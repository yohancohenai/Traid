"""Price-target digests: for upcoming confident matches, the minimum Hard Rock price at which each side would pass the
model-side research filters. Lets the user check Hard Rock only when a price is worth it. Never places bets.

The market-edge filter (model vs Hard Rock no-vig) needs Hard Rock's own two-way price, so it is applied later, when
the user uploads a screenshot and the normal scanner runs.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ttq.core.config import get_settings
from ttq.core.timeutil import as_utc, utcnow
from ttq.models import AppSetting, Match
from ttq.odds.math import american_to_decimal
from ttq.services.app_settings import QUALITY_ORDER, get_filters, get_setting
from ttq.services.modeling import latest_prediction


def round_up_american(decimal_odds: float, step: int = 5) -> int:
    """Conservative: the smallest American price on a `step` grid that pays at least `decimal_odds`.
    Computed from the exact value (no intermediate rounding), so the target is never below what's needed."""
    if decimal_odds >= 2.0:
        return int(math.ceil((decimal_odds - 1) * 100 / step - 1e-9) * step)
    exact = -100 / (decimal_odds - 1)            # e.g. 1.6613 -> -151.2; "better" = closer to -100
    am = int(math.ceil(exact / step - 1e-9) * step)
    return am if am < -100 else 100   # -100 and +100 are the same price (even money); show +100


def side_target(p: float, lo: float, F: dict) -> float | None:
    """Smallest decimal price that passes the model-side filters, or None if no plausible price qualifies."""
    if not (0 < p < 1) or not (0 < lo < 1):
        return None
    need = max((1 + F["min_ev"]) / p, (1 + F["min_ev_low"]) / lo, F["min_decimal_odds"])
    if need > F["max_decimal_odds"] or need > (1 + F.get("max_ev", 0.25)) / p:
        return None
    return need


def _short(name: str) -> str:
    return name.split()[-1] if name else name


def build_digest(db: Session, now: datetime | None = None) -> dict | None:
    """Return {"text", "match_ids"} for live matches starting soon, or None if nothing to send."""
    cfg = get_setting(db, "alerts")
    if not cfg.get("price_targets", True):
        return None
    now = now or utcnow()
    F = get_filters(db, False)
    window = cfg.get("price_targets_window_minutes", 75)
    sent_row = db.get(AppSetting, "targets_sent")
    sent = {k: v for k, v in (sent_row.value if sent_row else {}).items()
            if datetime.fromisoformat(v) > now - timedelta(days=1)}
    ms = db.scalars(select(Match).where(Match.is_demo.is_(False), Match.status == "SCHEDULED",
                                        Match.scheduled_at >= now + timedelta(minutes=10),
                                        Match.scheduled_at <= now + timedelta(minutes=window))
                    .order_by(Match.scheduled_at)).all()
    cands = []
    for m in ms:
        if str(m.id) in sent:
            continue
        pred = latest_prediction(db, m.id)
        if not pred:
            continue
        f = pred.features or {}
        n_min = int(min(f.get("_n1") or 0, f.get("_n2") or 0))
        comps = list((pred.component_probs or {}).values()) or [pred.p1_win]
        spread = max(comps) - min(comps)
        if QUALITY_ORDER[pred.data_quality] < QUALITY_ORDER[F["min_data_quality"]] or n_min < F["min_player_matches"] \
                or spread > F["max_model_disagreement"]:
            continue
        sides = []
        for name, p, lo in ((m.player1.canonical_name, pred.p1_win, pred.p1_ci_low),
                            (m.player2.canonical_name, 1 - pred.p1_win, 1 - pred.p1_ci_high)):
            t = side_target(p, lo, F)
            if t:
                sides.append((name, p, round_up_american(t)))
        if sides:
            cands.append((pred.p1_ci_high - pred.p1_ci_low, m, sides))
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1].scheduled_at))
    chosen = sorted(cands[: cfg.get("price_targets_max", 8)], key=lambda c: c[1].scheduled_at)
    tz = ZoneInfo(get_setting(db, "display").get("timezone") or get_settings().user_timezone)
    lines = ["TT Elite price targets (model estimates, not guarantees)"]
    for _, m, sides in chosen:
        lines.append(f"{as_utc(m.scheduled_at).astimezone(tz).strftime('%I:%M %p').lstrip('0')}  {m.player1.canonical_name} vs {m.player2.canonical_name}")
        for name, p, am in sides:
            lines.append(f"  {_short(name)} {p:.0%} -> only at {am:+d} or better")
    lines.append("Check Hard Rock; upload a screenshot to confirm before deciding. Never more than your limits.")
    for _, m, _s in chosen:
        sent[str(m.id)] = now.isoformat()
    if sent_row:
        sent_row.value = sent
    else:
        db.add(AppSetting(key="targets_sent", value=sent))
    db.flush()
    return {"text": "\n".join(lines), "match_ids": [m.id for _, m, _s in chosen]}


