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


def build_picks(db: Session, now: datetime | None = None, stats: dict | None = None,
                max_minutes: int | None = None) -> list[dict]:
    """Strongest conditional picks for live matches starting soon. One side per match, each match once, capped per
    local day. Returns [{"match", "pred", "side", "p", "min_american"}]."""
    cfg = get_setting(db, "alerts")
    if not cfg.get("conditional_picks", True):
        return []
    now = now or utcnow()
    F = get_filters(db, False)
    lo_min, hi_min = int(cfg.get("picks_min_minutes", 10)), int(max_minutes or cfg.get("picks_max_minutes", 45))
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


MARKET_DISAGREE = 0.0     # model and market must agree: at Hard Rock's price the consensus of the other books must not say -EV
HR_OUTLIER = 0.12         # skip if Hard Rock's no-vig chance is 12+ points away from every other book (stale/void line)
PRICE_MIN, PRICE_MAX = 1.50, 3.00   # only -200 to +200: no -500 favourites (one loss wipes out five wins)
MAX_FAV_TO_CHECK = 0.80   # don't spend a credit on huge favourites: their price can't land in the band


def _sides(pred, p_fav: float, fav_side: str) -> list[tuple[str, float, float]]:
    """Both sides of a calibrated match (favourite at 60%+ means the underdog is in the calibrated 20-40% zone):
    (side, model chance, low end of the model's range)."""
    p1, lo1, hi1 = pred.p1_win, pred.p1_ci_low, pred.p1_ci_high
    return [("p1", p1, lo1), ("p2", 1 - p1, 1 - hi1)]


def decide_with_market(side: str, p: float, min_american: int, mk: dict | None, pred=None,
                       F: dict | None = None) -> tuple[bool, dict]:
    """A pick is sent only when the live market confirms a mispriced Hard Rock line:
    Hard Rock's price is in the -200..+200 band, the model has >= min_ev at that price (and >= min_ev_low at the low
    end of its range), and the consensus of the other books also says +EV. Either side of the match can qualify;
    the side with the biggest edge vs the market wins. No market data -> no pick."""
    info: dict = {"market": (mk or {}).get("status", "not checked")}
    if not mk or mk.get("status") != "ok":
        info["reason"] = "no live market data, so no pick"
        return False, info
    info["books"] = mk.get("books")
    cons_p1 = mk.get("consensus_p1")
    hr = mk.get("hard_rock")
    if cons_p1 is None:
        info["reason"] = "too few books for a fair price"
        return False, info
    F = F or {"min_ev": 0.03, "min_ev_low": 0.0}
    if not hr:      # Hard Rock lists TT Elite late: decide on the market, send the minimum Hard Rock price to accept
        return _decide_without_hr(p, side, pred, cons_p1, mk, F, info)
    from ttq.odds.math import decimal_to_american
    hr_novig_p1 = (1 / hr[0]) / (1 / hr[0] + 1 / hr[1])
    if abs(hr_novig_p1 - cons_p1) > HR_OUTLIER:
        info["reason"] = (f"Hard Rock's line ({hr_novig_p1:.0%}) is far from every other book ({cons_p1:.0%}); "
                          "possible stale or void line")
        return False, info
    sides = _sides(pred, p, side) if pred is not None else [(side, p, p)]
    best, notes = None, []
    for sd, mp, lo in sides:
        dec = hr[0] if sd == "p1" else hr[1]
        cons = cons_p1 if sd == "p1" else 1 - cons_p1
        row = {"side": sd, "p": round(mp, 4), "hr_american": decimal_to_american(dec), "hr_decimal": round(dec, 3),
               "consensus_p": round(cons, 4), "model_ev_at_hr": round(mp * dec - 1, 4),
               "model_ev_low_at_hr": round(lo * dec - 1, 4), "market_ev_at_hr": round(cons * dec - 1, 4)}
        if not (PRICE_MIN <= dec <= PRICE_MAX):
            notes.append(f"{sd} {row['hr_american']:+d} outside -200..+200")
            continue
        if row["model_ev_at_hr"] < F["min_ev"] or row["model_ev_low_at_hr"] < F["min_ev_low"]:
            notes.append(f"{sd} {row['hr_american']:+d}: model edge {row['model_ev_at_hr']:+.1%} too small")
            continue
        if row["market_ev_at_hr"] < MARKET_DISAGREE:
            notes.append(f"{sd} {row['hr_american']:+d}: other books say {row['market_ev_at_hr']:+.1%}")
            continue
        if best is None or row["market_ev_at_hr"] > best["market_ev_at_hr"]:
            best = row
    if best is None:
        info["reason"] = "; ".join(notes) or "no side passes"
        # keep the favourite's numbers for the log
        sd, mp, _ = sides[0] if (pred is None or sides[0][1] >= 0.5) else sides[1]
        dec = hr[0] if sd == "p1" else hr[1]
        info.update({"side": sd, "hr_american": decimal_to_american(dec), "hr_decimal": round(dec, 3),
                     "consensus_p": round(cons_p1 if sd == "p1" else 1 - cons_p1, 4),
                     "market_ev_at_hr": round((cons_p1 if sd == "p1" else 1 - cons_p1) * dec - 1, 4)})
        return False, info
    info.update(best)
    info["reason"] = "misplaced Hard Rock line: model and market both say +EV"
    return True, info


