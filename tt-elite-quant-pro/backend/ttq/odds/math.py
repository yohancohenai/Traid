"""Odds, implied probability, vig removal, EV and Kelly. Pure functions, fully tested.

EV is *estimated* EV: conditional on the model probability being accurate.
"""
from __future__ import annotations

import math
from scipy.optimize import brentq


def american_to_decimal(american: int | float) -> float:
    a = float(american)
    if -100 < a < 100:
        raise ValueError("American odds must be <= -100 or >= +100")
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def decimal_to_american(decimal_odds: float) -> int:
    if decimal_odds <= 1:
        raise ValueError("Decimal odds must be > 1")
    if decimal_odds >= 2:
        return int(round((decimal_odds - 1) * 100))
    return int(round(-100 / (decimal_odds - 1)))


def implied_prob(decimal_odds: float) -> float:
    if decimal_odds <= 1:
        raise ValueError("Decimal odds must be > 1")
    return 1.0 / decimal_odds


def overround(decimals: list[float]) -> float:
    """Sum of implied probabilities minus one (bookmaker margin)."""
    return sum(1 / d for d in decimals) - 1


def no_vig_multiplicative(decimals: list[float]) -> list[float]:
    imp = [1 / d for d in decimals]
    s = sum(imp)
    return [p / s for p in imp]


def no_vig_power(decimals: list[float]) -> list[float]:
    """Power method: find k such that sum(imp^k) = 1. Handles favourite-longshot bias better."""
    imp = [1 / d for d in decimals]
    if abs(sum(imp) - 1) < 1e-12:
        return imp
    k = brentq(lambda k: sum(p ** k for p in imp) - 1, 0.2, 5.0)
    return [p ** k for p in imp]


def no_vig_shin(decimals: list[float]) -> list[float]:
    """Shin (1993) method for insider-trading-adjusted fair probabilities."""
    imp = [1 / d for d in decimals]
    b = sum(imp)
    if abs(b - 1) < 1e-12:
        return imp
    n = len(imp)

    def probs(z):
        return [(math.sqrt(z * z + 4 * (1 - z) * p * p / b) - z) / (2 * (1 - z)) for p in imp]

    z = brentq(lambda z: sum(probs(z)) - 1, 0.0, 0.4)
    return probs(z)


def fair_decimal(prob: float) -> float:
    if not 0 < prob < 1:
        raise ValueError("probability must be in (0,1)")
    return 1 / prob


def expected_value(prob: float, decimal_odds: float) -> float:
    """EV per unit staked = p * d - 1."""
    if not 0 <= prob <= 1:
        raise ValueError("probability must be in [0,1]")
    return prob * decimal_odds - 1


def break_even_prob(decimal_odds: float) -> float:
    return 1 / decimal_odds


def kelly_fraction(prob: float, decimal_odds: float) -> float:
    """Full-Kelly fraction of bankroll; 0 if no positive edge."""
    b = decimal_odds - 1
    f = (b * prob - (1 - prob)) / b
    return max(0.0, f)


def profit_for_result(stake: float, decimal_odds: float, result: str) -> float:
    """Net profit for a settled single bet. result in WON | LOST | PUSH | VOID."""
    r = result.upper()
    if r == "WON":
        return round(stake * (decimal_odds - 1), 2)
    if r == "LOST":
        return round(-stake, 2)
    if r in ("PUSH", "VOID"):
        return 0.0
    raise ValueError(f"unsettled result {result}")


def ev_sensitivity(prob: float, decimal_odds: float, shifts=(-0.05, -0.03, -0.01, 0, 0.01, 0.03)) -> list[dict]:
    out = []
    for s in shifts:
        p = min(max(prob + s, 0.0), 1.0)
        out.append({"prob_shift": s, "prob": p, "ev": expected_value(p, decimal_odds)})
    return out


def clv(accepted_decimal: float, closing_decimal: float) -> float:
    """Closing-line value: positive when you beat the closing price."""
    return accepted_decimal / closing_decimal - 1
