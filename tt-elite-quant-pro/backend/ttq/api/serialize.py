from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from ttq.core.config import get_settings
from ttq.core.timeutil import as_utc, utcnow
from ttq.models import Match, OddsQuote, Player, Prediction, Recommendation
from ttq.odds.math import decimal_to_american
from ttq.services.scanner import effective_max_age, is_executable, observed_at, quote_status


def iso(dt):
    return as_utc(dt).isoformat() if dt else None


def num(x):
    return float(x) if isinstance(x, Decimal) else x


def row(obj, exclude=()):
    return {k: (iso(v) if isinstance(v, datetime) else num(v)) for k, v in obj.__dict__.items()
            if not k.startswith("_") and k not in exclude}


def match_brief(m: Match) -> dict:
    return {"id": m.id, "player1": {"id": m.player1_id, "name": m.player1.canonical_name},
            "player2": {"id": m.player2_id, "name": m.player2.canonical_name}, "scheduled_at": iso(m.scheduled_at),
            "status": m.status, "sets_p1": m.sets_p1, "sets_p2": m.sets_p2, "is_demo": m.is_demo,
            "competition": m.competition, "tournament": m.tournament.name if m.tournament else None,
            "result_verified": m.result_verified, "data_quality": m.data_quality,
            "set_scores": [[s.p1_points, s.p2_points] for s in m.sets], "live_state": m.live_state,
            "live_updated_at": iso(m.live_updated_at), "finished_at": iso(m.finished_at)}


def quote_out(q: OddsQuote, m: Match, max_age: int | None = None) -> dict:
    max_age = max_age or get_settings().max_quote_age_seconds
    st = quote_status(q, m, max_age)
    return {"id": q.id, "bookmaker": q.bookmaker_key, "market": q.market, "selection": q.selection, "line": q.line,
            "american": q.american, "decimal": float(q.decimal_odds), "quoted_at": iso(q.quoted_at),
            "captured_at": iso(q.captured_at), "last_confirmed_at": iso(observed_at(q)), "source": q.source_key, "availability": q.availability,
            "is_closing": q.is_closing, "settlement_rules": q.settlement_rules, "is_demo": q.is_demo,
            "freshness": st, "age_seconds": (utcnow() - observed_at(q)).total_seconds(),
            "executable": is_executable(q.bookmaker_key) and st == "VERIFIED",
            "executable_note": None if is_executable(q.bookmaker_key) else "Reference only: not available to bet in Florida."}


def pred_out(p: Prediction | None) -> dict | None:
    if not p:
        return None
    return {"id": p.id, "created_at": iso(p.created_at), "as_of": iso(p.as_of), "p1_win": p.p1_win, "p2_win": 1 - p.p1_win,
            "p1_ci": [p.p1_ci_low, p.p1_ci_high], "p_game": p.p_set, "scorelines": p.scorelines,
            "components": p.component_probs, "data_quality": p.data_quality, "model_version_id": p.model_version_id,
            "fair_p1": {"decimal": 1 / p.p1_win, "american": decimal_to_american(1 / p.p1_win)},
            "fair_p2": {"decimal": 1 / (1 - p.p1_win), "american": decimal_to_american(1 / (1 - p.p1_win))},
            "features": p.features, "is_demo": p.is_demo}


def rec_out(db: Session, r: Recommendation) -> dict:
    m = db.get(Match, r.match_id)
    q = db.get(OddsQuote, r.quote_id) if r.quote_id else None
    qo = quote_out(q, m, effective_max_age(db)) if q else None
    sel_name = m.player1.canonical_name if r.selection == "p1" else m.player2.canonical_name if r.selection == "p2" else r.selection
    return {"id": r.id, "match": match_brief(m), "market": r.market, "selection": r.selection, "selection_name": sel_name,
            "line": r.line, "sportsbook": "Hard Rock Bet", "decimal_odds": r.decimal_odds,
            "american_odds": decimal_to_american(r.decimal_odds) if r.decimal_odds else None,
            "quote": qo, "quote_status": qo["freshness"] if qo else "UNAVAILABLE",
            "model_prob": r.model_prob, "prob_interval": [r.prob_low, r.prob_high],
            "break_even": (1 / r.decimal_odds) if r.decimal_odds else None, "ev": r.ev, "ev_low": r.ev_low, "edge": r.edge,
            "novig_prob": r.novig_prob,
            "fair_odds": {"decimal": 1 / r.model_prob, "american": decimal_to_american(1 / r.model_prob)} if 0 < r.model_prob < 1 else None,
            "data_quality": r.data_quality, "model_agreement": r.model_agreement, "reasons_for": r.reasons_for,
            "reasons_against": r.reasons_against, "filters": r.filter_results,
            # A recommendation can only QUALIFY while its quote is still fresh at read time
            "status": ("WATCH" if r.status == "QUALIFIES" and (not qo or qo["freshness"] != "VERIFIED") else r.status),
            "status_at_scan": r.status,
            "user_action": r.user_action, "created_at": iso(r.created_at), "is_demo": r.is_demo,
            "hypothetical_result": r.hypothetical_result}
