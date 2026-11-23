"""Scheduled jobs. Each job is idempotent, records a JobRun row and is safe to run concurrently with the API."""
from __future__ import annotations

import logging
import traceback
from datetime import timedelta

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ttq.core.db import session_scope
from ttq.core.timeutil import as_utc, utcnow
from ttq.models import Bet, DataSource, JobRun, Match, OddsQuote, Recommendation
from ttq.providers.registry import odds_providers, results_providers
from ttq.services import backtest, ingest, modeling, monitoring, scanner, settlement
from ttq.services.alerts import raise_alert
from ttq.services.app_settings import get_setting

log = logging.getLogger(__name__)


def run_job(name: str, fn, *args, **kw) -> dict:
    with session_scope() as db:
        jr = JobRun(job=name)
        db.add(jr)
        db.flush()
        jid = jr.id
    try:
        with session_scope() as db:
            res = fn(db, *args, **kw)
        ok = True
    except Exception as e:  # noqa
        log.exception("job failed", extra={"event": name})
        res, ok = {"error": str(e), "trace": traceback.format_exc()[-2000:]}, False
    with session_scope() as db:
        jr = db.get(JobRun, jid)
        jr.finished_at, jr.ok, jr.detail = utcnow(), ok, _jsonable(res)
    return res


def _jsonable(x):
    import json
    return json.loads(json.dumps(x, default=str))


def complete_tournament_refs(db: Session, source_key: str) -> set[str]:
    """Tournaments whose every match is final: never re-fetched."""
    from sqlalchemy import func
    from ttq.models import Tournament
    rows = db.execute(select(Tournament.source_ref, func.count(Match.id),
                             func.count(Match.id).filter(Match.status.in_(["SCHEDULED", "LIVE"])))
                      .join(Match, Match.tournament_id == Tournament.id)
                      .where(Tournament.source_key == source_key).group_by(Tournament.source_ref)).all()
    return {ref for ref, n, open_ in rows if n and not open_}


def ingest_results_job(db: Session) -> dict:
    now = utcnow()
    out = {}
    for p in results_providers():
        if p.key == "ttseries":
            p.skip_refs = complete_tournament_refs(db, "ttseries")
            out[p.key] = ingest.ingest_results(db, p, now - timedelta(days=1), now + timedelta(days=2))
        else:
            out[p.key] = ingest.ingest_results(db, p, now - timedelta(days=3), now + timedelta(days=2))
    return out


def backfill_ttseries(from_id: int, to_id: int | None = None, stop_after_empty: int = 15) -> dict:
    """Walk tt-series tournament ids, one committed transaction per tournament (resumable). Already-complete
    tournaments are skipped without a request."""
    from ttq.providers.ttseries import TTSeriesResultsProvider
    p = TTSeriesResultsProvider()
    if to_id is None:
        to_id = max(c.tid for c in p.list_tournaments(max_pages=1))
    with session_scope() as db:
        done = complete_tournament_refs(db, p.key)
        ingest.ensure_source(db, p.key, p.name, "results", False)
    stats = {"fetched": 0, "skipped": 0, "matches": 0, "empty": 0, "to_id": to_id}
    empties = 0
    for tid in range(from_id, to_id + 1):
        if f"tts-{tid}" in done:
            stats["skipped"] += 1
            continue
        ms, page = p.fetch_tournament(tid)
        stats["fetched"] += 1
        if not ms:
            stats["empty"] += 1
            if stats["matches"]:  # leading gaps (ids that never existed) are not the end of the archive
                empties += 1
                if empties >= stop_after_empty:
                    break
            continue
        empties = 0
        with session_scope() as db:
            ingest.save_raw(db, p.key, f"/tournaments/?ttes_tournament={tid}", {"html": page}, False)
            for pm in ms:
                ingest.upsert_match(db, pm, p)
            src = db.scalar(select(DataSource).where(DataSource.key == p.key))
            src.status, src.last_success_at = "OK", utcnow()
        stats["matches"] += len(ms)
        if stats["fetched"] % 25 == 0:
            log.info(f"backfill progress: tournament {tid}/{to_id}, {stats['matches']} matches")
    return stats


