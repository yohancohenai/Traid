import pytest
from ttq.odds.math import *


def test_ev_known_case_from_spec():
    assert expected_value(0.64, 1.75) == pytest.approx(0.12)


@pytest.mark.parametrize("am,dec", [(-110, 1.9090909), (+150, 2.5), (-200, 1.5), (+100, 2.0), (-100, 2.0), (+1000, 11.0)])
def test_american_to_decimal(am, dec):
    assert american_to_decimal(am) == pytest.approx(dec, rel=1e-6)


def test_roundtrip_and_invalid():
    for am in (-250, -110, 120, 300):
        assert decimal_to_american(american_to_decimal(am)) == am
    with pytest.raises(ValueError):
        american_to_decimal(50)
    with pytest.raises(ValueError):
        implied_prob(1.0)


def test_novig_methods_sum_to_one_and_remove_margin():
    d = [1.8, 2.0]
    assert overround(d) == pytest.approx(1 / 1.8 + 0.5 - 1)
    for fn in (no_vig_multiplicative, no_vig_power, no_vig_shin):
        p = fn(d)
        assert sum(p) == pytest.approx(1, abs=1e-9)
        assert all(0 < x < 1 for x in p)
        assert p[0] > p[1]


def test_break_even_fair_and_kelly():
    assert break_even_prob(2.0) == 0.5
    assert fair_decimal(0.25) == 4
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.2)
    assert kelly_fraction(0.4, 2.0) == 0.0


def test_payouts():
    assert profit_for_result(10, 1.91, "WON") == 9.1
    assert profit_for_result(10, 1.91, "LOST") == -10
    assert profit_for_result(10, 1.91, "PUSH") == 0
    assert profit_for_result(10, 1.91, "VOID") == 0
    with pytest.raises(ValueError):
        profit_for_result(10, 1.91, "PENDING")


def test_clv():
    assert clv(2.1, 2.0) == pytest.approx(0.05)
