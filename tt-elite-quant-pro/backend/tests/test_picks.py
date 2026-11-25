"""Conditional picks: strongest matches only, one side, minimum Hard Rock price, capped per day."""
from datetime import datetime, timedelta, timezone

from ttq.core.timeutil import utcnow
from ttq.models import Alert, ModelVersion
from ttq.odds.math import american_to_decimal
from ttq.services.app_settings import get_filters, set_setting
from ttq.services.messages import conditional_pick_text
from ttq.services.targets import build_picks, picks_job, side_target


def _m(f, db, minutes=30, p1=0.66, width=0.08, dq="HIGH", demo=False, names=None):
    a, b = f.player(names[0] if names else None, demo=demo), f.player(names[1] if names else None, demo=demo)
    m = f.match(a, b, at=utcnow() + timedelta(minutes=minutes), demo=demo)
    f.prediction(m, p1=p1, lo=p1 - width / 2, hi=p1 + width / 2, dq=dq, demo=demo)
    return m


def _setup(db):
    set_setting(db, "filters", {"min_player_matches": 0})


def test_only_strong_matches_in_window(f, db):
    _setup(db)
    good = _m(f, db, 30)
    _m(f, db, 5)                     # too soon
    _m(f, db, 90)                    # too far
    _m(f, db, 30, dq="LOW")          # low-quality data
    _m(f, db, 30, p1=0.55)           # under 60%: model over-confident on close matches
    _m(f, db, 30, width=0.30)        # too uncertain
    _m(f, db, 30, demo=True)         # demo never sent
    picks = build_picks(db)
    assert [p["match"].id for p in picks] == [good.id]
    assert build_picks(db) == []     # never repeats


def test_one_side_and_conservative_minimum(f, db):
    _setup(db)
    _m(f, db, 30, p1=0.66, width=0.08)
    pk = build_picks(db)[0]
    F = get_filters(db, False)
    p = pk["p"]
    lo = pk["pred"].p1_ci_low if pk["side"] == "p1" else 1 - pk["pred"].p1_ci_high
    assert american_to_decimal(pk["min_american"]) >= side_target(p, lo, F) - 1e-9
    assert pk["side"] in ("p1", "p2")


def test_daily_cap_when_set(f, db):
    _setup(db)
    set_setting(db, "alerts", {"picks_max_per_day": 3})
    for i in range(6):
        _m(f, db, 20 + i)
    assert len(build_picks(db)) == 3
    assert build_picks(db) == []


def test_toggle_off(f, db):
    _setup(db)
    _m(f, db, 30)
    set_setting(db, "alerts", {"conditional_picks": False})
    assert build_picks(db) == []


def test_message_layout(f, db):
    _setup(db)
    m = _m(f, db, 30, names=("Mateusz Baran", "Miroslaw Lewczuk"))
    m.scheduled_at = datetime(2026, 11, 24, 0, 10, tzinfo=timezone.utc)
    mv = ModelVersion(name="dyn_elo", kind="x", version="20261123162333", status="CHAMPION",
                      trained_at=datetime(2026, 11, 23, tzinfo=timezone.utc))
    db.add(mv); db.flush()
    from ttq.models import Prediction
    pred = db.query(Prediction).filter_by(match_id=m.id).one(); pred.model_version_id = mv.id
    title, body = conditional_pick_text(db, m, pred, "p1", 0.588, 135)
    lines = body.splitlines()
    assert title == "New Bet Recommendation"
    assert lines[:3] == ["Mateusz Baran vs Miroslaw Lewczuk", "Pick: Mateusz Baran (HOME)",
                         "Odds: 2.35 (+135) | Prob: 58.8% | EV: 38.2%"]
    assert lines[4] == "Match: Nov 23, 7:10 PM ET"
    assert lines[5] == "Model: dyn_elo_20261123162333 (2026-11-23)"
    assert lines[6].startswith("Ruleset: EV>=")
    assert lines[-1] == "Bet only if Hard Rock odds >= +135 (2.35)"


