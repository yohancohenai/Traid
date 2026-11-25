from ttq.services import cloud, jobs


def test_cloud_cycle_runs_every_step_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "run_job", lambda name, fn, *a, **k: calls.append(name) or {"ok": True})
    out = cloud.cloud_cycle(120)
    assert calls == ["cloud_history", "cloud_window", "price_replies", "picks", "ingest_results", "retrain", "predict_scan", "settle", "picks", "self_check", "weekly_summary", "market_status"]
    assert set(out) == {"history", "window", "replies", "picks_early", "results", "retrain", "predict", "settle", "picks", "self_check", "weekly_summary", "released_while_waiting", "market"}


def test_cloud_window_sets_two_hour_lookahead(db):
    from ttq.services.app_settings import get_setting
    captured = {}
    def fake_run(name, fn, *a, **k):
        if name == "cloud_window":
            captured["r"] = fn(db)
        return {}
    import pytest
    mp = pytest.MonkeyPatch(); mp.setattr(jobs, "run_job", fake_run)
    try:
        cloud.cloud_cycle(120)
    finally:
        mp.undo()
    cfg = get_setting(db, "alerts")
    assert (cfg["picks_min_minutes"], cfg["picks_max_minutes"]) == (10, 120)


def test_hold_releases_picks_every_minute(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "run_job", lambda name, fn, *a, **k: calls.append(name) or {"sent": 1})
    t = [0.0]
    def sleep(s):
        t[0] += s
    out = cloud.cloud_cycle(35, hold_minutes=8, sleep=sleep, clock=lambda: t[0])
    extra = calls[11:-1]                    # after the normal cycle: replies + picks each minute
    assert set(extra) == {"price_replies", "picks"} and extra.count("picks") == 7
    assert out["released_while_waiting"] == 7 and t[0] <= 8 * 60