def price_targets_job(db: Session) -> dict:
    from ttq.services.alerts import raise_alert
    d = build_digest(db)
    if not d:
        return {"sent": 0}
    a = raise_alert(db, "price_targets", f"Price targets: {len(d['match_ids'])} upcoming match(es)", d["text"],
                    f"targets:{utcnow():%Y%m%d%H%M}:{','.join(map(str, d['match_ids']))}", "INFO", False)
    return {"sent": len(d["match_ids"]), "channels": a.channels_sent if a else []}


def build_picks(db: Session, now: datetime | None = None, stats: dict | None = None) -> list[dict]:
    """Strongest conditional picks for live matches starting soon. One side per match, each match once, capped per
    local day. Returns [{"match", "pred", "side", "p", "min_american"}]."""
    cfg = get_setting(db, "alerts")
    if not cfg.get("conditional_picks", True):
        return []
    now = now or utcnow()
    F = get_filters(db, False)
    lo_min, hi_min = int(cfg.get("picks_min_minutes", 10)), int(cfg.get("picks_max_minutes", 45))
    max_width = float(cfg.get("picks_max_interval", 0.20))
    # Back-test (Nov 2026, 1,338 out-of-sample matches): the model is well calibrated for favourites at 60%+ but
    # over-confident on near coin-flips, and the HIGH-quality / narrow-range / models-agree filters did not raise the
    # hit rate. So picks are favourites at >= picks_min_prob; only LOW-quality data is excluded.
    min_prob = float(cfg.get("picks_min_prob", 0.60))
    tz = ZoneInfo(get_setting(db, "display").get("timezone") or get_settings().user_timezone)
    sent_row = db.get(AppSetting, "picks_sent")
    sent = {k: v for k, v in (sent_row.value if sent_row else {}).items()
            if datetime.fromisoformat(v) > now - timedelta(days=2)}
    today = now.astimezone(tz).date()
    sent_today = sum(1 for v in sent.values() if datetime.fromisoformat(v).astimezone(tz).date() == today)
    cap = int(cfg.get("picks_max_per_day", 0) or 0)          # 0 = unlimited: send every pick that passes
    room = (cap - sent_today) if cap > 0 else None
    if room is not None and room <= 0:
        return []
    ms = db.scalars(select(Match).where(Match.is_demo.is_(False), Match.status == "SCHEDULED",
                                        Match.scheduled_at >= now + timedelta(minutes=lo_min),
                                        Match.scheduled_at <= now + timedelta(minutes=hi_min))
                    .order_by(Match.scheduled_at)).all()
    st = stats if stats is not None else {}
    def skip(reason):
        st[reason] = st.get(reason, 0) + 1
    st["in_window"] = len(ms)
    cands = []
    for m in ms:
        if str(m.id) in sent:
            skip("already_sent")
            continue
        pred = latest_prediction(db, m.id)
        if not pred:
            skip("no_prediction")
            continue
        if pred.data_quality == "LOW":
            skip("low_quality")
            continue
        if max(pred.p1_win, 1 - pred.p1_win) < min_prob:
            skip("below_min_prob")
            continue
        width = pred.p1_ci_high - pred.p1_ci_low
        f = pred.features or {}
        if width > max_width:
            skip("too_uncertain")
            st.setdefault("widths", []).append(round(width, 3))
            continue
        if min(f.get("_n1") or 0, f.get("_n2") or 0) < F["min_player_matches"]:
            skip("too_few_player_matches")
            continue
        best = None
        fav = ("p1", pred.p1_win, pred.p1_ci_low) if pred.p1_win >= 0.5 else ("p2", 1 - pred.p1_win, 1 - pred.p1_ci_high)
        for side, p, lo in (fav,):
            t = side_target(p, lo, F)
            if t is None:
                continue
            premium = t * p            # how far above the model's own fair price the minimum sits
            if best is None or premium < best[0]:
                best = (premium, side, p, round_up_american(t))
        if best:
            cands.append((width, m, pred, best))
        else:
            skip("no_sensible_price")
    cands.sort(key=lambda c: (c[0], c[1].scheduled_at))
    picks = []
    for width, m, pred, (_, side, p, am) in (cands if room is None else cands[:room]):
        picks.append({"match": m, "pred": pred, "side": side, "p": p, "min_american": am})
        sent[str(m.id)] = now.isoformat()
    if picks:
        if sent_row:
            sent_row.value = sent
        else:
            db.add(AppSetting(key="picks_sent", value=sent))
        db.flush()
    return picks