def test_job_sends_every_pick(f, db, monkeypatch):
    _setup(db)
    for i in range(3):
        _m(f, db, 20 + i)
    sent = []
    monkeypatch.setattr("ttq.services.alerts._send_telegram", lambda t, b: sent.append(t) or True)
    monkeypatch.setattr("ttq.services.alerts._send_email", lambda t, b: False)
    # Hard Rock pays +105 on a 66% favourite while the other books price it ~60%: a misplaced line
    monkeypatch.setattr("ttq.providers.oddspapi.market_check",
                        lambda *a, **k: {"status": "ok", "books": 30, "hard_rock": (1.70, 2.20), "consensus_p1": 0.62})
    r = picks_job(db)
    assert r["sent"] == 3 and len(sent) == 3
    assert db.query(Alert).filter_by(kind="pick").count() == 3


def test_no_market_data_means_no_pick(f, db, monkeypatch):
    _setup(db)
    _m(f, db, 30)
    monkeypatch.setattr("ttq.providers.oddspapi.market_check", lambda *a, **k: {"status": "no_budget"})
    r = picks_job(db)
    assert r["sent"] == 0 and "no live market data" in r["skipped_by_market"][0]["reason"]


def test_no_daily_cap_by_default(f, db):
    _setup(db)
    for i in range(14):
        _m(f, db, 15 + i)
    assert len(build_picks(db)) == 14


def test_status_reports_missing_pieces(db):
    db.commit()
    from ttq.services.status import system_status
    r = system_status()
    names = {k for k, _ in r["checks"]}
    assert {"match history", "trained model", "Telegram configured", "scheduler (worker)"} <= names
    assert r["ready"] is False      # empty test database: nothing in place yet


def test_rejection_reasons_are_counted(f, db):
    _setup(db)
    _m(f, db, 30)                    # passes
    _m(f, db, 30, dq="LOW")
    _m(f, db, 30, width=0.30)
    _m(f, db, 30, p1=0.45)           # favourite is p2 at 55%: under the minimum
    st = {}
    picks = build_picks(db, stats=st)
    assert len(picks) == 1
    assert st["in_window"] == 4 and st["low_quality"] == 1 and st["too_uncertain"] == 1 and st["below_min_prob"] == 1


def test_message_shows_real_hard_rock_and_market(f, db):
    _setup(db)
    m = _m(f, db, 30, names=("Mateusz Baran", "Miroslaw Lewczuk"))
    from ttq.models import Prediction
    pred = db.query(Prediction).filter_by(match_id=m.id).one()
    info = {"hr_american": -125, "hr_decimal": 1.8, "consensus_p": 0.58, "books": 36, "market_ev_at_hr": 0.044}
    _, body = conditional_pick_text(db, m, pred, "p1", 0.62, -135, info)
    lines = body.splitlines()
    assert lines[2] == "Odds: 1.80 (-125) Hard Rock now | Prob: 62.0% | EV: 11.6%"
    assert "Market fair: -138 (58.0%, 36 books) | Edge vs market: +4.4%" in body
    assert lines[-1] == "Bet only if Hard Rock odds >= -135 (1.74)"


def test_market_rejection_is_not_sent_but_logged(f, db, monkeypatch):
    _setup(db)
    _m(f, db, 30)
    monkeypatch.setattr("ttq.providers.oddspapi.market_check",
                        lambda *a, **k: {"status": "ok", "books": 30, "hard_rock": (1.3, 3.5), "consensus_p1": 0.66})
    sent = []
    monkeypatch.setattr("ttq.services.alerts._send_telegram", lambda t, b: sent.append(t) or True)
    r = picks_job(db)
    assert r["sent"] == 0 and len(r["skipped_by_market"]) == 1 and not sent
    from ttq.models import AppSetting
    assert db.get(AppSetting, "market_checks").value["items"][-1]["sent"] is False
