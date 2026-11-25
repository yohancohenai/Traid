"""One complete bot cycle for scheduled cloud runs (GitHub Actions): no worker process, no laptop.

Each run: fetch results (first run downloads the full history), retrain if due, predict upcoming matches, settle,
then send conditional picks for every match starting within the look-ahead window. Picks are remembered in the
database (app_settings["picks_sent"]), which the workflow saves between runs, so no match is sent twice.
"""
import logging
import time

from sqlalchemy import func, select

from ttq.models import Tournament
from ttq.services import jobs, modeling, monitoring
from ttq.services.app_settings import get_setting, set_setting

log = logging.getLogger(__name__)


def cloud_cycle(window_minutes: int = 35, min_minutes: int = 10, hold_minutes: float = 0, max_interval: float = 0.20, min_prob: float = 0.60, sleep=time.sleep,
                clock=time.monotonic) -> dict:
    """window_minutes is the lead time: a pick is released when its match is at most this far away, so picks arrive
    one at a time, each about `window_minutes` before its start. With hold_minutes > 0 the run stays alive and checks
    every minute, releasing each pick as its match reaches the lead time."""
    started = clock()
    out: dict = {}

    def first_run(db):
        n = db.scalar(select(func.count(Tournament.id)).where(Tournament.source_key == "ttseries"))
        return {"backfill": jobs.backfill_ttseries(1)} if not n else {"backfill": "not needed"}
    out["history"] = jobs.run_job("cloud_history", first_run)

    def window(db):
        cfg = get_setting(db, "alerts")
        want = {"picks_min_minutes": min_minutes, "picks_max_minutes": window_minutes, "picks_max_interval": max_interval,
                "picks_min_prob": min_prob}
        if any(cfg.get(k) != v for k, v in want.items()):
            set_setting(db, "alerts", want)
        return {"window": [min_minutes, window_minutes], "max_interval": max_interval, "min_prob": min_prob}
    out["window"] = jobs.run_job("cloud_window", window)

    def picks(db):
        from ttq.services.targets import picks_job
        return picks_job(db)
    def replies(db):
        from ttq.services.price_log import poll_replies
        return poll_replies(db)
    out["replies"] = jobs.run_job("price_replies", replies)

    # Send picks from the previous run's predictions straight away, before the slower steps below.
    out["picks_early"] = jobs.run_job("picks", picks)

    out["results"] = jobs.run_job("ingest_results", jobs.ingest_results_job)

    def retrain_live(db):
        due, why = monitoring.retrain_due(db, False)
        if not due:
            return {"due": False, "why": why}
        return {"due": True, "why": why, "train": modeling.train_and_register(db, False, promote="auto")}
    out["retrain"] = jobs.run_job("retrain", retrain_live)

    out["predict"] = jobs.run_job("predict_scan", jobs.predict_scan_job)
    out["settle"] = jobs.run_job("settle", jobs.settle_job)

    out["picks"] = jobs.run_job("picks", picks)

    def learn(db):
        from ttq.services.learning import daily_self_check, prune_if_due
        return {**daily_self_check(db), "housekeeping": prune_if_due(db)}
    out["self_check"] = jobs.run_job("self_check", learn)

    def weekly(db):
        from ttq.services.summary import weekly_summary_job
        return weekly_summary_job(db)
    out["weekly_summary"] = jobs.run_job("weekly_summary", weekly)

    released = 0
    while clock() - started + 60 < hold_minutes * 60:
        sleep(60)
        jobs.run_job("price_replies", replies)
        r = jobs.run_job("picks", picks)
        released += (r or {}).get("sent", 0) if isinstance(r, dict) else 0
    out["released_while_waiting"] = released

    def market(db):
        from ttq.providers.oddspapi import sweep_status
        return sweep_status(db)
    out["market"] = jobs.run_job("market_status", market)
    return out
