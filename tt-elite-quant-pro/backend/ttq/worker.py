"""Background scheduler. Run: python -m ttq.worker"""
import logging
import time

from apscheduler.schedulers.blocking import BlockingScheduler

from ttq.core.logging import setup_logging
from ttq.services import jobs

log = logging.getLogger("ttq.worker")


def main():
    setup_logging()
    s = BlockingScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})
    s.add_job(lambda: jobs.run_job("ingest_results", jobs.ingest_results_job), "interval", minutes=10, id="ingest_results")
    s.add_job(lambda: jobs.run_job("ingest_odds", jobs.ingest_odds_job), "interval", minutes=3, id="ingest_odds")
    s.add_job(lambda: jobs.run_job("predict_scan", jobs.predict_scan_job), "interval", minutes=5, id="predict_scan")
    s.add_job(lambda: jobs.run_job("settle", jobs.settle_job), "interval", minutes=2, id="settle")
    s.add_job(lambda: jobs.run_job("monitor", jobs.monitor_job), "interval", minutes=10, id="monitor")
    s.add_job(lambda: jobs.run_job("retrain", jobs.retrain_job), "cron", hour=7, minute=17, id="retrain")
    log.info("worker started")
    s.start()


if __name__ == "__main__":
    main()
