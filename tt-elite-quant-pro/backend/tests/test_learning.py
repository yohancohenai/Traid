from datetime import timedelta

from ttq.core.timeutil import utcnow
from ttq.models import Alert, AppSetting, Prediction
from ttq.services.app_settings import get_setting, set_setting
from ttq.services.learning import calibration_table, choose_threshold, daily_self_check, live_pairs, prune


def test_choose_threshold_moves_toward_reliable_range_in_small_steps():
    pairs = [(0.59, i % 2 == 0) for i in range(400)]            # 59% favourites win only 50%
    pairs += [(0.65, i % 100 < 66) for i in range(400)]         # 65% favourites win 66%
    t = calibration_table(pairs)
    new, note = choose_threshold(t, 0.58)
    assert new == 0.60 and "over-confident" in note             # target 0.60+, max step 0.02
    assert choose_threshold(calibration_table([(0.7, True)] * 10), 0.60)[0] == 0.60   # too little data: no change


def _finished(f, db, p1, p1_wins, hours_ago=5):
    a, b = f.player(), f.player()
    m = f.match(a, b, at=utcnow() - timedelta(hours=hours_ago))
    pr = f.prediction(m, p1=p1, lo=p1 - .05, hi=p1 + .05)
    pr.as_of = m.scheduled_at - timedelta(minutes=30)
    m.status, m.winner_id = "FINISHED", (m.player1_id if p1_wins else m.player2_id)
    db.flush()
    return m


def test_live_pairs_use_favourite_side(f, db):
    _finished(f, db, 0.3, False)            # p2 is the 70% favourite and won
    assert live_pairs(db, utcnow() - timedelta(days=1)) == [(0.7, True)]


def test_daily_check_runs_once_logs_and_alerts_on_change(f, db, monkeypatch):
    monkeypatch.setattr("ttq.services.alerts._send_telegram", lambda t, b: True)
    set_setting(db, "alerts", {"picks_min_prob": 0.58})
    for i in range(200):
        _finished(f, db, 0.59, i % 2 == 0)  # 59% favourites winning 50%: over-confident
    for i in range(200):
        _finished(f, db, 0.66, i % 100 < 67)
    r = daily_self_check(db)
    assert r["ran"] and r["threshold_after"] == 0.60
    assert get_setting(db, "alerts")["picks_min_prob"] == 0.60
    assert db.query(Alert).filter_by(kind="learning").count() == 1
    assert daily_self_check(db)["ran"] is False
    assert len(db.get(AppSetting, "learning_log").value["entries"]) == 1


def test_prune_keeps_latest_and_backtest(f, db):
    a, b = f.player(), f.player()
    m = f.match(a, b, at=utcnow() + timedelta(hours=5))
    old = utcnow() - timedelta(days=5)
    for k in range(3):
        pr = f.prediction(m, p1=0.6 + k / 100)
        pr.created_at, pr.as_of = old, old + timedelta(minutes=k)
    bt = f.prediction(m); bt.is_backtest = True; bt.created_at = old
    db.flush()
    r = prune(db)
    left = db.query(Prediction).filter_by(match_id=m.id).all()
    assert r["predictions_deleted"] == 2 and len(left) == 2
    assert any(p.is_backtest for p in left) and any(abs(p.p1_win - 0.62) < 1e-9 for p in left)


def test_prune_slims_finished_match_features(f, db):
    from datetime import timedelta
    from ttq.core.timeutil import utcnow
    from ttq.models import Prediction
    a, b = f.player(), f.player()
    m = f.match(a, b, at=utcnow() - timedelta(days=1))
    m.status = "FINISHED"
    f.prediction(m, p1=0.6, lo=0.55, hi=0.65)
    pr = db.query(Prediction).filter_by(match_id=m.id).one()
    pr.features = {"x": 1}
    db.flush()
    assert prune(db)["predictions_slimmed"] == 1
    db.refresh(pr)
    assert pr.features == {} and pr.p1_win == 0.6
