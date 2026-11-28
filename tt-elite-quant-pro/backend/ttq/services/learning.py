"""The bot's learning loop, run once a day by the cloud bot.

1. Result tracking happens every run (official results -> matches -> picks graded); retraining happens whenever
   enough new results have arrived (monitoring.retrain_due).
2. Daily self-check (this module): compare what the model predicted before each finished match with what happened,
   over the last N days of live (never back-tested) predictions. The pick threshold `picks_min_prob` then follows
   the evidence: it is the lowest win chance at which the model's favourites actually won at least as often as
   predicted (within a small tolerance), moved at most 0.02 per day and kept between 0.58 and 0.70.
   Every check is written to a log (app_settings["learning_log"]) shown on the dashboard, and a Telegram note is
   sent whenever the threshold changes.
3. Housekeeping: old duplicate predictions/recommendations are pruned so the database stays small and fast.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, exists, func, select, update
from sqlalchemy.orm import Session

from ttq.core.config import get_settings
from ttq.core.timeutil import as_utc, utcnow
from ttq.models import AppSetting, Bet, Match, OddsQuote, Prediction, RawObservation, Recommendation
from ttq.services.app_settings import get_setting, set_setting

log = logging.getLogger(__name__)

CANDIDATES = [0.58, 0.60, 0.62, 0.64, 0.66, 0.68, 0.70]
MIN_SAMPLE = 150          # favourites needed at a threshold before it can be trusted
TOLERANCE = 0.01          # actual may trail predicted by at most 1 point
MAX_STEP = 0.02           # change per day
LOOKBACK_DAYS = 7


def live_pairs(db: Session, since: datetime) -> list[tuple[float, bool]]:
    """(favourite's predicted win chance, did the favourite win) for finished live matches since `since`, using the
    last prediction made before the match started."""
    q = (select(Prediction.match_id, Prediction.p1_win, Prediction.as_of, Match.winner_id, Match.player1_id)
         .join(Match, Match.id == Prediction.match_id)
         .where(Match.is_demo.is_(False), Match.status == "FINISHED", Match.winner_id.isnot(None),
                Match.scheduled_at >= since, Prediction.is_backtest.is_(False), Prediction.as_of <= Match.scheduled_at))
    best: dict[int, tuple] = {}
    for mid, p1, as_of, winner, p1_id in db.execute(q):
        if mid not in best or as_of > best[mid][0]:
            best[mid] = (as_of, p1, winner == p1_id)
    out = []
    for _, p1, p1_won in best.values():
        fav_p = max(p1, 1 - p1)
        out.append((fav_p, p1_won if p1 >= 0.5 else not p1_won))
    return out


def calibration_table(pairs: list[tuple[float, bool]]) -> list[dict]:
    rows = []
    for c in CANDIDATES:
        sel = [(p, w) for p, w in pairs if p >= c]
        n = len(sel)
        rows.append({"min_prob": c, "n": n, "predicted": round(sum(p for p, _ in sel) / n, 4) if n else None,
                     "actual": round(sum(w for _, w in sel) / n, 4) if n else None})
    return rows


def choose_threshold(table: list[dict], current: float) -> tuple[float, str]:
    good = [r for r in table if r["n"] >= MIN_SAMPLE and r["actual"] >= r["predicted"] - TOLERANCE]
    if not any(r["n"] >= MIN_SAMPLE for r in table):
        return current, "not enough finished matches yet"
    target = good[0]["min_prob"] if good else CANDIDATES[-1]
    new = current + max(-MAX_STEP, min(MAX_STEP, target - current))
    new = round(min(CANDIDATES[-1], max(CANDIDATES[0], new)), 2)
    if new == current:
        return current, f"model reliable from {target:.0%}; threshold stays {current:.0%}"
    why = "model over-confident below it" if new > current else "model proved reliable lower down"
    return new, f"threshold {current:.0%} -> {new:.0%} ({why})"


def prune(db: Session, keep_days: int = 2, keep_pred_hours: int = 6) -> dict:
    """Delete superseded recommendations and predictions older than `keep_days` that nothing else needs: keeps the
    latest prediction per match, every back-test prediction, and anything a bet or recommendation still points to."""
    cutoff = utcnow() - timedelta(days=keep_days)
    r = db.execute(delete(Recommendation).where(    # superseded scan results hold old predictions alive
        Recommendation.is_current.is_(False), Recommendation.created_at < utcnow() - timedelta(hours=keep_pred_hours),
        ~exists().where(Bet.recommendation_id == Recommendation.id)).execution_options(synchronize_session=False))
    latest = (select(Prediction.match_id, func.max(Prediction.as_of).label("mx"))
              .where(Prediction.is_backtest.is_(False)).group_by(Prediction.match_id).subquery())
    p = db.execute(delete(Prediction).where(       # superseded predictions are only needed briefly
        Prediction.is_backtest.is_(False), Prediction.created_at < utcnow() - timedelta(hours=keep_pred_hours),
        ~exists().where(and_(latest.c.match_id == Prediction.match_id, latest.c.mx == Prediction.as_of)),
        ~exists().where(Recommendation.prediction_id == Prediction.id)).execution_options(synchronize_session=False))
    raw = db.execute(delete(RawObservation).where(
        RawObservation.fetched_at < utcnow() - timedelta(hours=12),     # raw logs are only for short-term audit
        ~exists().where(OddsQuote.raw_observation_id == RawObservation.id)).execution_options(synchronize_session=False))
    # The feature snapshot (large JSON) is only needed before a match; learning uses the probability alone.
    fin = select(Match.id).where(Match.status != "SCHEDULED", Match.scheduled_at < utcnow() - timedelta(hours=12))
    slim = db.execute(update(Prediction).where(Prediction.match_id.in_(fin), Prediction.features != {})
                      .values(features={}, scorelines={}).execution_options(synchronize_session=False))
    return {"recommendations_deleted": r.rowcount, "predictions_deleted": p.rowcount, "raw_deleted": raw.rowcount,
            "predictions_slimmed": slim.rowcount, "artifacts_deleted": prune_artifacts(db)}


def prune_artifacts(db: Session, keep_latest: int = 2) -> int:
    """Each retrain saves every candidate model (several MB); keep the champion's file and the latest few."""
    import glob
    import os
    from ttq.models import ModelVersion
    rows = db.execute(select(ModelVersion.artifact_path, ModelVersion.status, ModelVersion.version)).all()
    keep = {p for p, st, _ in rows if p and st == "CHAMPION"}
    keep |= {p for p, _, _ in sorted({(p, "", v) for p, _, v in rows if p}, key=lambda x: x[2])[-keep_latest:]}
    n = 0
    for f in glob.glob(os.path.join(get_settings().artifacts_dir, "run_*.joblib")):
        if f not in keep and os.path.abspath(f) not in {os.path.abspath(k) for k in keep}:
            try:
                os.remove(f)
                n += 1
            except OSError:
                pass
    return n


def daily_self_check(db: Session, now: datetime | None = None, force: bool = False) -> dict:
    now = now or utcnow()
    tz = ZoneInfo(get_setting(db, "display").get("timezone") or get_settings().user_timezone)
    today = now.astimezone(tz).date().isoformat()
    last = db.get(AppSetting, "learning_last")
    if not force and last and last.value.get("date") == today:
        return {"ran": False, "why": "already checked today"}
    cleaned = prune(db)
    pairs = live_pairs(db, now - timedelta(days=LOOKBACK_DAYS))
    table = calibration_table(pairs)
    cfg = get_setting(db, "alerts")
    current = float(cfg.get("picks_min_prob", 0.60))
    new, note = choose_threshold(table, current)
    if new != current:
        set_setting(db, "alerts", {"picks_min_prob": new})
        from ttq.services.alerts import raise_alert
        rows = "\n".join(f"  {r['min_prob']:.0%}+: predicted {r['predicted']:.1%}, won {r['actual']:.1%} (n={r['n']})"
                         for r in table if r["n"])
        raise_alert(db, "learning", "Bot self-check: pick rule updated",
                    f"{note}.\nLast {LOOKBACK_DAYS} days, model favorites:\n{rows}\nNo action needed.",
                    f"learning:{today}", "INFO", False, rate_limited=False)
    try:   # recalibrate set-score markets on live results (needs 800+ matches; keeps defaults until then)
        from ttq.services.set_markets import refit
        q = (select(Prediction.match_id, Prediction.p1_win, Prediction.as_of, Match.sets_p1, Match.sets_p2)
             .join(Match, Match.id == Prediction.match_id)
             .where(Match.is_demo.is_(False), Match.status == "FINISHED", Match.sets_p1.isnot(None),
                    Match.scheduled_at >= now - timedelta(days=30), Prediction.is_backtest.is_(False),
                    Prediction.as_of <= Match.scheduled_at))
        best: dict = {}
        for mid, p1, as_of, s1, s2 in db.execute(q):
            if mid not in best or as_of > best[mid][0]:
                best[mid] = (as_of, p1, s1, s2)
        rows = [(max(p1, 1 - p1), s1 if p1 >= 0.5 else s2, s2 if p1 >= 0.5 else s1, True)
                for _, p1, s1, s2 in best.values()]
        set_fit = refit(db, rows)
    except Exception:  # noqa
        set_fit = None
    entry = {"date": today, "set_market_refit": bool(set_fit), "matches": len(pairs), "threshold_before": current, "threshold_after": new,
             "note": note, "table": table, **cleaned}
    row = db.get(AppSetting, "learning_log")
    hist = (list(row.value.get("entries", [])) if row else [])[-59:] + [entry]
    for key, val in (("learning_log", {"entries": hist}), ("learning_last", {"date": today})):
        r = db.get(AppSetting, key)
        if r:
            r.value = val
        else:
            db.add(AppSetting(key=key, value=val))
    db.flush()
    return {"ran": True, **entry}


def prune_if_due(db: Session, hours: int = 3) -> dict:
    """Housekeeping every few hours (the database is saved and restored on every bot run, so it must stay small)."""
    now = utcnow()
    row = db.get(AppSetting, "prune_last")
    if row and now - datetime.fromisoformat(row.value["at"]) < timedelta(hours=hours):
        return {"ran": False}
    out = prune(db)
    if row:
        row.value = {"at": now.isoformat()}
    else:
        db.add(AppSetting(key="prune_last", value={"at": now.isoformat()}))
    db.flush()
    return {"ran": True, **out}