def ingest_odds_job(db: Session) -> dict:
    out = {p.key: ingest.ingest_odds(db, p) for p in odds_providers()}
    out["closing_marked"] = ingest.mark_closing_quotes(db)
    return out


def predict_scan_job(db: Session) -> dict:
    out = {}
    for is_demo in (False, True):
        tag = "demo" if is_demo else "live"
        out[f"predict_{tag}"] = modeling.predict_upcoming(db, is_demo)
        res = scanner.scan(db, is_demo)
        out[f"scan_{tag}"] = {k: v for k, v in res.items() if k != "new_qualifiers"}
        for rid in res["new_qualifiers"]:
            r = db.get(Recommendation, rid)
            m = db.get(Match, r.match_id)
            raise_alert(db, "opportunity", f"Qualifying research opportunity: match {m.id}",
                        f"{m.player1.canonical_name} vs {m.player2.canonical_name} ({m.scheduled_at:%Y-%m-%d %H:%M} UTC)\n"
                        f"Selection {r.selection} @ Hard Rock {r.decimal_odds:.2f} (verified quote captured at "
                        f"{scanner.observed_at(db.get(OddsQuote, r.quote_id)):%H:%M:%S} UTC). Est. EV {r.ev:+.1%}, model {r.model_prob:.1%}.\n"
                        f"Re-check the price in the Hard Rock app before placing anything manually. Estimated EV is not a guarantee.",
                        f"opp:{rid}", "INFO", is_demo)
        _price_and_divergence_alerts(db, is_demo)
    return out


def _price_and_divergence_alerts(db: Session, is_demo: bool):
    cfg = get_setting(db, "alerts")
    recs = db.scalars(select(Recommendation).where(Recommendation.is_current.is_(True), Recommendation.is_demo == is_demo,
                                                   Recommendation.quote_status == "VERIFIED",
                                                   Recommendation.market == "match_winner")).all()
    for r in recs:
        if r.novig_prob is not None and abs(r.model_prob - r.novig_prob) >= cfg["divergence_threshold"]:
            raise_alert(db, "divergence", f"Model/market divergence on match {r.match_id}",
                        f"Model {r.model_prob:.1%} vs Hard Rock no-vig {r.novig_prob:.1%} for {r.selection}. Large gaps often mean "
                        f"the market knows something the model does not.", f"div:{r.match_id}:{r.selection}:{r.prediction_id}",
                        "WARN", is_demo)
        if r.status in ("QUALIFIES", "WATCH") and r.quote_id:
            qs = db.scalars(select(OddsQuote).where(OddsQuote.match_id == r.match_id, OddsQuote.bookmaker_key == "hardrock",
                                                    OddsQuote.selection == r.selection, OddsQuote.market == "match_winner")
                            .order_by(OddsQuote.captured_at.desc()).limit(2)).all()
            if len(qs) == 2 and abs(float(qs[0].decimal_odds) / float(qs[1].decimal_odds) - 1) >= cfg["price_change_threshold"]:
                raise_alert(db, "price_change", f"Hard Rock price moved on match {r.match_id}",
                            f"{r.selection}: {float(qs[1].decimal_odds):.2f} -> {float(qs[0].decimal_odds):.2f} (verified at "
                            f"{qs[0].captured_at:%H:%M:%S} UTC).", f"px:{qs[0].id}", "INFO", is_demo)


def settle_job(db: Session) -> dict:
    out = settlement.settle_open_bets(db)
    out["recommendations_graded"] = settlement.settle_recommendations(db)
    for b in db.scalars(select(Bet).where(Bet.settled_at >= utcnow() - timedelta(minutes=30))).all():
        raise_alert(db, "settlement", f"Bet #{b.id} settled: {b.status}", f"Net {float(b.net_profit or 0):+.2f} USD at "
                    f"{float(b.accepted_decimal):.2f}.", f"settle:{b.id}:{b.status}:{b.net_profit}", "INFO", b.is_demo)
    for b in db.scalars(select(Bet).where(Bet.status == "SETTLEMENT_REVIEW")).all():
        raise_alert(db, "settlement_review", f"Bet #{b.id} needs manual settlement review",
                    "The result could not be verified or the market rule is ambiguous.", f"review:{b.id}", "WARN", b.is_demo)
    return out