REACH = 1.03   # the minimum asked of Hard Rock may sit at most 3% above the best price the other books offer


def _decide_without_hr(p: float, side: str, pred, cons_p1: float, mk: dict, F: dict, info: dict) -> tuple[bool, dict]:
    """No Hard Rock price at the last sweep. A side qualifies when the model has >= min_ev (and >= min_ev_low at the
    low end of its range) at a price that is also fair-or-better versus the other books, inside -200..+200, and
    realistically on offer (within REACH of what the other books pay). The pick then says: bet only at that price."""
    from ttq.odds.math import decimal_to_american
    refs = mk.get("refs") or {}
    sides = _sides(pred, p, side) if pred is not None else [(side, p, p)]
    best, notes = None, []
    for sd, mp, lo in sides:
        cons = cons_p1 if sd == "p1" else 1 - cons_p1
        offered = max([(a if sd == "p1" else b) for a, b in refs.values()] or [0])
        need = max((1 + F["min_ev"]) / mp, (1 + F["min_ev_low"]) / max(lo, 1e-6), 1 / cons, PRICE_MIN)
        am = round_up_american(need)
        need = american_to_decimal(am)
        if need > PRICE_MAX:
            notes.append(f"{sd}: would need {am:+d}, outside -200..+200")
            continue
        if not offered or need > offered * REACH:
            notes.append(f"{sd}: needs {am:+d}, other books only pay {decimal_to_american(offered) if offered else 0:+d}")
            continue
        row = {"side": sd, "p": round(mp, 4), "consensus_p": round(cons, 4), "min_american": am, "min_decimal": round(need, 3),
               "ref_decimal": round(offered, 3), "market_ev_at_min": round(cons * need - 1, 4), "hr_listed": False}
        if best is None or need / offered < best["min_decimal"] / best["ref_decimal"]:
            best = row
    if best is None:
        info["reason"] = "Hard Rock not listed yet; " + ("; ".join(notes) or "no side passes")
        return False, info
    info.update(best)
    info["reason"] = "model and market agree; Hard Rock not listed at last check, bet only at the minimum price"
    return True, info


def clv_record(db: Session) -> tuple[int, float | None]:
    row = db.get(AppSetting, "picks_log")
    vals = [v["clv"] for v in (row.value if row else {}).values() if v.get("clv") is not None]
    return len(vals), (sum(vals) / len(vals) if vals else None)


def suggested_units(db: Session, edge_vs_market: float | None, dec: float | None) -> float:
    """Flat 1 unit until the closing-line record proves an edge (100+ closes, average CLV > 0); then
    quarter-Kelly on the edge vs the market, capped to 0.5-2 units."""
    n, avg = clv_record(db)
    if n < 100 or avg is None or avg <= 0 or edge_vs_market is None or not dec or edge_vs_market <= 0:
        return 1.0
    kelly = edge_vs_market / (dec - 1)
    return round(min(2.0, max(0.5, 0.25 * kelly * 100 / 2)), 1)   # 1 unit ~ 2% of bankroll


def closing_lines(db: Session, now: datetime | None = None) -> dict:
    """Closing price for sent picks, read 1-8 minutes before start (1 credit each, only with credits to spare)."""
    import os
    from ttq.providers.oddspapi import board_by_fixture, caps, usage
    now = now or utcnow()
    if os.environ.get("ODDSPAPI_CLOSING", "0") != "1":   # off on the free plan: sweeps need every credit
        return {"closed": 0, "why": "closing reads off"}
    row = db.get(AppSetting, "picks_log")
    if not row:
        return {"closed": 0}
    log = dict(row.value)
    done = 0
    for mid, pk in log.items():
        if pk.get("close_checked") or not pk.get("fixture_id"):
            continue
        m = db.get(Match, int(mid))
        if m is None:
            continue
        mins = (as_utc(m.scheduled_at) - now).total_seconds() / 60
        if not (1 <= mins <= 8):
            continue
        u, (d_cap, _) = usage(db, now), caps()
        if u["today"] >= d_cap - 1:        # always keep one credit for a new pick
            continue
        b = board_by_fixture(db, pk["fixture_id"], bool(pk.get("flipped")), now)
        pk = dict(pk)
        pk["close_checked"] = True
        if b and b.get("status") == "ok":
            side_p = lambda p1: None if p1 is None else (p1 if pk["side"] == "p1" else 1 - p1)
            cp = side_p(b.get("consensus_p1"))
            hr = b.get("hard_rock")
            pk["close_consensus_p"] = round(cp, 4) if cp else None
            pk["close_hr"] = (hr[0] if pk["side"] == "p1" else hr[1]) if hr else None
            taken = pk.get("hr_auto_dec") or american_to_decimal(pk["min_american"])
            if cp:
                pk["clv"] = round(taken * cp - 1, 4)     # price taken vs the fair closing price
        log[mid] = pk
        done += 1
    if done:
        row.value = log
        db.flush()
    return {"closed": done}


