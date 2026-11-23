from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from ttq.worker import build_scheduler


def test_data_jobs_run_at_startup_then_on_intervals():
    t0 = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    s = build_scheduler(start_at=t0, scheduler_cls=BackgroundScheduler)
    s.start(paused=True)
    try:
        jobs = {j.id: j for j in s.get_jobs()}
        assert set(jobs) == {"ingest_results", "ingest_odds", "settle", "predict_scan", "monitor", "retrain"}
        order = ["ingest_results", "ingest_odds", "settle", "predict_scan", "monitor"]
        times = [jobs[k].next_run_time for k in order]
        assert times == sorted(times)
        assert all(t0 <= t <= t0 + timedelta(minutes=2) for t in times)
        assert {k: jobs[k].trigger.interval for k in order} == {
            "ingest_results": timedelta(minutes=10), "ingest_odds": timedelta(minutes=3), "settle": timedelta(minutes=2),
            "predict_scan": timedelta(minutes=5), "monitor": timedelta(minutes=10)}
        nr = jobs["retrain"].next_run_time
        assert (nr.hour, nr.minute) == (7, 17)
    finally:
        s.shutdown(wait=False)
