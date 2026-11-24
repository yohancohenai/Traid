"""Weekly Telegram scorecard for the picks the bot sent.

Every sent pick is kept in app_settings["picks_log"] (90 days). Each pick is graded at its minimum price, the worst
price you would have taken, so the record is conservative: betting at a better Hard Rock price only improves it.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ttq.core.config import get_settings
from ttq.core.timeutil import utcnow
from ttq.models import AppSetting, Match
from ttq.odds.math import american_to_decimal
from ttq.services.app_settings import get_setting

KEEP_DAYS = 90


def _row(db: Session, key: str):
    return db.get(AppSetting, key)


def _save(db: Session, key: str, value):
    row = _row(db, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()


def log_picks(db: Session, picks: list[dict], now: datetime | None = None) -> None:
    now = now or utcnow()
    row = _row(db, "picks_log")
    log = dict(row.value) if row else {}
    cutoff = now - timedelta(days=KEEP_DAYS)
    log = {k: v for k, v in log.items() if datetime.fromisoformat(v["sent_at"]) > cutoff}
    for pk in picks:
        log[str(pk["match_id"])] = {**pk, "sent_at": now.isoformat()}
    _save(db, "picks_log", log)


def grade(db: Session, since: datetime, until: datetime) -> dict:
    row = _row(db, "picks_log")
    wins = losses = voids = pending = 0
    units = staked = prob_sum = 0.0
    for mid, pk in (row.value if row else {}).items():
        if not (since <= datetime.fromisoformat(pk["sent_at"]) < until):
            continue
        m = db.get(Match, int(mid))
        if m is None or m.status in ("SCHEDULED", "LIVE"):
            pending += 1
            continue
        if m.status in ("CANCELLED", "WALKOVER", "RETIRED") or m.winner_id is None:
            voids += 1
            continue
        picked = m.player1_id if pk["side"] == "p1" else m.player2_id
        staked += 1
        prob_sum += float(pk.get("p") or 0)
        if m.winner_id == picked:
            wins += 1
            units += american_to_decimal(pk["min_american"]) - 1
        else:
            losses += 1
            units -= 1
    n = wins + losses
    return {"picks": n + voids + pending, "wins": wins, "losses": losses, "voids": voids, "pending": pending,
            "units": round(units, 2), "roi": (units / staked) if staked else None,
            "win_rate": (wins / n) if n else None, "expected_win_rate": (prob_sum / n) if n else None}


def summary_text(week: dict, all_time: dict, start, end) -> str:
    def line(r):
        if not (r["wins"] + r["losses"]):
            return "no settled picks yet"
        return (f"{r['wins']}-{r['losses']} | {r['units']:+.2f} units | ROI {r['roi']:+.1%} | "
                f"won {r['win_rate']:.0%} (model expected {r['expected_win_rate']:.0%})")
    lines = [f"Week {start:%b} {start.day} - {end:%b} {end.day}: {week['picks']} picks sent",
             f"This week: {line(week)}"]
    extra = [f"{week[k]} {k}" for k in ("voids", "pending") if week[k]]
    if extra:
        lines.append("Not graded: " + ", ".join(extra))
    lines += [f"Last 90 days: {line(all_time)}", "",
              "Graded at each pick's minimum price (1 unit each). Better Hard Rock prices only improve this.",
              "Small samples swing a lot; judge the bot over hundreds of picks."]
    return "\n".join(lines)


def weekly_summary_job(db: Session, now: datetime | None = None, force: bool = False) -> dict:
    """Send once per week, on the first run from Monday 9 AM local time."""
    now = now or utcnow()
    tz = ZoneInfo(get_setting(db, "display").get("timezone") or get_settings().user_timezone)
    local = now.astimezone(tz)
    week_key = f"{local.isocalendar().year}-W{local.isocalendar().week:02d}"
    last = _row(db, "weekly_summary_last")
    if not force:
        if local.weekday() != 0 or local.hour < 9:
            return {"sent": False, "why": "not Monday 9 AM yet"}
        if last and last.value.get("week") == week_key:
            return {"sent": False, "why": "already sent this week"}
    end_local = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local.weekday())
    start_local = end_local - timedelta(days=7)
    week = grade(db, start_local, end_local)
    all_time = grade(db, now - timedelta(days=KEEP_DAYS), now)
    from ttq.services.alerts import raise_alert
    text = summary_text(week, all_time, start_local, end_local - timedelta(days=1))
    raise_alert(db, "weekly_summary", "TT Elite weekly scorecard", text, f"weekly:{week_key}:{now:%H%M%S}" if force
                else f"weekly:{week_key}", "INFO", False, rate_limited=False)
    _save(db, "weekly_summary_last", {"week": week_key, "at": now.isoformat()})
    return {"sent": True, "week": week, "all_time": all_time}
