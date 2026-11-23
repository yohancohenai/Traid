"""Result-driven settlement proposals. Applied automatically only when the result is verified and the market rule
is unambiguous; everything else goes to SETTLEMENT_REVIEW. Results are never invented."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ttq.core.timeutil import utcnow
from ttq.models import BankrollTransaction, Bet, Match, OddsQuote, Recommendation, SettlementProposal
from ttq.odds.math import clv, profit_for_result
from ttq.services.audit import audit


def grade(m: Match, market: str, selection: str, line: float | None) -> tuple[str | None, str, str]:
    """Return (result, confidence, reason). result None => cannot grade."""
    if m.status == "CANCELLED" or m.status == "POSTPONED":
        return "VOID", "LOW", "Match cancelled/postponed: usually void, but confirm against Hard Rock's settlement."
    if m.status in ("RETIRED", "WALKOVER"):
        return "VOID", "LOW", "Retirement/walkover: sportsbook rules vary (void vs. advance). Manual review required."
    if m.status != "FINISHED":
        return None, "LOW", "Match not finished."
    if not m.result_verified:
        return None, "LOW", "Result not verified (single unverified source or conflicting sources)."
    a, b = m.sets_p1, m.sets_p2
    if market == "match_winner":
        won = (a > b) if selection == "p1" else (b > a)
        return ("WON" if won else "LOST"), "HIGH", f"Final set score {a}-{b}."
    if market == "correct_score":
        return ("WON" if selection == f"{a}-{b}" else "LOST"), "HIGH", f"Final set score {a}-{b}."
    if market == "set_handicap":
        diff = (a - b) if selection == "p1" else (b - a)
        v = diff + (line or 0)
        return ("WON" if v > 0 else "LOST" if v < 0 else "PUSH"), "HIGH", f"Set diff {diff:+d} with line {line:+}."
    if market in ("total_points", "point_handicap"):
        pts = [(s.p1_points, s.p2_points) for s in m.sets]
        if len(pts) != a + b or any(x is None for p in pts for x in p):
            return None, "LOW", "Point scores unavailable; cannot grade a points market."
        if market == "total_points":
            tot = sum(x + y for x, y in pts)
            v = (tot - line) if selection == "over" else (line - tot)
            return ("WON" if v > 0 else "LOST" if v < 0 else "PUSH"), "HIGH", f"Total points {tot} vs {line}."
        mar = sum(x - y for x, y in pts) * (1 if selection == "p1" else -1)
        v = mar + (line or 0)
        return ("WON" if v > 0 else "LOST" if v < 0 else "PUSH"), "HIGH", f"Point margin {mar:+d} with line {line:+}."
    return None, "LOW", f"Unsupported market {market}."


def _apply_result_money(db: Session, b: Bet, result: str, prior_net=None, prior_stake=None, note="settled"):
    stake = float(b.stake)
    net = profit_for_result(stake, float(b.accepted_decimal), result)
    # reverse previous settlement return if re-settling
    if prior_net is not None:
        ps = prior_stake if prior_stake is not None else stake
        prev_return = ps + prior_net
        if prev_return:
            db.add(BankrollTransaction(kind="ADJUSTMENT", amount=-round(prev_return, 2), bet_id=b.id,
                                       note=f"reverse prior settlement ({note})", is_demo=b.is_demo))
    ret = stake + net
    if ret:
        db.add(BankrollTransaction(kind="RETURN", amount=round(ret, 2), bet_id=b.id, note=note, is_demo=b.is_demo))
    b.status, b.net_profit, b.settled_at = result, net, utcnow()


def closing_for(db: Session, b: Bet) -> float | None:
    q = db.scalar(select(OddsQuote).where(OddsQuote.match_id == b.match_id, OddsQuote.bookmaker_key == "hardrock",
                                          OddsQuote.market == b.market, OddsQuote.selection == b.selection,
                                          OddsQuote.is_closing.is_(True)).order_by(OddsQuote.captured_at.desc()).limit(1))
    return float(q.decimal_odds) if q else None


def settle_open_bets(db: Session, actor: str = "system") -> dict:
    out = {"applied": 0, "review": 0, "waiting": 0}
    bets = db.scalars(select(Bet).where(Bet.status.in_(["PLACED", "PENDING_RESULT"]))).all()
    for b in bets:
        m = db.get(Match, b.match_id)
        if m.status in ("LIVE",) or (m.status == "SCHEDULED" and m.scheduled_at <= utcnow()):
            b.status = "PENDING_RESULT"
        result, conf, reason = grade(m, b.market, b.selection, b.line)
        if result is None and m.status not in ("FINISHED",):
            out["waiting"] += 1
            continue
        net = profit_for_result(float(b.stake), float(b.accepted_decimal), result) if result else None
        prop = SettlementProposal(bet_id=b.id, proposed_status=result or "UNKNOWN", proposed_net_profit=net,
                                  confidence=conf, evidence={"match_status": m.status, "sets": [m.sets_p1, m.sets_p2],
                                                             "sources": m.result_sources, "reason": reason})
        db.add(prop)
        cl = closing_for(db, b)
        if cl:
            b.closing_decimal = cl
            b.clv = clv(float(b.accepted_decimal), cl)
        if result and conf == "HIGH":
            _apply_result_money(db, b, result)
            prop.state, prop.applied_at = "APPLIED", utcnow()
            audit(db, actor, "bet_settled", "bet", b.id, result=result, net=net, reason=reason)
            out["applied"] += 1
        else:
            b.status = "SETTLEMENT_REVIEW"
            prop.state, prop.review_reason = "REVIEW", reason
            out["review"] += 1
    return out


def resolve_review(db: Session, bet_id: int, result: str, actor: str, note: str | None = None) -> Bet:
    b = db.get(Bet, bet_id)
    if not b or b.status != "SETTLEMENT_REVIEW":
        raise ValueError("bet is not awaiting settlement review")
    if result not in ("WON", "LOST", "PUSH", "VOID"):
        raise ValueError("invalid result")
    _apply_result_money(db, b, result, note=f"manual settlement: {note or ''}")
    for p in db.scalars(select(SettlementProposal).where(SettlementProposal.bet_id == bet_id, SettlementProposal.state == "REVIEW")):
        p.state = "APPLIED" if p.proposed_status == result else "REJECTED"
        p.applied_at = utcnow()
    audit(db, actor, "bet_settled_manual", "bet", bet_id, result=result, note=note)
    return b


def settle_recommendations(db: Session) -> int:
    """Ledger B: hypothetical outcome of recommendations (whether or not placed). 1 unit stakes, no money."""
    n = 0
    recs = db.scalars(select(Recommendation).where(Recommendation.hypothetical_result.is_(None),
                                                   Recommendation.is_current.is_(True),
                                                   Recommendation.decimal_odds.isnot(None))).all()
    for r in recs:
        m = db.get(Match, r.match_id)
        res, conf, _ = grade(m, r.market, r.selection, r.line)
        if res and conf == "HIGH":
            r.hypothetical_result = res
            r.hypothetical_profit_per_unit = profit_for_result(1.0, r.decimal_odds, res)
            n += 1
        elif m.status in ("CANCELLED", "RETIRED", "WALKOVER"):
            r.hypothetical_result, r.hypothetical_profit_per_unit = "VOID", 0.0
            n += 1
    return n