MARKET_DISAGREE = -0.03   # skip if, at Hard Rock's price, the consensus of other books says EV is below -3%


def decide_with_market(side: str, p: float, min_american: int, mk: dict | None) -> tuple[bool, dict]:
    """Use the live market (if we have it) to confirm or reject a model pick. Returns (send, info)."""
    info: dict = {"market": (mk or {}).get("status", "not checked")}
    if not mk or mk.get("status") != "ok":
        return True, info
    info["books"] = mk.get("books")
    cons_p1 = mk.get("consensus_p1")
    cons = None if cons_p1 is None else (cons_p1 if side == "p1" else 1 - cons_p1)
    info["consensus_p"] = round(cons, 4) if cons is not None else None
    hr = mk.get("hard_rock")
    if not hr:
        info["reason"] = "Hard Rock not pricing it"
        return True, info
    hr_dec = hr[0] if side == "p1" else hr[1]
    from ttq.odds.math import decimal_to_american
    info["hr_american"] = decimal_to_american(hr_dec)
    info["hr_decimal"] = round(hr_dec, 3)
    info["model_ev_at_hr"] = round(p * hr_dec - 1, 4)
    info["market_ev_at_hr"] = round(cons * hr_dec - 1, 4) if cons is not None else None
    if hr_dec < american_to_decimal(min_american) - 1e-9:
        info["reason"] = f"Hard Rock {info['hr_american']:+d} is below the minimum {min_american:+d}"
        return False, info
    if info["market_ev_at_hr"] is not None and info["market_ev_at_hr"] < MARKET_DISAGREE:
        info["reason"] = f"other books disagree (market EV {info['market_ev_at_hr']:+.1%} at Hard Rock's price)"
        return False, info
    info["reason"] = "Hard Rock price passes"
    return True, info


def _log_market_check(db: Session, row: dict) -> None:
    r = db.get(AppSetting, "market_checks")
    items = (list(r.value.get("items", [])) if r else [])[-299:] + [row]
    if r:
        r.value = {"items": items}
    else:
        db.add(AppSetting(key="market_checks", value={"items": items}))
    db.flush()


def picks_job(db: Session) -> dict:
    from ttq.providers.oddspapi import market_check
    from ttq.services.alerts import raise_alert
    from ttq.services.messages import conditional_pick_text
    from ttq.services.summary import log_picks
    out, logged, stats, skipped = [], [], {}, []
    for pk in build_picks(db, stats=stats):
        m = pk["match"]
        try:
            mk = market_check(db, m.player1.canonical_name, m.player2.canonical_name, m.scheduled_at)
        except Exception:  # noqa
            mk = {"status": "error"}
        send, info = decide_with_market(pk["side"], pk["p"], pk["min_american"], mk)
        name = m.player1.canonical_name if pk["side"] == "p1" else m.player2.canonical_name
        _log_market_check(db, {"at": utcnow().isoformat(), "match_id": m.id, "match": f"{m.player1.canonical_name} vs "
                               f"{m.player2.canonical_name}", "pick": name, "p": round(pk["p"], 4),
                               "min_american": pk["min_american"], "sent": send, **info})
        if not send:
            skipped.append({"match_id": m.id, "reason": info.get("reason")})
            continue
        title, body = conditional_pick_text(db, m, pk["pred"], pk["side"], pk["p"], pk["min_american"], info)
        a = raise_alert(db, "pick", title, body, f"pick:{m.id}", "INFO", False, rate_limited=False)
        out.append({"match_id": m.id, "side": pk["side"], "min": pk["min_american"], "market": info.get("market"),
                    "channels": a.channels_sent if a else []})
        logged.append({"match_id": m.id, "side": pk["side"], "p": round(pk["p"], 4), "min_american": pk["min_american"],
                       "tg_msg": getattr(a, "telegram_message_id", None) if a else None, "pick_name": name,
                       "hr_auto": info.get("hr_american"), "consensus_p": info.get("consensus_p"),
                       "books": info.get("books")})
    if logged:
        log_picks(db, logged)
    return {"sent": len(out), "picks": out, "skipped_by_market": skipped, "checked": stats}
