"""Private online dashboard, published by the GitHub bot to GitHub Pages.

The repository is public, so the page itself is public too. All data is therefore encrypted (AES-256-GCM, key from
the password with PBKDF2-SHA256) and only decrypted in the viewer's browser after they type the password. Nothing
readable about picks or bets is ever published in the clear.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ttq.core.config import get_settings
from ttq.core.timeutil import as_utc, utcnow
from ttq.models import AppSetting, Match, ModelVersion
from ttq.odds.math import american_to_decimal
from ttq.services.app_settings import get_filters, get_setting
from ttq.services.modeling import latest_prediction
from ttq.services.targets import round_up_american, side_target

PBKDF2_ITERATIONS = 200_000


def _tz(db):
    return ZoneInfo(get_setting(db, "display").get("timezone") or get_settings().user_timezone)


def _fmt(dt, tz) -> str:
    d = as_utc(dt).astimezone(tz)
    return f"{d:%b} {d.day}, {d.strftime('%I:%M %p').lstrip('0')}"


def _upcoming(db: Session, now, tz, hours: int = 3) -> list[dict]:
    F = get_filters(db, False)
    cfg = get_setting(db, "alerts")
    max_w = float(cfg.get("picks_max_interval", 0.20))
    min_prob = float(cfg.get("picks_min_prob", 0.60))
    ms = db.scalars(select(Match).where(Match.is_demo.is_(False), Match.status == "SCHEDULED",
                                        Match.scheduled_at >= now, Match.scheduled_at <= now + timedelta(hours=hours))
                    .order_by(Match.scheduled_at)).all()
    out = []
    for m in ms:
        pred = latest_prediction(db, m.id)
        row = {"time": _fmt(m.scheduled_at, tz), "p1": m.player1.canonical_name, "p2": m.player2.canonical_name}
        if not pred:
            out.append({**row, "status": "no prediction yet"})
            continue
        p1 = pred.p1_win
        fav_p1 = p1 >= 0.5
        p, lo = (p1, pred.p1_ci_low) if fav_p1 else (1 - p1, 1 - pred.p1_ci_high)
        width = pred.p1_ci_high - pred.p1_ci_low
        f = pred.features or {}
        comps = list((pred.component_probs or {}).values()) or [p1]
        reasons = []
        if pred.data_quality == "LOW":
            reasons.append("low data quality")
        if p < min_prob:
            reasons.append(f"under {min_prob:.0%}")
        if width > max_w:
            reasons.append("too uncertain")
        if min(f.get("_n1") or 0, f.get("_n2") or 0) < F["min_player_matches"]:
            reasons.append("too few matches")
        t = side_target(p, lo, F)
        out.append({**row, "p1_prob": round(p1, 3), "lean": m.player1.canonical_name if fav_p1 else m.player2.canonical_name,
                    "lean_prob": round(p, 3), "min_price": round_up_american(t) if t else None,
                    "status": "passes rules" if not reasons and t else ("no sensible price" if not reasons else ", ".join(reasons))})
    return out


def _picks(db: Session, tz) -> tuple[list[dict], dict]:
    row = db.get(AppSetting, "picks_log")
    items = sorted((row.value if row else {}).items(), key=lambda kv: kv[1]["sent_at"], reverse=True)
    out = []
    rec = {"w": 0, "l": 0, "units": 0.0, "bw": 0, "bl": 0, "bunits": 0.0, "logged": 0, "beat": 0}
    for mid, pk in items:
        m = db.get(Match, int(mid))
        if m is None:
            continue
        picked_id = m.player1_id if pk["side"] == "p1" else m.player2_id
        name = pk.get("pick_name") or (m.player1.canonical_name if pk["side"] == "p1" else m.player2.canonical_name)
        result, units = "pending", None
        if m.status in ("CANCELLED", "WALKOVER", "RETIRED") or (m.status == "FINISHED" and m.winner_id is None):
            result = "void"
        elif m.status == "FINISHED":
            won = m.winner_id == picked_id
            result = "won" if won else "lost"
            units = round(american_to_decimal(pk["min_american"]) - 1, 2) if won else -1.0
            rec["w" if won else "l"] += 1
            rec["units"] += units
        hr = pk.get("hr_price")
        if pk.get("hr_action"):
            rec["logged"] += 1
            if hr is not None and american_to_decimal(hr) >= american_to_decimal(pk["min_american"]) - 1e-9:
                rec["beat"] += 1
        if pk.get("hr_action") == "bet" and hr is not None and result in ("won", "lost"):
            if result == "won":
                rec["bw"] += 1
                rec["bunits"] += american_to_decimal(hr) - 1
            else:
                rec["bl"] += 1
                rec["bunits"] -= 1
        out.append({"_at": as_utc(m.scheduled_at).astimezone(tz).isoformat(),
                    "sent": _fmt(datetime.fromisoformat(pk["sent_at"]), tz), "match_time": _fmt(m.scheduled_at, tz),
                    "match": f"{m.player1.canonical_name} vs {m.player2.canonical_name}", "pick": name,
                    "prob": pk.get("p"), "min": pk["min_american"], "hr_action": pk.get("hr_action"), "hr_price": hr,
                    "score": f"{m.sets_p1}-{m.sets_p2}" if m.sets_p1 is not None else None,
                    "result": result, "units": units})
    rec["units"] = round(rec["units"], 2)
    rec["bunits"] = round(rec["bunits"], 2)
    return out, rec


def _stats(picks: list[dict]) -> dict:
    """Hit rate and performance stats over settled picks (graded at each pick's minimum price, 1 unit each)."""
    settled = sorted((p for p in picks if p["result"] in ("won", "lost")), key=lambda p: p["_at"])
    n = len(settled)
    wins = sum(p["result"] == "won" for p in settled)
    units = sum(p["units"] for p in settled)
    exp = sum(p["prob"] or 0 for p in settled) / n if n else None
    curve, run = [], 0.0
    for i, p in enumerate(settled, 1):
        run += p["units"]
        curve.append({"i": i, "units": round(run, 2), "label": f"{p['pick']} ({p['result']})", "time": p["match_time"]})
    streak = ""
    if settled:
        last = settled[-1]["result"]
        k = 0
        for p in reversed(settled):
            if p["result"] != last:
                break
            k += 1
        streak = f"{'W' if last == 'won' else 'L'}{k}"
    by_day: dict[str, dict] = {}
    for p in settled:
        d = by_day.setdefault(p["_at"][:10], {"date": p["_at"][:10], "w": 0, "l": 0, "units": 0.0})
        d["w" if p["result"] == "won" else "l"] += 1
        d["units"] = round(d["units"] + p["units"], 2)
    buckets = {}
    for name, test in (("Favorites (minimum below +100)", lambda a: a < 0),
                       ("Underdogs (minimum +100 or more)", lambda a: a >= 0)):
        grp = [p for p in settled if test(p["min"])]
        gw = sum(p["result"] == "won" for p in grp)
        buckets[name] = {"n": len(grp), "w": gw, "l": len(grp) - gw,
                         "hit": (gw / len(grp)) if grp else None,
                         "units": round(sum(p["units"] for p in grp), 2)}
    return {"settled": n, "wins": wins, "losses": n - wins, "hit_rate": (wins / n) if n else None,
            "expected_hit_rate": exp, "units": round(units, 2), "roi": (units / n) if n else None,
            "avg_min_price": round(sum(p["min"] for p in settled) / n) if n else None,
            "pending": sum(p["result"] == "pending" for p in picks), "voids": sum(p["result"] == "void" for p in picks),
            "total": len(picks), "streak": streak, "last10": "".join("W" if p["result"] == "won" else "L" for p in settled[-10:]),
            "curve": curve, "by_day": sorted(by_day.values(), key=lambda d: d["date"], reverse=True)[:14],
            "buckets": buckets}


def build_data(db: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    tz = _tz(db)
    champ = db.scalar(select(ModelVersion).where(ModelVersion.status == "CHAMPION", ModelVersion.is_demo.is_(False)))
    n_done = db.scalar(select(func.count(Match.id)).where(Match.is_demo.is_(False), Match.status == "FINISHED")) or 0
    picks, rec = _picks(db, tz)
    cfg = get_setting(db, "alerts")
    test = (champ.metrics or {}).get("test", {}) if champ else {}
    upcoming = _upcoming(db, now, tz)
    lrow = db.get(AppSetting, "learning_log")
    entries = (lrow.value.get("entries") if lrow else None) or []
    return {
        "learning": {"last": entries[-1] if entries else None,
                     "history": [{k: e[k] for k in ("date", "matches", "threshold_after", "note")} for e in entries[-10:]][::-1]},
        "stats": _stats(picks),
        "model_test": {"accuracy": test.get("accuracy"), "log_loss": test.get("log_loss"), "n": test.get("n")},
        "upcoming_passing": sum(u["status"] == "passes rules" for u in upcoming),
        "updated": _fmt(now, tz),
        "model": f"{champ.name}_{champ.version}" if champ else None,
        "trained": champ.trained_at.strftime("%Y-%m-%d") if champ and champ.trained_at else None,
        "matches_in_history": n_done,
        "rules": {"min_prob": cfg.get("picks_min_prob"), "min_ev": get_filters(db, False)["min_ev"], "max_uncertainty": cfg.get("picks_max_interval"),
                  "lead_minutes": cfg.get("picks_max_minutes")},
        "record": rec, "picks": [{k: v for k, v in p.items() if k != "_at"} for p in picks[:200]],
        "upcoming": upcoming,
    }


def encrypt(data: dict, password: str) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(data).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "iter": PBKDF2_ITERATIONS, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def decrypt(blob: dict, password: str) -> dict:
    """For tests: the same scheme the page uses in the browser."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    d = lambda s: base64.b64decode(s)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=d(blob["salt"]), iterations=blob["iter"]).derive(password.encode())
    return json.loads(AESGCM(key).decrypt(d(blob["iv"]), d(blob["ct"]), None))


def write_site(db: Session, outdir: str, password: str) -> dict:
    os.makedirs(outdir, exist_ok=True)
    data = build_data(db)
    with open(os.path.join(outdir, "data.json"), "w") as fh:
        json.dump(encrypt(data, password), fh)
    with open(os.path.join(os.path.dirname(__file__), "dashboard_page.html")) as src, \
            open(os.path.join(outdir, "index.html"), "w") as dst:
        dst.write(src.read())
    with open(os.path.join(outdir, ".nojekyll"), "w"):
        pass
    return {"picks": len(data["picks"]), "upcoming": len(data["upcoming"])}
