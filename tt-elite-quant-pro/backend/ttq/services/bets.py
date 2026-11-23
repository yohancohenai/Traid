"""Ledger A: actual, manually confirmed bets. A recommendation is NEVER a bet until the user confirms it."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ttq.core.timeutil import as_utc, utcnow
from ttq.models import BankrollTransaction, Bet, BetRevision, Match, Recommendation
from ttq.odds.math import american_to_decimal, decimal_to_american, expected_value
from ttq.services.app_settings import get_setting
from ttq.services.audit import audit
from ttq.services.modeling import latest_prediction
from ttq.services.scanner import is_executable

OPEN_STATUSES = ("PLACED", "PENDING_RESULT", "SETTLEMENT_REVIEW")


class BetError(ValueError):
    def __init__(self, msg, code=422, detail=None):
        super().__init__(msg)
        self.code, self.detail = code, detail or {}


def _bet_dict(b: Bet) -> dict:
    return {k: (float(v) if isinstance(v, Decimal) else (v.isoformat() if isinstance(v, datetime) else v))
            for k, v in b.__dict__.items() if not k.startswith("_")}


def model_prob_for(db, match: Match, selection: str, market: str) -> float | None:
    if market != "match_winner":
        return None
    pred = latest_prediction(db, match.id)
    if not pred:
        return None
    return pred.p1_win if selection == "p1" else 1 - pred.p1_win


def risk_check(db: Session, match_id: int, stake: float, is_demo: bool, exclude_bet: int | None = None) -> list[str]:
    R = get_setting(db, "risk")
    warn = []
    if R["max_stake"] and stake > R["max_stake"]:
        warn.append(f"Stake ${stake:.2f} exceeds your max stake ${R['max_stake']:.2f}.")
    q = select(func.coalesce(func.sum(Bet.stake), 0)).where(Bet.match_id == match_id, Bet.status.in_(OPEN_STATUSES),
                                                            Bet.is_demo == is_demo)
    if exclude_bet:
        q = q.where(Bet.id != exclude_bet)
    ev_exp = float(db.scalar(q)) + stake
    if R["max_event_exposure"] and ev_exp > R["max_event_exposure"]:
        warn.append(f"Event exposure ${ev_exp:.2f} exceeds limit ${R['max_event_exposure']:.2f}.")
    day0 = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    day_exp = float(db.scalar(select(func.coalesce(func.sum(Bet.stake), 0)).where(
        Bet.placed_at >= day0, Bet.is_demo == is_demo, Bet.status.notin_(["VOID"])))) + stake
    if R["max_daily_exposure"] and day_exp > R["max_daily_exposure"]:
        warn.append(f"Today's total staked ${day_exp:.2f} exceeds daily exposure limit ${R['max_daily_exposure']:.2f}.")
    day_pl = float(db.scalar(select(func.coalesce(func.sum(Bet.net_profit), 0)).where(
        Bet.settled_at >= day0, Bet.is_demo == is_demo)))
    if R["daily_loss_limit"] and -day_pl >= R["daily_loss_limit"]:
        warn.append(f"Daily loss ceiling reached (today ${day_pl:.2f}). Consider stopping for today.")
    return warn


def confirm_bet(db: Session, *, actor: str, match_id: int, market: str, selection: str, stake: float,
                accepted_american: int | None = None, accepted_decimal: float | None = None, line: float | None = None,
                placed_at: datetime | None = None, bet_ref: str | None = None, notes: str | None = None,
                recommendation_id: int | None = None, client_request_id: str | None = None,
                bookmaker_key: str = "hardrock", override_risk: bool = False, allow_duplicate: bool = False) -> dict:
    m = db.get(Match, match_id)
    if not m:
        raise BetError("match not found", 404)
    if not is_executable(bookmaker_key):
        raise BetError(f"{bookmaker_key} is not an executable sportsbook in your region; bets can only be recorded for Hard Rock Bet.")
    if stake is None or stake <= 0:
        raise BetError("stake must be positive")
    if accepted_american is None and accepted_decimal is None:
        raise BetError("accepted odds required")
    if accepted_american is not None:
        dec = american_to_decimal(accepted_american)
        if accepted_decimal is not None and abs(dec - accepted_decimal) > 0.02:
            raise BetError("american and decimal odds disagree")
    else:
        if accepted_decimal <= 1.0:
            raise BetError("decimal odds must be > 1")
        dec, accepted_american = accepted_decimal, decimal_to_american(accepted_decimal)
    if market in ("set_handicap", "point_handicap", "total_points") and line is None:
        raise BetError(f"a line is required for {market}")
    if selection not in ("p1", "p2") and market == "match_winner":
        raise BetError("selection must be p1 or p2 for match winner")
    placed_at = as_utc(placed_at) or utcnow()
    if placed_at > utcnow() + timedelta(minutes=5):
        raise BetError("placed_at cannot be in the future")
    rec = db.get(Recommendation, recommendation_id) if recommendation_id else None
    if recommendation_id and not rec:
        raise BetError("recommendation not found", 404)
    if rec and (rec.match_id != match_id or rec.market != market or rec.selection != selection or rec.line != line):
        raise BetError("bet does not match the linked recommendation (match, market, selection or line differ)")
    # Duplicate protection
    if bet_ref:
        key = f"ref:{bookmaker_key}:{bet_ref.strip()}"
    elif client_request_id:
        key = f"req:{client_request_id}"
    else:
        key = "h:" + hashlib.sha256(f"{match_id}|{market}|{selection}|{line}|{accepted_american}|{stake}|{placed_at:%Y%m%d%H%M}".encode()).hexdigest()[:40]
    existing = db.scalar(select(Bet).where(Bet.dedupe_key == key))
    if existing:
        raise BetError("duplicate bet entry (same bet slip reference or request)", 409, {"existing_bet_id": existing.id})
    if not allow_duplicate:
        recent = db.scalar(select(Bet).where(Bet.match_id == match_id, Bet.selection == selection, Bet.market == market,
                                             Bet.created_at >= utcnow() - timedelta(minutes=10)))
        if recent:
            raise BetError("A bet on this selection was recorded in the last 10 minutes. Confirm it is a separate bet.",
                           409, {"existing_bet_id": recent.id, "needs_allow_duplicate": True})
    warnings = risk_check(db, match_id, stake, m.is_demo)
    if warnings and not override_risk:
        raise BetError("risk limits exceeded", 422, {"warnings": warnings, "needs_override": True})
    p = model_prob_for(db, m, selection, market)
    pred = latest_prediction(db, m.id)
    stake_d = round(float(stake), 2)
    status = "PLACED" if m.status == "SCHEDULED" else "PENDING_RESULT"
    b = Bet(recommendation_id=rec.id if rec else None, match_id=m.id, bookmaker_key=bookmaker_key, market=market,
            selection=selection, line=line, accepted_american=int(accepted_american), accepted_decimal=round(dec, 4),
            stake=stake_d, placed_at=placed_at, bet_ref=bet_ref, notes=notes, status=status,
            potential_payout=round(stake_d * dec, 2), potential_profit=round(stake_d * (dec - 1), 2),
            model_prob_at_placement=p, ev_at_placement=expected_value(p, dec) if p is not None else None,
            model_version_id=pred.model_version_id if pred else None, dedupe_key=key, is_demo=m.is_demo)
    db.add(b)
    db.flush()
    db.add(BankrollTransaction(kind="STAKE", amount=-stake_d, bet_id=b.id, note="stake placed", is_demo=m.is_demo, at=placed_at))
    if rec:
        rec.user_action = "PLACED"
    audit(db, actor, "bet_confirmed", "bet", b.id, match_id=m.id, stake=stake_d, odds=accepted_american,
          risk_override=bool(warnings), warnings=warnings)
    return {"bet": _bet_dict(b), "warnings": warnings}


def skip_recommendation(db: Session, rec_id: int, actor: str, reason: str | None = None):
    rec = db.get(Recommendation, rec_id)
    if not rec:
        raise BetError("recommendation not found", 404)
    if rec.user_action == "PLACED":
        raise BetError("already placed")
    rec.user_action = "SKIPPED"
    audit(db, actor, "recommendation_skipped", "recommendation", rec_id, reason=reason)
    return rec


EDITABLE = {"accepted_american", "stake", "placed_at", "bet_ref", "notes", "selection", "market", "line", "status"}


def correct_bet(db: Session, bet_id: int, changes: dict, reason: str, actor: str) -> dict:
    b = db.get(Bet, bet_id, with_for_update=True, populate_existing=True)
    if not b:
        raise BetError("bet not found", 404)
    if not reason or len(reason.strip()) < 3:
        raise BetError("a correction reason is required")
    bad = set(changes) - EDITABLE
    if bad:
        raise BetError(f"fields not editable: {sorted(bad)}")
    before = _bet_dict(b)
    old_stake = float(b.stake)
    old_net = float(b.net_profit) if b.net_profit is not None else None
    for k, v in changes.items():
        if k == "accepted_american":
            b.accepted_american = int(v)
            b.accepted_decimal = round(american_to_decimal(int(v)), 4)
        elif k == "stake":
            if float(v) <= 0:
                raise BetError("stake must be positive")
            b.stake = round(float(v), 2)
        elif k == "placed_at":
            b.placed_at = as_utc(datetime.fromisoformat(v) if isinstance(v, str) else v)
        elif k == "bet_ref":
            ref = (v or "").strip() or None
            if ref:
                key = f"ref:{b.bookmaker_key}:{ref}"
                other = db.scalar(select(Bet).where(Bet.dedupe_key == key, Bet.id != b.id))
                if other:
                    raise BetError("another bet already uses this bet slip reference", 409, {"existing_bet_id": other.id})
                b.dedupe_key = key
            b.bet_ref = ref
        elif k == "status":
            if v not in ("PLACED", "PENDING_RESULT", "WON", "LOST", "PUSH", "VOID", "SETTLEMENT_REVIEW"):
                raise BetError("invalid status")
            b.status = v
        else:
            setattr(b, k, v)
    dec, stake = float(b.accepted_decimal), float(b.stake)
    b.potential_payout = round(stake * dec, 2)
    b.potential_profit = round(stake * (dec - 1), 2)
    if b.model_prob_at_placement is not None:
        b.ev_at_placement = expected_value(b.model_prob_at_placement, dec)
    if stake != old_stake:
        db.add(BankrollTransaction(kind="ADJUSTMENT", amount=-(stake - old_stake), bet_id=b.id,
                                   note=f"stake correction: {reason}", is_demo=b.is_demo))
    if b.status in ("WON", "LOST", "PUSH", "VOID"):
        from ttq.services.settlement import _apply_result_money
        _apply_result_money(db, b, b.status, prior_net=old_net, prior_stake=old_stake, note=f"correction: {reason}")
    elif old_net is not None:
        # moved back to an open status: reverse previous return
        returned = old_stake + old_net if before["status"] != "LOST" else 0
        if returned:
            db.add(BankrollTransaction(kind="ADJUSTMENT", amount=-returned, bet_id=b.id, note=f"unsettle: {reason}", is_demo=b.is_demo))
        b.net_profit, b.settled_at = None, None
    b.updated_at = utcnow()
    after = _bet_dict(b)
    db.add(BetRevision(bet_id=b.id, actor=actor, reason=reason, before=before, after=after))
    audit(db, actor, "bet_corrected", "bet", b.id, reason=reason, fields=list(changes))
    return after
