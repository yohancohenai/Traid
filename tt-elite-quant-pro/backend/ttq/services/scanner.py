"""Hard Rock market scanner: compares verified Hard Rock prices with independent model probabilities.

Status rules
- QUALIFIES : verified fresh Hard Rock quote AND every research filter passes.
- WATCH     : positive estimated EV but at least one filter fails (e.g. stale quote, low data quality), or a
              derivative market (scoreline / handicap / totals) that is not independently validated for staking.
- PASS      : everything else.
DraftKings and other books are reference-only and can never be executable for a Florida user.
"""
from __future__ import annotations

import math
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ttq.core.config import get_settings
from ttq.core.timeutil import as_utc, utcnow
from ttq.models import Bookmaker, Match, OddsQuote, Prediction, Recommendation
from ttq.odds.math import expected_value, no_vig_multiplicative, implied_prob
from ttq.services.app_settings import QUALITY_ORDER, get_filters, get_setting
from ttq.services.modeling import latest_prediction
from ttq.sim.tt import full_match_model, prob_set_handicap

PRIMARY_BOOK = "hardrock"
DEFAULT_BOOKS = [
    {"key": "hardrock", "name": "Hard Rock Bet", "executable_regions": ["US-FL"], "is_primary": True},
    {"key": "draftkings", "name": "DraftKings (reference only)", "executable_regions": [], "is_primary": False},
]


def ensure_bookmakers(db: Session):
    for b in DEFAULT_BOOKS:
        if not db.scalar(select(Bookmaker).where(Bookmaker.key == b["key"])):
            db.add(Bookmaker(**b))
    db.flush()


def is_executable(book_key: str, region: str | None = None) -> bool:
    """Hard invariant: DraftKings is never executable in Florida regardless of DB contents."""
    region = region or get_settings().user_region
    if book_key == "draftkings" and region == "US-FL":
        return False
    return any(b["key"] == book_key and region in b["executable_regions"] for b in DEFAULT_BOOKS)


def observed_at(q: OddsQuote):
    """Conservative freshness time: the latest time WE observed this price, but never later than the provider's own
    quote timestamp (a cached provider price re-served to us is not fresh)."""
    ours = max(as_utc(q.captured_at), as_utc(q.last_confirmed_at)) if q.last_confirmed_at else as_utc(q.captured_at)
    return min(ours, as_utc(q.quoted_at)) if q.quoted_at else ours


def effective_max_age(db, is_demo: bool = False) -> int:
    from ttq.services.app_settings import get_filters
    return min(get_filters(db, is_demo)["max_quote_age_seconds"], get_settings().max_quote_age_seconds)


def quote_status(q: OddsQuote | None, m: Match, max_age: int, now=None) -> str:
    now = now or utcnow()
    if q is None:
        return "UNAVAILABLE"
    if not q.source_key or q.captured_at is None:
        return "STALE"
    age = (now - observed_at(q)).total_seconds()
    if age > max_age or age < -60:
        return "STALE"
    if q.availability != "OPEN" or m.status != "SCHEDULED" or as_utc(m.scheduled_at) <= now:
        return "STALE"
    return "VERIFIED"


def latest_quotes(db: Session, match_id: int, book: str, market: str = "match_winner") -> dict:
    qs = db.scalars(select(OddsQuote).where(OddsQuote.match_id == match_id, OddsQuote.bookmaker_key == book,
                                            OddsQuote.market == market).order_by(OddsQuote.captured_at)).all()
    out = {}
    for q in qs:
        out[(q.selection, q.line)] = q
    return out


def opening_quote(db: Session, match_id: int, book: str, selection: str) -> OddsQuote | None:
    return db.scalar(select(OddsQuote).where(OddsQuote.match_id == match_id, OddsQuote.bookmaker_key == book,
                                             OddsQuote.market == "match_winner", OddsQuote.selection == selection)
                     .order_by(OddsQuote.captured_at).limit(1))


def dec_ev_too_big(p, dec, cap=0.25):
    return dec is not None and expected_value(p, dec) > cap


