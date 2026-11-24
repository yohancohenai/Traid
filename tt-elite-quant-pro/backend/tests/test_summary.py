from datetime import datetime, timedelta, timezone

from ttq.core.timeutil import utcnow
from ttq.models import Alert
from ttq.services.summary import grade, log_picks, weekly_summary_job


def _finished(f, db, winner_is_p1, days_ago=3):
    a, b = f.player(), f.player()
    m = f.match(a, b, at=utcnow() - timedelta(days=days_ago))
    m.status = "FINISHED"
    m.winner_id = m.player1_id if winner_is_p1 else m.player2_id
    db.flush()
    return m


def test_grading_at_minimum_price(f, db):
    now = utcnow()
    w, l = _finished(f, db, True), _finished(f, db, True)
    log_picks(db, [{"match_id": w.id, "side": "p1", "p": 0.6, "min_american": 135},
                   {"match_id": l.id, "side": "p2", "p": 0.5, "min_american": 120}], now=now - timedelta(days=3))
    r = grade(db, now - timedelta(days=7), now)
    assert (r["wins"], r["losses"]) == (1, 1)
    assert r["units"] == round(1.35 - 1, 2)
    assert abs(r["expected_win_rate"] - 0.55) < 1e-9


def test_pending_and_void_not_graded(f, db):
    now = utcnow()
    a, b = f.player(), f.player()
    sched = f.match(a, b, at=now + timedelta(hours=1))
    void = _finished(f, db, True); void.status = "CANCELLED"; void.winner_id = None
    log_picks(db, [{"match_id": sched.id, "side": "p1", "p": 0.6, "min_american": 110},
                   {"match_id": void.id, "side": "p1", "p": 0.6, "min_american": 110}], now=now - timedelta(hours=1))
    r = grade(db, now - timedelta(days=1), now + timedelta(minutes=1))
    assert (r["pending"], r["voids"], r["wins"] + r["losses"]) == (1, 1, 0)


def test_sent_once_per_week_on_monday(f, db, monkeypatch):
    sent = []
    monkeypatch.setattr("ttq.services.alerts._send_telegram", lambda t, b: sent.append(b) or True)
    monkeypatch.setattr("ttq.services.alerts._send_email", lambda t, b: False)
    monday = datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc)    # 10 AM ET
    assert weekly_summary_job(db, now=monday - timedelta(days=1))["sent"] is False   # Sunday
    assert weekly_summary_job(db, now=monday)["sent"] is True
    assert weekly_summary_job(db, now=monday + timedelta(minutes=30))["sent"] is False
    assert len(sent) == 1 and "Week Nov 23 - Nov 29" in sent[0]
    assert db.query(Alert).filter_by(kind="weekly_summary").count() == 1
