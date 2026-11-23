"""One-shot readiness check for the operator: is everything needed for Telegram picks in place?"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from ttq.core.config import get_settings
from ttq.core.db import SessionLocal
from ttq.core.timeutil import as_utc, utcnow
from ttq.models import Alert, DataSource, JobRun, Match, ModelVersion, Prediction
from ttq.services.app_settings import get_setting


def system_status() -> dict:
    s = get_settings()
    now = utcnow()
    checks = []
    with SessionLocal() as db:
        fin = db.scalar(select(func.count(Match.id)).where(Match.is_demo.is_(False), Match.status == "FINISHED",
                                                         Match.result_verified.is_(True))) or 0
        checks.append(("match history", {"ok": fin >= 1500, "detail": f"{fin} verified finished matches (need 1,500+)"}))
        src = db.scalar(select(DataSource).where(DataSource.key == "ttseries"))
        fresh = bool(src and src.last_success_at and now - as_utc(src.last_success_at) < timedelta(hours=1))
        checks.append(("official results feed", {"ok": fresh, "detail": (
            f"last update {as_utc(src.last_success_at):%Y-%m-%d %H:%M} UTC" if src and src.last_success_at else "never updated")}))
        champ = db.scalar(select(ModelVersion).where(ModelVersion.status == "CHAMPION", ModelVersion.is_demo.is_(False)))
        checks.append(("trained model", {"ok": champ is not None,
                                         "detail": f"{champ.name}_{champ.version}" if champ else "none yet (train-force --live)"}))
        upcoming = db.scalar(select(func.count(func.distinct(Prediction.match_id))).join(Match, Match.id == Prediction.match_id)
                             .where(Prediction.is_demo.is_(False), Prediction.is_backtest.is_(False),
                                    Match.status == "SCHEDULED", Match.scheduled_at > now)) or 0
        checks.append(("predictions for upcoming matches", {"ok": upcoming > 0, "detail": f"{upcoming} matches"}))
        last_job = db.scalar(select(JobRun).where(JobRun.job == "picks").order_by(JobRun.started_at.desc()).limit(1))
        worker_ok = bool(last_job and now - as_utc(last_job.started_at) < timedelta(minutes=15))
        checks.append(("scheduler (worker)", {"ok": worker_ok, "detail": (
            f"picks job last ran {as_utc(last_job.started_at):%H:%M} UTC ({'ok' if last_job.ok else 'ERROR'})" if last_job
            else "picks job has not run yet (worker running?)")}))
        tg = bool(s.telegram_bot_token and s.telegram_chat_id)
        cfg = get_setting(db, "alerts")
        checks.append(("Telegram configured", {"ok": tg and cfg.get("telegram", True),
                                               "detail": "token + chat id set" if tg else "set TTQ_TELEGRAM_BOT_TOKEN and TTQ_TELEGRAM_CHAT_ID in .env"}))
        checks.append(("conditional picks enabled", {"ok": bool(cfg.get("conditional_picks", True)),
                                                     "detail": f"daily cap: {cfg.get('picks_max_per_day') or 'none'}"}))
        sent = db.scalar(select(func.count(Alert.id)).where(Alert.kind == "pick", Alert.created_at >= now - timedelta(days=1))) or 0
        checks.append(("picks sent in last 24 h", {"ok": True, "detail": str(sent)}))
    ready = all(v["ok"] for _, v in checks)
    return {"ready": ready, "checks": checks}