def build_reasons(pred: Prediction, side: str, p: float, novig: float | None, dk_novig: float | None,
                  qstat: str, age: float | None, open_q: OddsQuote | None, cur_dec: float | None) -> tuple[list, list]:
    f = pred.features or {}
    s = 1 if side == "p1" else -1
    pro, con = [], []

    def g(k, d=0.0):
        v = f.get(k)
        return d if v is None else float(v)

    ed = s * g("elo_diff")
    (pro if ed > 0 else con).append(f"Elo gap {ed:+.0f} points for the selection.")
    form = s * g("l10_diff")
    if abs(form) > 0.05:
        (pro if form > 0 else con).append(f"Last-10 shrunk win rate differential {form:+.0%}.")
    adj = s * g("adj_form_diff")
    if abs(adj) > 0.02:
        (pro if adj > 0 else con).append(f"Opponent-adjusted recent form {adj:+.3f} vs expectation.")
    if g("h2h_n") >= 3:
        h = g("h2h_share") if side == "p1" else 1 - g("h2h_share")
        (pro if h > 0.5 else con).append(f"Head-to-head (shrunk) {h:.0%} over {int(g('h2h_n'))} meetings.")
    sp = s * g("set_pct_diff")
    if abs(sp) > 0.03:
        (pro if sp > 0 else con).append(f"Game-win share differential {sp:+.1%}.")
    comps = pred.component_probs or {}
    if comps:
        vals = [v if side == "p1" else 1 - v for v in comps.values()]
        spread = max(vals) - min(vals)
        (pro if spread < 0.05 else con).append(
            f"Model {'agreement' if spread < 0.05 else 'disagreement'}: component probabilities {min(vals):.0%}-{max(vals):.0%}.")
    if novig is not None and dec_ev_too_big(p, cur_dec):
        con.append("Estimated EV is implausibly large; most such gaps are stale/wrong prices or data errors. Verify before acting.")
    if novig is not None and p - novig > 0.10:
        con.append(f"Large gap vs Hard Rock no-vig ({novig:.0%}); the market may hold information the model lacks.")
    if dk_novig is not None:
        (pro if p > dk_novig else con).append(f"DraftKings reference no-vig {dk_novig:.0%} (reference only, not executable in FL).")
    if min(g("_n1"), g("_n2")) < 20:
        con.append(f"Small sample: {int(g('_n1'))} / {int(g('_n2'))} prior matches.")
    if pred.data_quality != "HIGH":
        con.append(f"Data quality {pred.data_quality}.")
    if qstat != "VERIFIED":
        con.append(f"Hard Rock price is {qstat}{f' ({age/60:.0f} min old)' if age is not None else ''}; re-check in the app.")
    if open_q is not None and cur_dec is not None:
        mv = float(cur_dec) / float(open_q.decimal_odds) - 1
        if abs(mv) > 0.02:
            (con if mv < 0 else pro).append(f"Price moved {mv:+.1%} since first observed ({float(open_q.decimal_odds):.2f} -> {cur_dec:.2f}).")
    con.append("Estimated EV assumes the model probability is accurate; it is not a guarantee.")
    return pro, con


def evaluate(p, lo, hi, dec, novig, dq, qstat, n_min, spread, F) -> tuple[str, dict, float | None, float | None]:
    ev = expected_value(p, dec) if dec else None
    ev_low = expected_value(lo, dec) if dec else None
    checks = {
        "quote_verified": qstat == "VERIFIED",
        "min_ev": ev is not None and ev >= F["min_ev"],
        "plausible_ev": ev is not None and ev <= F.get("max_ev", 0.25),
        "min_ev_low": ev_low is not None and ev_low >= F["min_ev_low"],
        "min_edge": novig is not None and (p - novig) >= F["min_edge"],
        "data_quality": QUALITY_ORDER[dq] >= QUALITY_ORDER[F["min_data_quality"]],
        "sample_size": n_min >= F["min_player_matches"],
        "model_agreement": spread <= F["max_model_disagreement"],
        "odds_range": dec is not None and F["min_decimal_odds"] <= dec <= F["max_decimal_odds"],
    }
    if all(checks.values()):
        st = "QUALIFIES"
    elif ev is not None and ev > F["watch_min_ev"]:
        st = "WATCH"
    else:
        st = "PASS"
    return st, checks, ev, ev_low


