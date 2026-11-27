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


class _Pred:
    def __init__(self, p1, lo, hi):
        self.p1_win, self.p1_ci_low, self.p1_ci_high = p1, lo, hi


def test_decision_rules():
    pred = _Pred(0.64, 0.60, 0.68)
    ok = {"status": "ok", "books": 36, "hard_rock": (1.80, 2.0), "consensus_p1": 0.58}
    send, info = decide_with_market("p1", 0.64, -135, ok, pred)            # HR -125, market fair 58% -> +4.4%
    assert send and info["side"] == "p1" and info["hr_american"] == -125 and info["market_ev_at_hr"] > 0
    send, info = decide_with_market("p1", 0.64, -135, {**ok, "hard_rock": (1.50, 2.5), "consensus_p1": 0.64}, pred)
    assert not send                                                         # -200 but market says -4%
    assert decide_with_market("p1", 0.64, -135, None, pred)[0] is False     # no market -> no pick
    assert decide_with_market("p1", 0.64, -135, {**ok, "hard_rock": None, "refs": {}}, pred)[0] is False


def test_heavy_favourite_outside_band_is_never_sent():
    pred = _Pred(0.88, 0.85, 0.91)
    mk = {"status": "ok", "books": 30, "hard_rock": (1.20, 4.5), "consensus_p1": 0.82}   # -500
    send, info = decide_with_market("p1", 0.88, -550, mk, pred)
    assert not send and "outside -200..+200" in info["reason"]


def test_underdog_can_be_the_misplaced_line():
    pred = _Pred(0.62, 0.58, 0.66)       # model: underdog 38% (low end 34%)
    mk = {"status": "ok", "books": 30, "hard_rock": (1.40, 3.0), "consensus_p1": 0.64}  # dog +200, market dog 36%
    send, info = decide_with_market("p1", 0.62, -135, mk, pred)
    assert send and info["side"] == "p2" and info["hr_american"] == 200



def test_hard_rock_outlier_is_skipped():
    mk = {"status": "ok", "books": 30, "hard_rock": (1.25, 4.0), "consensus_p1": 0.60}   # HR ~76% vs market 60%
    send, info = decide_with_market("p2", 0.62, -135, {**mk}, _Pred(0.38, 0.34, 0.42))
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
    monkeypatch.setenv("ODDSPAPI_CLOSING", "1")
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
    send, info = decide_with_market("p1", 0.64, -135, mk, _Pred(0.64, 0.60, 0.68))
    assert not send


def test_credits_are_paced_through_the_day():
    from datetime import datetime, timezone
    at = lambda h: datetime(2026, 11, 25, h, tzinfo=timezone.utc)
    assert op.paced_allowance(8, at(0)) == 2 and op.paced_allowance(8, at(9)) == 5 and op.paced_allowance(8, at(23)) == 8


def test_cached_fixture_list_costs_nothing(db, monkeypatch):
    monkeypatch.setenv("ODDSPAPI_KEY", "k")
    st = utcnow() + timedelta(minutes=30)
    op._put_row(db, "oddspapi_fixtures", {"fixtures": [{"fixtureId": "x1", "startTime": st.isoformat(),
                                                        "participant1Name": "Brunner, Marian",
                                                        "participant2Name": "Pyrek, Dawid"}],
                                          "fetched_at": (utcnow() - timedelta(hours=10)).isoformat(), "until": "2099"})
    urls = []
    class R:
        status_code = 200
        def json(self): return {"bookmakerOdds": {}}
    monkeypatch.setattr(op.httpx, "get", lambda url, **k: urls.append(url) or R())
    monkeypatch.setattr(op, "paced_allowance", lambda cap, now: cap)
    op.market_check(db, "Marian Brunner", "Dawid Pyrek", st)
    assert len(urls) == 1 and urls[0].endswith("/odds")          # no list refresh on a cache hit



