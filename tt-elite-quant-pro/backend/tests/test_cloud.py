from ttq.services import cloud, jobs


def test_cloud_cycle_runs_every_step_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "run_job", lambda name, fn, *a, **k: calls.append(name) or {"ok": True})
    out = cloud.cloud_cycle(120)
    assert calls == ["cloud_history", "cloud_window", "picks", "ingest_results", "retrain", "predict_scan", "settle", "picks", "weekly_summary"]
    assert set(out) == {"history", "window", "picks_early", "results", "retrain", "predict", "settle", "picks", "weekly_summary"}


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