def scan(db: Session, is_demo: bool | None = None, now=None) -> dict:
    """Scan all scheduled matches with a current prediction. Returns counts. Idempotent: a new recommendation row is
    only written when the underlying prediction, quote or status changes."""
    ensure_bookmakers(db)
    now = now or utcnow()
    q = select(Match).where(Match.status == "SCHEDULED", Match.scheduled_at > now,
                            Match.scheduled_at <= now + timedelta(hours=48))
    if is_demo is not None:
        q = q.where(Match.is_demo == is_demo)
    counts = {"QUALIFIES": 0, "WATCH": 0, "PASS": 0, "matches": 0}
    new_qualifiers = []
    for m in db.scalars(q).all():
        pred = latest_prediction(db, m.id)
        if not pred:
            continue
        F = get_filters(db, m.is_demo)
        counts["matches"] += 1
        hr = latest_quotes(db, m.id, PRIMARY_BOOK)
        dk = latest_quotes(db, m.id, "draftkings")
        hr1, hr2 = hr.get(("p1", None)), hr.get(("p2", None))
        dk1, dk2 = dk.get(("p1", None)), dk.get(("p2", None))
        hr_nv = no_vig_multiplicative([float(hr1.decimal_odds), float(hr2.decimal_odds)]) if hr1 and hr2 else None
        dk_nv = no_vig_multiplicative([float(dk1.decimal_odds), float(dk2.decimal_odds)]) if dk1 and dk2 else None
        f = pred.features or {}
        n_min = int(min(f.get("_n1") or 0, f.get("_n2") or 0))
        for side, qt, idx in (("p1", hr1, 0), ("p2", hr2, 1)):
            p = pred.p1_win if side == "p1" else 1 - pred.p1_win
            lo, hi = (pred.p1_ci_low, pred.p1_ci_high) if side == "p1" else (1 - pred.p1_ci_high, 1 - pred.p1_ci_low)
            comps = [v if side == "p1" else 1 - v for v in (pred.component_probs or {}).values()] or [p]
            spread = max(comps) - min(comps)
            qstat = quote_status(qt, m, effective_max_age(db, m.is_demo), now)
            dec = float(qt.decimal_odds) if qt else None
            novig = hr_nv[idx] if hr_nv else None
            st, checks, ev, ev_low = evaluate(p, lo, hi, dec, novig, pred.data_quality, qstat, n_min, spread, F)
            age = (now - observed_at(qt)).total_seconds() if qt else None
            pro, con = build_reasons(pred, side, p, novig, dk_nv[idx] if dk_nv else None, qstat, age,
                                     opening_quote(db, m.id, PRIMARY_BOOK, side), dec)
            prev = db.scalar(select(Recommendation).where(Recommendation.match_id == m.id, Recommendation.selection == side,
                                                          Recommendation.market == "match_winner", Recommendation.is_current.is_(True)))
            if prev and prev.prediction_id == pred.id and prev.quote_id == (qt.id if qt else None) and prev.status == st \
                    and prev.quote_status == qstat:
                prev.filter_results, prev.reasons_against = checks, con
                counts[st] += 1
                continue
            if prev:
                prev.is_current = False
            rec = Recommendation(match_id=m.id, prediction_id=pred.id, quote_id=qt.id if qt else None, market="match_winner",
                                 selection=side, bookmaker_key=PRIMARY_BOOK, decimal_odds=dec, model_prob=p, prob_low=lo,
                                 prob_high=hi, ev=ev, ev_low=ev_low, edge=(p - novig) if novig is not None else None,
                                 novig_prob=novig, status=st, reasons_for=pro, reasons_against=con, filter_results=checks,
                                 data_quality=pred.data_quality,
                                 model_agreement={"spread": spread, "components": pred.component_probs},
                                 quote_status=qstat, is_demo=m.is_demo,
                                 user_action=prev.user_action if prev and prev.user_action != "RECOMMENDED" else "RECOMMENDED")
            db.add(rec)
            db.flush()
            counts[st] += 1
            if st == "QUALIFIES" and (not prev or prev.status != "QUALIFIES"):
                new_qualifiers.append(rec.id)
        # derivative markets: only when Hard Rock quotes exist for them; capped at WATCH
        derivative_scan(db, m, pred, F, now)
    counts["new_qualifiers"] = new_qualifiers
    return counts


def derivative_scan(db: Session, m: Match, pred: Prediction, F: dict, now):
    for market in ("set_handicap", "correct_score"):
        qs = latest_quotes(db, m.id, PRIMARY_BOOK, market)
        if not qs:
            continue
        sl = pred.scorelines or full_match_model(pred.p1_win, with_points=False)["scorelines"]
        for (sel, line), qt in qs.items():
            if market == "correct_score":
                a, b = sel.split("-")
                p = sl.get(f"{a}-{b}")
            else:
                side, ln = sel, line or 0
                p_a = prob_set_handicap(sl, ln if side == "p1" else -ln)
                p = p_a if side == "p1" else 1 - p_a
            if p is None:
                continue
            dec = float(qt.decimal_odds)
            ev = expected_value(p, dec)
            qstat = quote_status(qt, m, F["max_quote_age_seconds"], now)
            st = "WATCH" if (ev > F["min_ev"] and qstat == "VERIFIED") else "PASS"
            prev = db.scalar(select(Recommendation).where(Recommendation.match_id == m.id, Recommendation.market == market,
                                                          Recommendation.selection == sel, Recommendation.is_current.is_(True)))
            if prev and prev.quote_id == qt.id and prev.prediction_id == pred.id:
                continue
            if prev:
                prev.is_current = False
            db.add(Recommendation(match_id=m.id, prediction_id=pred.id, quote_id=qt.id, market=market, selection=sel,
                                  line=line, bookmaker_key=PRIMARY_BOOK, decimal_odds=dec, model_prob=p, prob_low=p,
                                  prob_high=p, ev=ev, ev_low=None, edge=None, novig_prob=None, status=st,
                                  reasons_for=[f"Derived from match model via exact best-of-5 game model (p_game={pred.p_set or 0:.3f})."],
                                  reasons_against=["Derivative market: not independently validated for staking; capped at WATCH.",
                                                   "Assumes independent games with constant per-game probability."],
                                  filter_results={"quote_verified": qstat == "VERIFIED"}, data_quality=pred.data_quality,
                                  model_agreement={}, quote_status=qstat, is_demo=m.is_demo))