def test_bulk_sweep_covers_all_matches_for_three_credits(db, monkeypatch):
    monkeypatch.setenv("ODDSPAPI_KEY", "k")
    monkeypatch.setenv("ODDSPAPI_REF_BOOKS", "draftkings,bet365")
    monkeypatch.setattr(op, "paced_allowance", lambda cap, now: cap)
    monkeypatch.setattr("time.sleep", lambda s: None)
    st = (utcnow() + timedelta(minutes=40)).isoformat()
    fixtures = [{"fixtureId": f"f{i}", "startTime": st, "participant1Name": f"Surname{i}, First{i}",
                 "participant2Name": f"Other{i}, Name{i}", "statusName": "Pre-Game"} for i in range(5)]
    prices = {"hardrockbet": (1.80, 2.00), "draftkings": (1.70, 2.15), "bet365": (1.72, 2.10)}
    calls = []
    class R:
        def __init__(self, d): self.d, self.status_code = d, 200
        def json(self): return self.d
    def get(url, params=None, **k):
        calls.append(url.rsplit("/", 1)[1])
        if url.endswith("/fixtures"):
            return R(fixtures)
        slug = params["bookmaker"]
        return R([{"fixtureId": f"f{i}", "startTime": st, "statusId": 0,
                   "bookmakerOdds": {slug: _book(*prices[slug])}} for i in range(5)])
    monkeypatch.setattr(op.httpx, "get", get)
    r = op.sweep(db)
    assert r["swept"] and r["matches"] == 5 and r["with_hard_rock"] == 5 and r["credits"] == 4   # list + 3 books
    assert calls.count("odds-by-tournaments") == 3 and op.usage(db)["today"] == 4
    assert op.sweep(db)["why"] == "not due"                                  # no double spending
    mk = op.from_sweep(db, "First3 Surname3", "Name3 Other3", utcnow() + timedelta(minutes=40))
    assert mk["status"] == "ok" and mk["hard_rock"] == (1.80, 2.00) and mk["books"] == 2
    assert 0.55 < mk["consensus_p1"] < 0.57
    flipped = op.from_sweep(db, "Name3 Other3", "First3 Surname3", utcnow() + timedelta(minutes=40))
    assert flipped["hard_rock"] == (2.00, 1.80)


def test_sweep_waits_for_budget(db, monkeypatch):
    monkeypatch.setenv("ODDSPAPI_KEY", "k")
    monkeypatch.setattr(op, "paced_allowance", lambda cap, now: 2)
    monkeypatch.setattr(op.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    assert op.sweep(db)["why"].startswith("budget")


def test_sweep_stays_usable_until_next_one_and_status(db, monkeypatch):
    monkeypatch.setenv("ODDSPAPI_FRESH_MINUTES", "435")
    now = utcnow()
    op._put_row(db, "oddspapi_sweep", {"fetched_at": (now - timedelta(hours=5)).isoformat(), "books": [],
                                       "boards": {"f1": {"start": now.isoformat(), "p1": "A B", "p2": "C D",
                                                         "books": {"hardrockbet": [1.8, 2.0], "draftkings": [1.7, 2.1]}}}})
    assert op.from_sweep(db, "A B", "C D", now)["status"] == "ok"           # 5 h old, next sweep not due yet
    op._put_row(db, "oddspapi_sweep", {**op.latest_sweep(db), "fetched_at": (now - timedelta(hours=8)).isoformat()})
    assert op.from_sweep(db, "A B", "C D", now)["status"] == "no fresh sweep"
    st = op.sweep_status(db, now)
    assert st["matches"] == 1 and st["priced_by"] == {"hardrockbet": 1, "draftkings": 1} and st["last_sweep_min_ago"] == 480


def test_no_hard_rock_price_falls_back_to_market_minimum(monkeypatch):
    monkeypatch.setenv("ODDSPAPI_NO_HR_PICKS", "1")
    from ttq.odds.math import american_to_decimal
    pred = _Pred(0.38, 0.33, 0.43)                       # model: p2 62%
    # DraftKings -200 / +165 -> market p2 ~64%; blend ~63% -> need >= 1.02/0.63 = 1.62 (about -160)
    mk = {"status": "ok", "books": 1, "hard_rock": None, "consensus_p1": 0.36, "refs": {"draftkings": (2.65, 1.50)}}
    send, info = decide_with_market("p2", 0.62, -135, mk, pred)
    assert send and info["side"] == "p2" and info["hr_listed"] is False
    assert american_to_decimal(info["min_american"]) >= 1.02 / 0.63 and info["min_decimal"] <= 1.50 * 1.10
    # market makes the other player the favourite -> no pick
    send, info = decide_with_market("p2", 0.62, -135, {**mk, "consensus_p1": 0.55, "refs": {"draftkings": (1.75, 2.1)}}, pred)
    assert not send
    # -500 favourite never qualifies
    send, _ = decide_with_market("p1", 0.88, -550, {**mk, "consensus_p1": 0.85, "refs": {"draftkings": (1.18, 4.8)}},
                                 _Pred(0.88, 0.84, 0.92))
    assert not send


def test_need_triggers_early_sweep(db, monkeypatch):
    monkeypatch.setenv("ODDSPAPI_KEY", "k")
    monkeypatch.setenv("ODDSPAPI_SWEEP_MINUTES", "300")
    now = utcnow()
    op._put_row(db, "oddspapi_sweep", {"fetched_at": (now - timedelta(minutes=30)).isoformat(), "boards": {}, "books": []})
    assert op.sweep(db, now, need=True)["why"] == "not due"                 # 30 min < 40 min gap
    op._put_row(db, "oddspapi_sweep", {"fetched_at": (now - timedelta(minutes=50)).isoformat(), "boards": {}, "books": []})
    assert op.sweep(db, now)["why"] == "not due"                            # background schedule not due
    monkeypatch.setattr(op, "can_spend", lambda db, cost, now: False)
    assert op.sweep(db, now, need=True)["why"].startswith("budget")         # a candidate needs it: due, budget decides