def _log_market_check(db: Session, row: dict) -> None:
    r = db.get(AppSetting, "market_checks")
    items = (list(r.value.get("items", [])) if r else [])[-299:] + [row]
    if r:
        r.value = {"items": items}
    else:
        db.add(AppSetting(key="market_checks", value={"items": items}))
    db.flush()


SWEEP_WINDOW_MIN = 90     # after a sweep, every match starting in the next 90 min is evaluated at once


def picks_job(db: Session) -> dict:
    from ttq.providers.oddspapi import from_sweep, latest_sweep, sweep, sweep_fresh_minutes
    from ttq.services.alerts import raise_alert
    from ttq.services.messages import conditional_pick_text
    from ttq.services.summary import log_picks
    out, logged, stats, skipped, unmark = [], [], {}, [], []
    resweep_tried = False
    try:
        swept = sweep(db)
    except Exception as e:  # noqa
        swept = {"swept": False, "why": f"error {e.__class__.__name__}"}
    sw = latest_sweep(db)
    fresh = bool(sw.get("fetched_at")) and (utcnow() - datetime.fromisoformat(sw["fetched_at"])).total_seconds() < 60 * sweep_fresh_minutes()
    if not fresh and not sweep(db, need=True).get("swept"):   # no live market data: nothing can be confirmed
        return {"sent": 0, "picks": [], "skipped_by_market": [], "checked": {"no_fresh_sweep": True}, "sweep": swept}
    for pk in build_picks(db, stats=stats, max_minutes=SWEEP_WINDOW_MIN):
        m = pk["match"]
        try:
            mk = from_sweep(db, m.player1.canonical_name, m.player2.canonical_name, m.scheduled_at)
            if mk.get("status") in ("not in sweep", "no fresh sweep") and not resweep_tried:
                resweep_tried = True                      # the books list matches ~2 h ahead: fetch a newer board
                r = sweep(db, need=True)
                if r.get("swept"):
                    swept = r
                    mk = from_sweep(db, m.player1.canonical_name, m.player2.canonical_name, m.scheduled_at)
        except Exception:  # noqa
            mk = {"status": "error"}
        send, info = decide_with_market(pk["side"], pk["p"], pk["min_american"], mk, pk["pred"], get_filters(db, False))
        if info.get("market") in ("no fresh sweep", "not in sweep", "error"):
            unmark.append(m.id)             # nothing decided: look again when the next sweep arrives
        if send and info.get("hr_listed") is False:
            pk = {**pk, "side": info["side"], "p": info["p"], "min_american": info["min_american"]}
        elif send and info.get("side") and info["side"] != pk["side"]:      # the market made the other side the play
            pk = {**pk, "side": info["side"], "p": info["p"]}
            t = side_target(info["p"], (pk["pred"].p1_ci_low if info["side"] == "p1" else 1 - pk["pred"].p1_ci_high),
                            get_filters(db, False))
            pk["min_american"] = round_up_american(t) if t else info["hr_american"]
        info["units"] = suggested_units(db, info.get("market_ev_at_hr"), info.get("hr_decimal"))
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
                       "hr_auto": info.get("hr_american"), "hr_auto_dec": info.get("hr_decimal"),
                       "consensus_p": info.get("consensus_p"), "books": info.get("books"), "units": info["units"],
                       "fixture_id": (mk or {}).get("fixture_id"), "flipped": (mk or {}).get("flipped")})
    if logged:
        log_picks(db, logged)
    if unmark:
        row = db.get(AppSetting, "picks_sent")
        if row:
            row.value = {k: v for k, v in row.value.items() if int(k) not in unmark}
            db.flush()
    try:
        closes = closing_lines(db)
    except Exception:  # noqa
        closes = {"closed": "error"}
    return {"sent": len(out), "picks": out, "skipped_by_market": skipped, "checked": stats, "closing": closes,
            "sweep": swept}
