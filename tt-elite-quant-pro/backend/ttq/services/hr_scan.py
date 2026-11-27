"""Scan a Hard Rock screenshot for misplaced lines.

The free OddsPapi feed rarely carries Hard Rock's TT Elite prices, so the user sends a screenshot of the Hard Rock
table-tennis list to the bot in Telegram (no reply needed). The bot reads every match and price on it (Tesseract OCR),
matches them to the official schedule, and compares each Hard Rock price with:
  - the fair price: the average of the model and the DraftKings no-vig price when a recent DraftKings board has the
    match, otherwise the model alone (stricter edge required);
  - the band -200..+200.
Every value line is sent back as a normal "New Bet Recommendation" (logged and graded like any pick), followed by a
short summary of everything read.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from ttq.core.timeutil import utcnow
from ttq.models import Match
from ttq.odds.math import american_to_decimal, decimal_to_american

log = logging.getLogger(__name__)

EDGE_WITH_MARKET = 0.02     # Hard Rock vs the model/market blend
EDGE_MODEL_ONLY = 0.05      # no market price available: the model alone must see a bigger edge
PRICE_MIN, PRICE_MAX = 1.50, 3.00
MARKET_MAX_AGE_MIN = 180


def evaluate(pred, hr: tuple[float, float], cons_p1: float | None) -> dict:
    """Best side of one match at Hard Rock's prices. Returns {'value': bool, ...}."""
    rows = []
    for sd, mp, lo in (("p1", pred.p1_win, pred.p1_ci_low), ("p2", 1 - pred.p1_win, 1 - pred.p1_ci_high)):
        dec = hr[0] if sd == "p1" else hr[1]
        cons = None if cons_p1 is None else (cons_p1 if sd == "p1" else 1 - cons_p1)
        fair = (mp + cons) / 2 if cons is not None else mp
        need = EDGE_WITH_MARKET if cons is not None else EDGE_MODEL_ONLY
        ev = fair * dec - 1
        ok = PRICE_MIN <= dec <= PRICE_MAX and ev >= need and (cons is not None or lo * dec >= 1.0)
        if cons is not None and cons * dec - 1 < 0:      # the sharper book says it's -EV: never send
            ok = False
        rows.append({"side": sd, "p": round(fair, 4), "model_p": round(mp, 4), "consensus_p": cons,
                     "hr_decimal": round(dec, 3), "hr_american": decimal_to_american(dec), "ev": round(ev, 4),
                     "fair_american": decimal_to_american(1 / max(fair, 0.01)), "value": ok})
    best = max(rows, key=lambda r: (r["value"], r["ev"]))
    return best


def scan_image(db: Session, image: bytes, now=None) -> dict:
    from ttq.ocr.hardrock import ocr_rows, pair_matches, parse_rows, propose
    from ttq.providers.oddspapi import from_sweep
    from ttq.services.modeling import latest_prediction
    now = now or utcnow()
    rows, _ = ocr_rows(image)
    props = propose(db, pair_matches(parse_rows(rows)), False, now=now, horizon_hours=12)
    out = {"read": len(props), "matched": 0, "value": [], "no_value": [], "unmatched": []}
    for pr in props:
        if not pr["match_id"] or pr["p1_american"] is None or pr["p2_american"] is None:
            out["unmatched"].append(f"{pr['read']['p1']} / {pr['read']['p2']}")
            continue
        m = db.get(Match, pr["match_id"])
        pred = latest_prediction(db, m.id)
        if pred is None or pred.data_quality == "LOW":
            out["unmatched"].append(f"{m.player1.canonical_name} vs {m.player2.canonical_name} (no reliable model)")
            continue
        out["matched"] += 1
        hr = (american_to_decimal(pr["p1_american"]), american_to_decimal(pr["p2_american"]))
        try:
            mk = from_sweep(db, m.player1.canonical_name, m.player2.canonical_name, m.scheduled_at, now=now,
                            max_age_min=MARKET_MAX_AGE_MIN)
        except Exception:  # noqa
            mk = None
        cons = mk.get("consensus_p1") if mk and mk.get("status") == "ok" else None
        r = evaluate(pred, hr, cons)
        r.update({"match": m, "pred": pred, "books": (mk or {}).get("books") if cons is not None else 0})
        (out["value"] if r["value"] else out["no_value"]).append(r)
    return out


def _short(n: str) -> str:
    return n.split()[-1] if n else n


def summary_text(res: dict) -> str:
    lines = [f"Hard Rock scan: read {res['read']} matches, matched {res['matched']}."]
    if res["value"]:
        lines.append(f"✅ {len(res['value'])} misplaced line(s), sent above as picks.")
    else:
        lines.append("No misplaced lines on this screen right now.")
    for r in res["no_value"][:12]:
        m = r["match"]
        name = m.player1.canonical_name if r["side"] == "p1" else m.player2.canonical_name
        src = "model+DK" if r["consensus_p"] is not None else "model"
        lines.append(f"• {_short(name)} {r['hr_american']:+d} vs fair {r['fair_american']:+d} ({src}): {r['ev']:+.1%}")
    if res["unmatched"]:
        lines.append(f"Couldn't use {len(res['unmatched'])}: " + "; ".join(res["unmatched"][:5]))
    lines.append("Tip: scroll so full names and both prices are visible; send another screenshot anytime.")
    return "\n".join(lines)


def send_value_picks(db: Session, res: dict) -> int:
    """Send each value line as a normal pick (logged, graded, never repeated)."""
    from ttq.models import AppSetting
    from ttq.services.alerts import raise_alert
    from ttq.services.messages import conditional_pick_text
    from ttq.services.summary import log_picks
    from ttq.services.targets import round_up_american
    sent_row = db.get(AppSetting, "picks_sent")
    sent = dict(sent_row.value) if sent_row else {}
    logged, n = [], 0
    for r in res["value"]:
        m = r["match"]
        if str(m.id) in sent:
            continue
        need = EDGE_WITH_MARKET if r["consensus_p"] is not None else EDGE_MODEL_ONLY
        min_am = round_up_american((1 + need) / r["p"])
        info = {"hr_american": r["hr_american"], "hr_decimal": r["hr_decimal"], "consensus_p": r["consensus_p"],
                "books": r["books"], "market_ev_at_hr": (round(r["consensus_p"] * r["hr_decimal"] - 1, 4)
                                                          if r["consensus_p"] is not None else None), "units": 1.0}
        title, body = conditional_pick_text(db, m, r["pred"], r["side"], r["p"], min_am, info)
        body += "\nSource: your Hard Rock screenshot"
        a = raise_alert(db, "pick", title, body, f"pick:{m.id}", "INFO", False, rate_limited=False)
        sent[str(m.id)] = utcnow().isoformat()
        name = m.player1.canonical_name if r["side"] == "p1" else m.player2.canonical_name
        logged.append({"match_id": m.id, "side": r["side"], "p": r["p"], "min_american": min_am,
                       "tg_msg": getattr(a, "telegram_message_id", None) if a else None, "pick_name": name,
                       "hr_auto": r["hr_american"], "hr_auto_dec": r["hr_decimal"], "consensus_p": r["consensus_p"],
                       "books": r["books"], "units": 1.0, "source": "screenshot"})
        n += 1
    if logged:
        log_picks(db, logged)
        if sent_row:
            sent_row.value = sent
        else:
            db.add(AppSetting(key="picks_sent", value=sent))
        db.flush()
    return n
