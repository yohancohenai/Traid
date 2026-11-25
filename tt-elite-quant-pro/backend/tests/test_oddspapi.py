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
