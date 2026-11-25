from datetime import timedelta

from ttq.core.timeutil import utcnow
from ttq.providers import oddspapi as op
from ttq.services.targets import decide_with_market


def _book(a, b, **kw):
    return {"markets": {"251": {"outcomes": {"251": {"players": {"0": {"price": a}}},
                                              "252": {"players": {"0": {"price": b}}}}}}, **kw}


BOARD = {"bookmakerOdds": {"hardrockbet": _book(1.625, 2.15), "draftkings": _book(1.741, 1.952),
                           "bet365": _book(1.70, 2.05), "1xbet": _book(1.72, 2.0), "bet365.es": _book(1.70, 2.05),
                           "dead": _book(1.5, 2.5, suspended=True), "demo": _book(9, 9)}}


def test_names_match_either_order_and_comma_format():
    st = utcnow() + timedelta(minutes=30)
    fx = [{"fixtureId": "x1", "startTime": st.isoformat().replace("+00:00", "Z"),
           "participant1Name": "Pyrek, Dawid", "participant2Name": "Brunner, Marian"}]
    f, flipped = op.find_fixture(fx, "Marian Brunner", "Dawid Pyrek", st)
    assert f["fixtureId"] == "x1" and flipped is True
    assert op.find_fixture(fx, "Marian Brunner", "Dawid Pyrek", st + timedelta(hours=2)) is None


def test_board_parsing_skips_suspended_and_test_feeds_and_dedupes():
    pairs = op.winner_pairs(BOARD)
    assert set(pairs) == {"hardrockbet", "draftkings", "bet365", "1xbet", "bet365.es"}
    c = op.consensus_p1(pairs)                      # 4 distinct pairs
    assert 0.53 < c < 0.57


def test_budget_caps_and_counts_every_request(db, monkeypatch):
    monkeypatch.setenv("ODDSPAPI_KEY", "k")
    monkeypatch.setenv("ODDSPAPI_DAILY_CAP", "2")
    calls = []
    class R:
        status_code = 200
        def json(self): return []
    monkeypatch.setattr(op.httpx, "get", lambda *a, **k: calls.append(1) or R())
    now = utcnow()
    assert op.can_spend(db, 1, now)
    op._request(db, "fixtures", now); op._request(db, "fixtures", now)
    assert op.usage(db, now)["today"] == 2 and not op.can_spend(db, 1, now)


def test_no_key_means_no_calls(db, monkeypatch):
    monkeypatch.delenv("ODDSPAPI_KEY", raising=False)
    assert op.market_check(db, "A B", "C D", utcnow() + timedelta(minutes=30)) is None


def test_started_match_is_never_requested(db, monkeypatch):
    monkeypatch.setenv("ODDSPAPI_KEY", "k")
    monkeypatch.setattr(op.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    assert op.market_check(db, "A B", "C D", utcnow() - timedelta(minutes=1)) is None


def test_market_check_orients_to_our_player1(db, monkeypatch):
    monkeypatch.setenv("ODDSPAPI_KEY", "k")
    st = utcnow() + timedelta(minutes=30)
    fx = [{"fixtureId": "x1", "startTime": st.isoformat().replace("+00:00", "Z"), "statusName": "Pre-Game",
           "participant1Name": "Pyrek, Dawid", "participant2Name": "Brunner, Marian"}]
    board = {"bookmakerOdds": {k: _book(b, a) for k, (a, b) in op.winner_pairs(BOARD).items()}}  # Pyrek listed first
    class R:
        def __init__(self, data): self.data, self.status_code = data, 200
        def json(self): return self.data
    monkeypatch.setattr(op.httpx, "get", lambda url, **k: R(fx if url.endswith("fixtures") else board))
    mk = op.market_check(db, "Marian Brunner", "Dawid Pyrek", st)
    assert mk["status"] == "ok" and mk["hard_rock"] == (1.625, 2.15) and mk["consensus_p1"] > 0.5
    assert op.usage(db)["today"] == 2


def test_decision_rules():
    ok = {"status": "ok", "books": 36, "hard_rock": (1.80, 2.0), "consensus_p1": 0.56}
    send, info = decide_with_market("p1", 0.62, -135, ok)        # HR -125 beats -135 minimum, market agrees
    assert send and info["hr_american"] == -125 and info["market_ev_at_hr"] > 0
    send, info = decide_with_market("p1", 0.62, -135, {**ok, "hard_rock": (1.625, 2.15)})
    assert not send and "below the minimum" in info["reason"]
    send, info = decide_with_market("p1", 0.70, -135, {**ok, "hard_rock": (1.80, 2.0), "consensus_p1": 0.50})
    assert not send and "disagree" in info["reason"]
    assert decide_with_market("p1", 0.62, -135, None)[0] is True          # no market data: pick goes out as before
    assert decide_with_market("p1", 0.62, -135, {**ok, "hard_rock": None})[0] is True


def test_hard_rock_outlier_is_skipped():
    mk = {"status": "ok", "books": 30, "hard_rock": (1.25, 4.0), "consensus_p1": 0.60}   # HR ~76% vs market 60%
    send, info = decide_with_market("p2", 0.62, -135, {**mk})
    assert not send and "far from every other book" in info["reason"]


def test_units_flat_until_clv_proven(db):
    from ttq.services.summary import log_picks
    from ttq.services.targets import suggested_units
    assert suggested_units(db, 0.05, 1.8) == 1.0
    log_picks(db, [{"match_id": 10_000 + i, "side": "p1", "p": 0.6, "min_american": -135} for i in range(100)])
    from ttq.models import AppSetting
    row = db.get(AppSetting, "picks_log")
    row.value = {k: {**v, "clv": 0.03} for k, v in row.value.items()}
    db.flush()
    u = suggested_units(db, 0.05, 1.8)
    assert u == 0.8                                   # quarter-Kelly: 0.05 edge at 1.80 -> 0.8 units
    assert suggested_units(db, -0.01, 1.8) == 1.0


def test_closing_line_records_clv(f, db, monkeypatch):
    from ttq.services.summary import log_picks
    from ttq.services.targets import closing_lines
    monkeypatch.setenv("ODDSPAPI_KEY", "k")
    a, b = f.player(), f.player()
    m = f.match(a, b, at=utcnow() + timedelta(minutes=4))
    log_picks(db, [{"match_id": m.id, "side": "p1", "p": 0.62, "min_american": -135, "fixture_id": "x9",
                    "flipped": False, "hr_auto_dec": 1.80}])
    monkeypatch.setattr(op, "board_by_fixture", lambda *a, **k: {"status": "ok", "books": 30,
                                                                 "hard_rock": (1.70, 2.10), "consensus_p1": 0.58})
    assert closing_lines(db)["closed"] == 1
    from ttq.models import AppSetting
    pk = db.get(AppSetting, "picks_log").value[str(m.id)]
    assert pk["close_checked"] and abs(pk["clv"] - (1.80 * 0.58 - 1)) < 1e-4
    assert closing_lines(db)["closed"] == 0          # never re-checked (no double credit use)


def test_set_market_calibration_values():
    from ttq.services.set_markets import fav_minus_1_5
    assert 0.36 < fav_minus_1_5(0.6) < 0.42 and fav_minus_1_5(0.75) > fav_minus_1_5(0.6)


def test_market_must_not_say_negative_ev():
    mk = {"status": "ok", "books": 30, "hard_rock": (1.76, 2.05), "consensus_p1": 0.56}   # 0.56*1.76 = 0.986
    send, info = decide_with_market("p1", 0.64, -135, mk)
    assert not send and info["market_ev_at_hr"] < 0
