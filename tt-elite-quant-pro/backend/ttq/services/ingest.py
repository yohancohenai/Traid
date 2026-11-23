"""Ingestion of provider data: raw payload preservation, identity resolution, result validation, quote linking."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from ttq.core.timeutil import as_utc, utcnow
from ttq.models import DataSource, Match, MatchSet, OddsQuote, RawObservation, Tournament
from ttq.odds.math import american_to_decimal, decimal_to_american
from ttq.providers.base import OddsProvider, ProviderMatch, ProviderQuote, ProviderUnavailable, ResultsProvider
from ttq.services.identity import resolve_player

log = logging.getLogger(__name__)


def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def save_raw(db: Session, source_key: str, endpoint: str, payload, is_demo: bool) -> RawObservation:
    ro = RawObservation(source_key=source_key, endpoint=endpoint, payload=json.loads(json.dumps(payload, default=str)),
                        payload_hash=_hash(payload), is_demo=is_demo)
    db.add(ro)
    db.flush()
    return ro


def ensure_source(db: Session, key: str, name: str, kind: str, is_demo: bool) -> DataSource:
    s = db.scalar(select(DataSource).where(DataSource.key == key))
    if not s:
        s = DataSource(key=key, name=name, kind=kind, is_demo=is_demo)
        db.add(s)
        db.flush()
    return s


def validate_result(pm: ProviderMatch) -> tuple[bool, list[str]]:
    """Structural checks of a reported result. Returns (valid, problems)."""
    probs = []
    need = pm.best_of // 2 + 1
    if pm.status == "FINISHED":
        if pm.sets_p1 is None or pm.sets_p2 is None:
            probs.append("missing set score")
        elif max(pm.sets_p1, pm.sets_p2) != need or min(pm.sets_p1, pm.sets_p2) >= need:
            probs.append(f"set score {pm.sets_p1}-{pm.sets_p2} impossible for best of {pm.best_of}")
    if pm.set_points:
        w1 = w2 = 0
        for a, b in pm.set_points:
            hi, lo = max(a, b), min(a, b)
            if pm.status == "FINISHED" and not (hi >= 11 and (hi - lo == 2 if hi > 11 else hi - lo >= 2)):
                probs.append(f"invalid game score {a}-{b}")
            w1 += a > b
            w2 += b > a
        if pm.status == "FINISHED" and (w1, w2) != (pm.sets_p1, pm.sets_p2):
            probs.append("game scores inconsistent with set score")
    return (not probs), probs


def upsert_match(db: Session, pm: ProviderMatch, provider: ResultsProvider) -> tuple[Match | None, str]:
    is_demo = provider.is_demo
    p1 = resolve_player(db, pm.p1_name, provider.key, pm.p1_ref, is_demo)
    p2 = resolve_player(db, pm.p2_name, provider.key, pm.p2_ref, is_demo)
    if p1 is None or p2 is None:
        return None, "identity_review"
    if p1 == p2:
        return None, "same_player"
    t = None
    if pm.tournament_ref:
        t = db.scalar(select(Tournament).where(Tournament.source_key == provider.key, Tournament.source_ref == pm.tournament_ref))
        if not t:
            t = Tournament(name=pm.tournament_name or pm.tournament_ref, level=pm.tournament_level,
                           starts_at=pm.scheduled_at, source_key=provider.key, source_ref=pm.tournament_ref, is_demo=is_demo)
            db.add(t)
            db.flush()
    m = db.scalar(select(Match).where(Match.source_key == provider.key, Match.source_ref == pm.source_ref))
    created = m is None
    if created:
        m = Match(source_key=provider.key, source_ref=pm.source_ref, player1_id=p1, player2_id=p2,
                  scheduled_at=as_utc(pm.scheduled_at), tournament_id=t.id if t else None, is_demo=is_demo,
                  best_of=pm.best_of, result_sources=[])
        db.add(m)
    elif (m.player1_id, m.player2_id) != (p1, p2):
        log.warning("player mismatch on update", extra={"match_id": m.id})
        return m, "player_mismatch"
    if m.status in ("FINISHED", "RETIRED", "WALKOVER", "CANCELLED") and m.result_verified:
        return m, "final"  # never overwrite a verified final result silently
    m.scheduled_at = as_utc(pm.scheduled_at)
    m.status = pm.status
    m.updated_at = utcnow()
    if pm.status == "LIVE":
        m.started_at = m.started_at or as_utc(pm.scheduled_at)
        m.live_state = pm.live_state
        m.live_updated_at = utcnow()
    if pm.status in ("FINISHED", "RETIRED", "WALKOVER"):
        valid, problems = validate_result(pm)
        m.finished_at = as_utc(pm.finished_at) or utcnow()
        m.sets_p1, m.sets_p2 = pm.sets_p1, pm.sets_p2
        m.live_state = None
        srcs = list(m.result_sources or [])
        srcs.append({"source": provider.key, "sets": [pm.sets_p1, pm.sets_p2], "status": pm.status,
                     "at": utcnow().isoformat(), "valid": valid, "problems": problems})
        m.result_sources = srcs
        if valid and pm.status == "FINISHED":
            m.winner_id = p1 if pm.sets_p1 > pm.sets_p2 else p2
        conflicting = len({tuple(s["sets"]) + (s["status"],) for s in srcs}) > 1
        m.result_verified = bool(valid and provider.verified and not conflicting)
        db.flush()
        m.sets.clear()
        for i, (a, b) in enumerate(pm.set_points, 1):
            m.sets.append(MatchSet(set_no=i, p1_points=a, p2_points=b))
        cov = 1.0 if pm.set_points else 0.0
        m.data_quality = "HIGH" if (valid and cov) else ("MEDIUM" if valid else "LOW")
    db.flush()
    return m, "created" if created else "updated"


def ingest_results(db: Session, provider: ResultsProvider, since: datetime, until: datetime) -> dict:
    src = ensure_source(db, provider.key, provider.name, "results", provider.is_demo)
    try:
        matches, raw = provider.fetch_matches(since, until)
    except ProviderUnavailable as e:
        src.status, src.last_error, src.last_error_at = "UNAVAILABLE", str(e), utcnow()
        return {"status": "UNAVAILABLE", "error": str(e)}
    except Exception as e:  # noqa
        src.status, src.last_error, src.last_error_at = "ERROR", str(e)[:1000], utcnow()
        log.exception("results ingest failed", extra={"provider": provider.key})
        return {"status": "ERROR", "error": str(e)}
    save_raw(db, provider.key, f"matches?since={since.isoformat()}&until={until.isoformat()}",
             {"summary": raw, "matches": [pm.__dict__ for pm in matches]} if len(matches) < 2000 else {"summary": raw},
             provider.is_demo)
    counts: dict[str, int] = {}
    for pm in matches:
        _, st = upsert_match(db, pm, provider)
        counts[st] = counts.get(st, 0) + 1
    src.status, src.last_success_at = "OK", utcnow()
    return {"status": "OK", "fetched": len(matches), **counts}


def find_match_for_quote(db: Session, q: ProviderQuote, provider: OddsProvider) -> Match | None:
    if q.match_source_ref:
        return db.scalar(select(Match).where(Match.source_ref == q.match_source_ref, Match.is_demo == provider.is_demo))
    p1 = resolve_player(db, q.p1_name, provider.key, None, provider.is_demo, create_if_new=False)
    p2 = resolve_player(db, q.p2_name, provider.key, None, provider.is_demo, create_if_new=False)
    if not p1 or not p2:
        return None
    ct = as_utc(q.commence_time)
    cands = db.scalars(select(Match).where(
        or_((Match.player1_id == p1) & (Match.player2_id == p2), (Match.player1_id == p2) & (Match.player2_id == p1)),
        Match.scheduled_at.between(ct - timedelta(hours=2), ct + timedelta(hours=2)))).all()
    if len(cands) != 1:
        return None  # ambiguous or unknown -> reject
    m = cands[0]
    if m.player1_id == p2:  # provider lists players in the opposite order -> flip selection
        q.selection = {"p1": "p2", "p2": "p1"}.get(q.selection, q.selection)
    return m


def validate_quote_values(american: int | None, decimal_odds: float | None) -> tuple[int, float]:
    if american is None and decimal_odds is None:
        raise ValueError("odds missing")
    if american is not None:
        d = american_to_decimal(american)
        if decimal_odds is not None and abs(d - decimal_odds) > 0.02:
            raise ValueError("american/decimal mismatch")
        decimal_odds = d
    if not (1.01 <= decimal_odds <= 101):
        raise ValueError("decimal odds out of range")
    return (american if american is not None else decimal_to_american(decimal_odds)), round(decimal_odds, 4)


def ingest_odds(db: Session, provider: OddsProvider, now: datetime | None = None) -> dict:
    now = now or utcnow()
    src = ensure_source(db, provider.key, provider.name, "odds", provider.is_demo)
    try:
        quotes, raw = provider.fetch_odds(now)
    except ProviderUnavailable as e:
        src.status, src.last_error, src.last_error_at = "UNAVAILABLE", str(e), utcnow()
        return {"status": "UNAVAILABLE", "error": str(e)}
    except Exception as e:  # noqa
        src.status, src.last_error, src.last_error_at = "ERROR", str(e)[:1000], utcnow()
        log.exception("odds ingest failed", extra={"provider": provider.key})
        return {"status": "ERROR", "error": str(e)}
    ro = save_raw(db, provider.key, "odds", raw if provider.is_demo else raw, provider.is_demo)
    stored = rejected = 0
    for q in quotes:
        m = find_match_for_quote(db, q, provider)
        if m is None or m.status not in ("SCHEDULED",):
            rejected += 1
            continue
        try:
            am, dec = validate_quote_values(q.american, q.decimal_odds)
        except ValueError:
            rejected += 1
            continue
        prev = db.scalar(select(OddsQuote).where(OddsQuote.match_id == m.id, OddsQuote.bookmaker_key == q.bookmaker_key,
                                                 OddsQuote.market == q.market, OddsQuote.selection == q.selection,
                                                 OddsQuote.line.is_(None) if q.line is None else OddsQuote.line == q.line)
                         .order_by(OddsQuote.captured_at.desc()).limit(1))
        if prev and prev.american == am and prev.availability == q.availability and prev.source_key == provider.key:
            prev.last_confirmed_at = now  # unchanged price re-observed: refresh freshness, keep history compact
            if q.quoted_at and (prev.quoted_at is None or as_utc(q.quoted_at) > as_utc(prev.quoted_at)):
                prev.quoted_at = as_utc(q.quoted_at)
            stored += 1
            continue
        db.add(OddsQuote(match_id=m.id, bookmaker_key=q.bookmaker_key, market=q.market, selection=q.selection,
                         line=q.line, american=am, decimal_odds=dec, quoted_at=as_utc(q.quoted_at), captured_at=now,
                         source_key=provider.key, availability=q.availability, settlement_rules=q.settlement_rules,
                         raw_observation_id=ro.id, is_demo=provider.is_demo))
        stored += 1
    src.status, src.last_success_at = "OK", utcnow()
    return {"status": "OK", "stored": stored, "rejected": rejected}


def mark_closing_quotes(db: Session) -> int:
    """For matches that have started, flag the last pre-start quote per (book, market, selection, line) as closing."""
    n = 0
    started = db.scalars(select(Match).where(Match.status.in_(["LIVE", "FINISHED", "RETIRED"]),
                                             Match.scheduled_at > utcnow() - timedelta(days=3))).all()
    for m in started:
        qs = db.scalars(select(OddsQuote).where(OddsQuote.match_id == m.id, OddsQuote.captured_at <= m.scheduled_at)
                        .order_by(OddsQuote.captured_at)).all()
        last = {}
        for q in qs:
            last[(q.bookmaker_key, q.market, q.selection, q.line)] = q
        for q in last.values():
            if not q.is_closing:
                q.is_closing = True
                n += 1
    return n
