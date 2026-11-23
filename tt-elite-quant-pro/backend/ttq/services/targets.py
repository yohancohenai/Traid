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
        lines.append(f"{as_utc(m.scheduled_at).astimezone(tz):%H:%M}  {m.player1.canonical_name} vs {m.player2.canonical_name}")
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


def build_picks(db: Session, now: datetime | None = None) -> list[dict]:
    """Strongest conditional picks for live matches starting soon. One side per match, each match once, capped per
    local day. Returns [{"match", "pred", "side", "p", "min_american"}]."""
    cfg = get_setting(db, "alerts")
    if not cfg.get("conditional_picks", True):
        return []
    now = now or utcnow()
    F = get_filters(db, False)
    lo_min, hi_min = int(cfg.get("picks_min_minutes", 10)), int(cfg.get("picks_max_minutes", 45))
    max_width = float(cfg.get("picks_max_interval", 0.135))
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
    cands = []
    for m in ms:
        if str(m.id) in sent:
            continue
        pred = latest_prediction(db, m.id)
        if not pred or pred.data_quality != "HIGH":
            continue
        width = pred.p1_ci_high - pred.p1_ci_low
        f = pred.features or {}
        comps = list((pred.component_probs or {}).values()) or [pred.p1_win]
        if width > max_width or min(f.get("_n1") or 0, f.get("_n2") or 0) < F["min_player_matches"] \
                or max(comps) - min(comps) > F["max_model_disagreement"]:
            continue
        best = None
        for side, p, lo in (("p1", pred.p1_win, pred.p1_ci_low), ("p2", 1 - pred.p1_win, 1 - pred.p1_ci_high)):
            t = side_target(p, lo, F)
            if t is None:
                continue
            premium = t * p            # how far above the model's own fair price the minimum sits
            if best is None or premium < best[0]:
                best = (premium, side, p, round_up_american(t))
        if best:
            cands.append((width, m, pred, best))
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


def picks_job(db: Session) -> dict:
    from ttq.services.alerts import raise_alert
    from ttq.services.messages import conditional_pick_text
    out = []
    for pk in build_picks(db):
        m = pk["match"]
        title, body = conditional_pick_text(db, m, pk["pred"], pk["side"], pk["p"], pk["min_american"])
        a = raise_alert(db, "pick", title, body, f"pick:{m.id}", "INFO", False, rate_limited=False)
        out.append({"match_id": m.id, "side": pk["side"], "min": pk["min_american"], "channels": a.channels_sent if a else []})
    return {"sent": len(out), "picks": out}
