"""Background scheduler. Run: python -m ttq.worker

Data jobs run once right after start (staggered), then on their intervals. That matters on a Mac: when it wakes and
Docker restarts the worker, results and settlements are refreshed within about a minute, not a full interval later.
"""
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler

from ttq.core.logging import setup_logging
from ttq.services import jobs

log = logging.getLogger("ttq.worker")

def _targets_job(db):
    from ttq.services.targets import price_targets_job
    return price_targets_job(db)


# (job id, function, interval minutes, startup delay seconds)
INTERVAL_JOBS = [
    ("ingest_results", jobs.ingest_results_job, 10, 0),
    ("ingest_odds", jobs.ingest_odds_job, 3, 20),
    ("settle", jobs.settle_job, 2, 40),
    ("predict_scan", jobs.predict_scan_job, 5, 60),   # after fresh results
    ("monitor", jobs.monitor_job, 10, 90),
    ("price_targets", _targets_job, 30, 120),  # after fresh predictions
]


def _runner(name, fn):
    def run():
        jobs.run_job(name, fn)
    return run


def build_scheduler(start_at: datetime | None = None, scheduler_cls=BlockingScheduler):
    start_at = start_at or datetime.now(timezone.utc)
    s = scheduler_cls(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})
    for name, fn, minutes, delay in INTERVAL_JOBS:
        s.add_job(_runner(name, fn), "interval", minutes=minutes, id=name,
                  next_run_time=start_at + timedelta(seconds=delay))
    # Training is gated by retrain_due(); daily is enough and it never needs to run at boot.
    s.add_job(_runner("retrain", jobs.retrain_job), "cron", hour=7, minute=17, id="retrain")
    return s


def main():
    setup_logging()
    s = build_scheduler()
    log.info("worker started; data jobs run now, then on their intervals")
    s.start()


if __name__ == "__main__":
    main()
