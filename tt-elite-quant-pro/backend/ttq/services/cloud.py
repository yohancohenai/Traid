"""One complete bot cycle for scheduled cloud runs (GitHub Actions): no worker process, no laptop.

Each run: fetch results (first run downloads the full history), retrain if due, predict upcoming matches, settle,
then send conditional picks for every match starting within the look-ahead window. Picks are remembered in the
database (app_settings["picks_sent"]), which the workflow saves between runs, so no match is sent twice.
"""
import logging

from sqlalchemy import func, select

from ttq.models import Tournament
from ttq.services import jobs, modeling, monitoring
from ttq.services.app_settings import get_setting, set_setting

log = logging.getLogger(__name__)


def cloud_cycle(window_minutes: int = 120, min_minutes: int = 10) -> dict:
    out: dict = {}

    def first_run(db):
        n = db.scalar(select(func.count(Tournament.id)).where(Tournament.source_key == "ttseries"))
        return {"backfill": jobs.backfill_ttseries(1)} if not n else {"backfill": "not needed"}
    out["history"] = jobs.run_job("cloud_history", first_run)

    def window(db):
        cfg = get_setting(db, "alerts")
        if (cfg.get("picks_min_minutes"), cfg.get("picks_max_minutes")) != (min_minutes, window_minutes):
            set_setting(db, "alerts", {"picks_min_minutes": min_minutes, "picks_max_minutes": window_minutes})
        return {"window": [min_minutes, window_minutes]}
    out["window"] = jobs.run_job("cloud_window", window)

    def picks(db):
        from ttq.services.targets import picks_job
        return picks_job(db)
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
    return out
