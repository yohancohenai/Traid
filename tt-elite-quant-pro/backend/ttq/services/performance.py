"""Actual-bet performance (ledger A), unplaced recommendations (ledger B) and stake simulations.
The three ledgers are computed from separate tables and never combined."""
from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from datetime import datetime

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ttq.models import BankrollTransaction, Bet, Match, Player, Recommendation, PaperTrade
from ttq.odds.math import kelly_fraction

SETTLED = ("WON", "LOST", "PUSH", "VOID")


def _f(x):
    return float(x) if x is not None else None


def bets_frame(db: Session, is_demo: bool) -> list[dict]:
    rows = db.execute(select(Bet, Match, Player.canonical_name.label("p1n"))
                      .join(Match, Match.id == Bet.match_id).join(Player, Player.id == Match.player1_id)
                      .where(Bet.is_demo == is_demo).order_by(Bet.placed_at)).all()
    out = []
    for b, m, p1n in rows:
        p2n = db.get(Player, m.player2_id).canonical_name
        out.append({"id": b.id, "placed_at": b.placed_at, "settled_at": b.settled_at, "status": b.status,
                    "market": b.market, "selection": b.selection, "line": b.line, "stake": float(b.stake),
                    "decimal": float(b.accepted_decimal), "american": b.accepted_american,
                    "net": _f(b.net_profit), "ev": b.ev_at_placement, "clv": b.clv, "model_version_id": b.model_version_id,
                    "player": p1n if b.selection == "p1" else p2n if b.selection == "p2" else b.selection,
                    "match": f"{p1n} vs {p2n}", "match_id": m.id, "scheduled_at": m.scheduled_at,
                    "bet_ref": b.bet_ref, "notes": b.notes, "potential_payout": float(b.potential_payout),
                    "potential_profit": float(b.potential_profit), "is_demo": b.is_demo})
    return out


def max_drawdown(curve: list[float]) -> float:
    peak, dd = -math.inf, 0.0
    for v in curve:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return dd


def summary(db: Session, is_demo: bool) -> dict:
    bs = bets_frame(db, is_demo)
    settled = [b for b in bs if b["status"] in SETTLED]
    graded = [b for b in settled if b["status"] in ("WON", "LOST")]
    wagered = sum(b["stake"] for b in bs if b["status"] != "VOID")
    settled_wagered = sum(b["stake"] for b in settled if b["status"] != "VOID")
    returned = sum(b["stake"] + (b["net"] or 0) for b in settled)
    net = sum(b["net"] or 0 for b in settled)
    pending = [b for b in bs if b["status"] in ("PLACED", "PENDING_RESULT", "SETTLEMENT_REVIEW")]
    txs = db.execute(select(BankrollTransaction).where(BankrollTransaction.is_demo == is_demo)
                     .order_by(BankrollTransaction.at, BankrollTransaction.id)).scalars().all()
    bal, hist = 0.0, []
    for t in txs:
        bal += float(t.amount)
        hist.append({"at": t.at.isoformat(), "balance": round(bal, 2), "kind": t.kind, "amount": float(t.amount)})
    pl_curve, c = [], 0.0
    for b in sorted(settled, key=lambda x: x["settled_at"] or x["placed_at"]):
        c += b["net"] or 0
        pl_curve.append({"at": (b["settled_at"] or b["placed_at"]).isoformat(), "cum_pl": round(c, 2)})
    clvs = [b["clv"] for b in settled if b["clv"] is not None]
    evs = [b["ev"] for b in bs if b["ev"] is not None]

    def group(keyf):
        g = defaultdict(lambda: {"bets": 0, "staked": 0.0, "net": 0.0, "won": 0, "lost": 0})
        for b in settled:
            k = keyf(b)
            d = g[k]
            d["bets"] += 1
            d["staked"] += b["stake"] if b["status"] != "VOID" else 0
            d["net"] += b["net"] or 0
            d["won"] += b["status"] == "WON"
            d["lost"] += b["status"] == "LOST"
        return [{"key": k, **v, "roi": (v["net"] / v["staked"]) if v["staked"] else None} for k, v in sorted(g.items(), key=lambda x: str(x[0]))]

    def odds_bucket(b):
        d = b["decimal"]
        return "<1.5" if d < 1.5 else "1.5-2.0" if d < 2 else "2.0-3.0" if d < 3 else "3.0+"

    return {
        "ledger": "ACTUAL" if not is_demo else "DEMO_ACTUAL",
        "total_bets": len(bs), "pending": len(pending), "pending_exposure": sum(b["stake"] for b in pending),
        "wins": sum(b["status"] == "WON" for b in bs), "losses": sum(b["status"] == "LOST" for b in bs),
        "pushes": sum(b["status"] == "PUSH" for b in bs), "voids": sum(b["status"] == "VOID" for b in bs),
        "in_review": sum(b["status"] == "SETTLEMENT_REVIEW" for b in bs),
        "win_pct": (sum(b["status"] == "WON" for b in graded) / len(graded)) if graded else None,
        "total_wagered": round(wagered, 2), "total_returned": round(returned, 2), "net_pl": round(net, 2),
        "roi": (net / settled_wagered) if settled_wagered else None,
        "avg_decimal": float(np.mean([b["decimal"] for b in bs])) if bs else None,
        "avg_ev_at_placement": float(np.mean(evs)) if evs else None,
        "avg_clv": float(np.mean(clvs)) if clvs else None, "clv_n": len(clvs),
        "bankroll": round(bal, 2), "bankroll_history": hist, "pl_curve": pl_curve,
        "max_drawdown": round(max_drawdown([0.0] + [p["cum_pl"] for p in pl_curve]), 2),
        "by_day": group(lambda b: (b["settled_at"] or b["placed_at"]).strftime("%Y-%m-%d")),
        "by_week": group(lambda b: (b["settled_at"] or b["placed_at"]).strftime("%G-W%V")),
        "by_month": group(lambda b: (b["settled_at"] or b["placed_at"]).strftime("%Y-%m")),
        "by_player": group(lambda b: b["player"]), "by_market": group(lambda b: b["market"]),
        "by_odds": group(odds_bucket), "by_model_version": group(lambda b: b["model_version_id"] or "none"),
    }


