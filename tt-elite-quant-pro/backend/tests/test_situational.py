from datetime import datetime, timedelta, timezone

from ttq.features.builder import FeatureBuilder, MatchRecord, tod_band


def _m(i, a, b, t, a_wins, venue="OSP"):
    return MatchRecord(id=i, p1=a, p2=b, scheduled_at=t, finished_at=t + timedelta(minutes=20), p1_won=a_wins,
                       sets_p1=3 if a_wins else 0, sets_p2=0 if a_wins else 3, venue=venue)


def test_momentum_reflects_recent_overperformance_only():
    fb = FeatureBuilder()
    t0 = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    for i in range(6):                       # player 1 beats player 3 six times today
        fb.update(_m(i, 1, 3, t0 + timedelta(minutes=30 * i), True))
    nxt = _m(99, 1, 2, t0 + timedelta(hours=4), True)
    f = fb.features(nxt, nxt.scheduled_at)
    assert f["mom24_diff"] > 0 and f["session_diff"] > 0
    later = fb.features(nxt, t0 + timedelta(days=3))
    assert later["mom24_diff"] == 0 and later["session_diff"] == 0


def test_tod_band_uses_polish_time():
    assert tod_band(datetime(2026, 11, 20, 22, 30, tzinfo=timezone.utc)) == 0   # 23:30 in Poland
    assert tod_band(datetime(2026, 11, 20, 8, tzinfo=timezone.utc)) == 1
    assert tod_band(datetime(2026, 11, 20, 13, tzinfo=timezone.utc)) == 2
    assert tod_band(datetime(2026, 11, 20, 18, tzinfo=timezone.utc)) == 3