def monitor_job(db: Session) -> dict:
    cfg = get_setting(db, "alerts")
    out = {}
    for s in db.scalars(select(DataSource)).all():
        if s.enabled and s.last_success_at and (utcnow() - as_utc(s.last_success_at)).total_seconds() > cfg["stale_provider_minutes"] * 60:
            s.status = "STALE"
            raise_alert(db, "provider_stale", f"Provider {s.name} is stale",
                        f"No successful update since {s.last_success_at:%Y-%m-%d %H:%M} UTC.",
                        f"stale:{s.key}:{s.last_success_at:%Y%m%d%H}", "WARN", s.is_demo)
    for is_demo in (False, True):
        h = monitoring.model_health(db, is_demo)
        out["demo" if is_demo else "live"] = h.get("status")
        if h.get("status") == "DRIFT":
            raise_alert(db, "model_drift", "Model calibration deteriorated",
                        f"Recent log loss {h['recent_log_loss']:.4f} vs reference {h['reference_log_loss']:.4f}.",
                        f"drift:{is_demo}:{utcnow():%Y%m%d}", "WARN", is_demo)
    return out


def retrain_job(db: Session) -> dict:
    out = {}
    for is_demo in (False, True):
        due, why = monitoring.retrain_due(db, is_demo)
        out["demo" if is_demo else "live"] = {"due": due, "why": why}
        if due:
            out[f"train_{'demo' if is_demo else 'live'}"] = modeling.train_and_register(db, is_demo, promote="auto")
    return out


def seed_demo(db: Session, fast: bool = False) -> dict:
    """Load the DEMO world: full history, archived opening/decision/closing quotes, training, filters, backtest."""
    from ttq.providers.demo import DemoOddsProvider, DemoResultsProvider, get_world
    w = get_world()
    rp, op = DemoResultsProvider(w), DemoOddsProvider(w)
    now = utcnow()
    res = ingest.ingest_results(db, rp, w.anchor - timedelta(days=1), now + timedelta(days=2))
    # archived quotes for past matches
    ms = {m.source_ref: m for m in db.scalars(select(Match).where(Match.is_demo.is_(True))).all()}
    have = {mid for (mid,) in db.execute(select(OddsQuote.match_id).where(OddsQuote.is_demo.is_(True)).distinct())}
    rows = []
    for wm in w.matches:
        m = ms.get(wm["ref"])
        if m is None or m.id in have or wm["sched"] > now:
            continue
        for at, opening, closing in ((wm["sched"] - timedelta(hours=18), True, False),
                                     (wm["sched"] - timedelta(minutes=60), False, False),
                                     (wm["sched"] - timedelta(minutes=5), False, True)):
            for q in op.quotes_for(wm, at, opening=opening):
                rows.append({"match_id": m.id, "bookmaker_key": q.bookmaker_key, "market": q.market, "selection": q.selection,
                             "american": q.american, "decimal_odds": q.decimal_odds, "quoted_at": at, "captured_at": at,
                             "source_key": op.key, "availability": "OPEN", "is_closing": closing,
                             "settlement_rules": q.settlement_rules, "is_demo": True})
    for i in range(0, len(rows), 10000):
        db.execute(insert(OddsQuote), rows[i:i + 10000])
    db.flush()
    odds = ingest.ingest_odds(db, op, now)
    tr = modeling.train_and_register(db, True, actor="seed", fast=fast, promote="auto")
    flt = backtest.select_filters(db, True)
    pred = modeling.predict_upcoming(db, True)
    sc = scanner.scan(db, True)
    bt = backtest.run_backtest(db, True, name="seed walk-forward (test period)")
    return {"results": res, "archived_quotes": len(rows), "current_odds": odds, "train": {k: tr.get(k) for k in ("status", "best_candidate", "decision")},
            "filters": flt.get("chosen"), "predict": pred, "scan": {k: v for k, v in sc.items() if k != "new_qualifiers"},
            "backtest": bt.get("outcome")}
