import pytest
from ttq.sim.tt import *


@pytest.mark.parametrize("p", [0.05, 0.3, 0.5, 0.64, 0.9])
def test_scorelines_sum_to_one_and_consistent(p):
    m = full_match_model(p)
    assert sum(m["scorelines"].values()) == pytest.approx(1, abs=1e-9)
    assert set(m["scorelines"]) == {"3-0", "3-1", "3-2", "0-3", "1-3", "2-3"}
    win = sum(v for k, v in m["scorelines"].items() if k.startswith("3"))
    assert win == pytest.approx(p, abs=1e-6)
    assert sum(m["totals"].values()) == pytest.approx(1, abs=1e-6)
    assert all(0 <= v <= 1 for v in m["scorelines"].values())


def test_game_rules_eleven_win_by_two():
    d = game_score_distribution(0.5)
    for (a, b) in d:
        assert max(a, b) >= 11 and abs(a - b) >= 2
        if max(a, b) > 11:
            assert abs(a - b) == 2  # deuce games end exactly two clear
    assert game_win_prob(0.5) == pytest.approx(0.5)


def test_serve_rotation_deuce():
    from ttq.sim.tt import _server
    assert [_server(a, 0, 1) for a in range(4)] == [1, 1, 2, 2]
    assert _server(10, 10, 1) != _server(11, 10, 1)  # alternates every point at deuce


def test_symmetry_and_monotonicity():
    assert match_win_from_game(0.5) == pytest.approx(0.5)
    assert match_win_from_game(0.6) > match_win_from_game(0.55)
    assert game_prob_from_match(match_win_from_game(0.58)) == pytest.approx(0.58, abs=1e-6)


def test_live_probability_bounds():
    assert live_match_win_prob(0.5, (3, 0), (0, 0)) == 1.0
    assert live_match_win_prob(0.5, (0, 3), (0, 0)) == 0.0
    assert live_match_win_prob(0.5, (0, 0), (0, 0)) == pytest.approx(0.5, abs=1e-6)
    assert live_match_win_prob(0.5, (2, 0), (10, 2)) > 0.9


def test_handicaps():
    m = full_match_model(0.7)
    sl = m["scorelines"]
    assert prob_set_handicap(sl, -1.5) == pytest.approx(sl["3-0"] + sl["3-1"])
    assert prob_set_handicap(sl, 2.5) == pytest.approx(1 - sl["0-3"])