def recommendations_ledger(db: Session, is_demo: bool) -> dict:
    """Ledger B: QUALIFIES recommendations the user did NOT place, 1-unit hypothetical."""
    rs = db.scalars(select(Recommendation).where(Recommendation.is_demo == is_demo, Recommendation.status == "QUALIFIES",
                                                 Recommendation.user_action != "PLACED")).all()
    done = [r for r in rs if r.hypothetical_result]
    units = sum(r.hypothetical_profit_per_unit or 0 for r in done)
    staked = sum(1 for r in done if r.hypothetical_result != "VOID")
    return {"ledger": "RECOMMENDATIONS_NOT_PLACED", "count": len(rs), "graded": len(done), "units": round(units, 3),
            "roi": units / staked if staked else None,
            "wins": sum(r.hypothetical_result == "WON" for r in done), "losses": sum(r.hypothetical_result == "LOST" for r in done)}


def export_csv(db: Session, is_demo: bool) -> str:
    rows = bets_frame(db, is_demo)
    buf = io.StringIO()
    cols = ["id", "placed_at", "match", "market", "selection", "line", "american", "decimal", "stake", "status", "net",
            "potential_payout", "ev", "clv", "bet_ref", "notes", "settled_at", "is_demo"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()})
    return buf.getvalue()


def stake_simulation(bankroll: float, prob: float, decimal_odds: float, prob_low: float | None, prob_high: float | None,
                     kelly_mult: float = 0.25, fixed_stake: float = 10.0, fixed_pct: float = 0.01, max_stake: float | None = None) -> dict:
    """Educational stake sizes. Never mandatory; Kelly shown across the uncertainty interval."""
    def cap(x):
        return round(min(x, max_stake) if max_stake else x, 2)
    kf = kelly_fraction(prob, decimal_odds)
    sens = []
    for lbl, p in (("low", prob_low), ("point", prob), ("high", prob_high)):
        if p is not None:
            sens.append({"case": lbl, "prob": p, "full_kelly_frac": kelly_fraction(p, decimal_odds),
                         "fractional_stake": cap(bankroll * kelly_mult * kelly_fraction(p, decimal_odds))})
    return {"fixed_stake": cap(fixed_stake), "fixed_pct_stake": cap(bankroll * fixed_pct),
            "fractional_kelly_stake": cap(bankroll * kelly_mult * kf), "full_kelly_fraction": kf, "kelly_multiplier": kelly_mult,
            "kelly_sensitivity": sens,
            "note": "Educational only. Kelly assumes the probability is exactly right; overestimated edges make Kelly "
                    "stakes too large. If the low-case Kelly is 0 the edge is not robust to model uncertainty."}
