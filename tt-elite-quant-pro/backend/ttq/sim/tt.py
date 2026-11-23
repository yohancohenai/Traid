"""Exact table tennis probability engine (dynamic programming, no Monte Carlo noise).

Rules modelled
- A game (set) is won by the first player to 11 points with a 2-point margin.
- Service alternates every 2 points; from 10-10 (deuce) every point.
- Matches are best-of-N games (TT Elite Series: best of five).

Two parametrisations:
- iid point model: P(A wins point) = p regardless of server.
- serve-aware model: pa = P(A wins point | A serves), pb = P(A wins point | B serves).
  Only use this when verified service-level data exists.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import product
from scipy.optimize import brentq

MAX_PTS = 40  # cap for deuce recursion; residual mass beyond is < 1e-12 for realistic p


def _server(a: int, b: int, first_server: int) -> int:
    """Return 1 if player A serves at score (a,b) given who served first (1=A, 2=B)."""
    n = a + b
    if a >= 10 and b >= 10:
        k = 10 + (n - 20)  # serve changes every point at deuce
    else:
        k = n // 2
    same = (k % 2 == 0)
    return first_server if same else (3 - first_server)


def game_score_distribution(pa: float, pb: float | None = None, first_server: int = 1,
                            start: tuple[int, int] = (0, 0)) -> dict[tuple[int, int], float]:
    """Distribution over final game scores (a, b) from a starting score.
    pa: P(A wins point when A serves); pb: when B serves (defaults to pa)."""
    if pb is None:
        pb = pa
    dist: dict[tuple[int, int], float] = {}
    frontier = {start: 1.0}
    while frontier:
        nxt: dict[tuple[int, int], float] = {}
        for (a, b), pr in frontier.items():
            if pr < 1e-15:
                continue
            if (a >= 11 or b >= 11) and abs(a - b) >= 2:
                dist[(a, b)] = dist.get((a, b), 0) + pr
                continue
            if a + b >= 2 * MAX_PTS:
                continue
            p = pa if _server(a, b, first_server) == 1 else pb
            nxt[(a + 1, b)] = nxt.get((a + 1, b), 0) + pr * p
            nxt[(a, b + 1)] = nxt.get((a, b + 1), 0) + pr * (1 - p)
        frontier = nxt
    s = sum(dist.values())
    return {k: v / s for k, v in dist.items()}


def game_win_prob(pa: float, pb: float | None = None, first_server: int = 1,
                  start: tuple[int, int] = (0, 0)) -> float:
    d = game_score_distribution(pa, pb, first_server, start)
    return sum(v for (a, b), v in d.items() if a > b)


@lru_cache(maxsize=4096)
def _game_p_cached(p: float) -> float:
    return game_win_prob(p)


def match_scoreline_distribution(q: float, best_of: int = 5, start: tuple[int, int] = (0, 0)) -> dict[str, float]:
    """Given per-game win prob q (iid games), exact distribution of final match scorelines."""
    need = best_of // 2 + 1
    out: dict[str, float] = {}

    def rec(a, b, pr):
        if a == need or b == need:
            out[f"{a}-{b}"] = out.get(f"{a}-{b}", 0) + pr
            return
        rec(a + 1, b, pr * q)
        rec(a, b + 1, pr * (1 - q))

    rec(start[0], start[1], 1.0)
    return out


def match_win_from_game(q: float, best_of: int = 5, start=(0, 0)) -> float:
    need = best_of // 2 + 1
    return sum(v for k, v in match_scoreline_distribution(q, best_of, start).items() if int(k.split("-")[0]) == need)


def game_prob_from_match(p_match: float, best_of: int = 5) -> float:
    """Invert match-win probability to an iid per-game probability."""
    p_match = min(max(p_match, 1e-6), 1 - 1e-6)
    return brentq(lambda q: match_win_from_game(q, best_of) - p_match, 1e-9, 1 - 1e-9)


def point_prob_from_game(q: float) -> float:
    q = min(max(q, 1e-6), 1 - 1e-6)
    return brentq(lambda p: _game_p_cached(round(p, 10)) - q, 1e-4, 1 - 1e-4, xtol=1e-9)


def game_total_points_distribution(p: float) -> dict[int, float]:
    d = game_score_distribution(p)
    tot: dict[int, float] = {}
    for (a, b), v in d.items():
        tot[a + b] = tot.get(a + b, 0) + v
    return tot


def match_point_distributions(p: float, best_of: int = 5) -> dict:
    """Joint distribution over (total points, A-points minus B-points, sets A, sets B) via DP over games,
    assuming iid points with probability p. Returns marginal dicts for totals, point margins and scorelines."""
    gd = game_score_distribution(p)
    need = best_of // 2 + 1
    # state: (setsA, setsB, total, margin) -> prob
    states = {(0, 0, 0, 0): 1.0}
    final: dict[tuple[int, int, int, int], float] = {}
    while states:
        nxt = {}
        for (sa, sb, tot, mar), pr in states.items():
            if sa == need or sb == need:
                final[(sa, sb, tot, mar)] = final.get((sa, sb, tot, mar), 0) + pr
                continue
            for (a, b), g in gd.items():
                if g < 1e-12:
                    continue
                key = (sa + (a > b), sb + (b > a), tot + a + b, mar + a - b)
                nxt[key] = nxt.get(key, 0) + pr * g
        states = nxt
    totals, margins, scores = {}, {}, {}
    for (sa, sb, tot, mar), v in final.items():
        totals[tot] = totals.get(tot, 0) + v
        margins[mar] = margins.get(mar, 0) + v
        scores[f"{sa}-{sb}"] = scores.get(f"{sa}-{sb}", 0) + v
    return {"totals": totals, "margins": margins, "scorelines": scores}


def prob_total_over(totals: dict[int, float], line: float) -> float:
    return sum(v for t, v in totals.items() if t > line)


def prob_point_handicap(margins: dict[int, float], line: float) -> float:
    """P(A covers line), e.g. line=-3.5 means A must win by 4+ points overall."""
    return sum(v for m, v in margins.items() if m + line > 0)


def prob_set_handicap(scorelines: dict[str, float], line: float) -> float:
    """P(A covers a set handicap line, e.g. -1.5 => A wins 3-0 or 3-1)."""
    tot = 0.0
    for k, v in scorelines.items():
        a, b = map(int, k.split("-"))
        if (a - b) + line > 0:
            tot += v
    return tot


def full_match_model(p_match: float, best_of: int = 5, with_points: bool = True) -> dict:
    """From a calibrated match probability derive consistent game, scoreline and (optionally) point-level
    distributions under the iid-point assumption. Point-level outputs are EXPERIMENTAL unless validated."""
    q = game_prob_from_match(p_match, best_of)
    sl = match_scoreline_distribution(q, best_of)
    res = {"p_match": p_match, "p_game": q, "scorelines": sl}
    if with_points:
        p = point_prob_from_game(q)
        d = match_point_distributions(p, best_of)
        res.update({"p_point": p, "totals": d["totals"], "margins": d["margins"]})
    return res


def live_match_win_prob(p_point: float, sets: tuple[int, int], points: tuple[int, int], best_of: int = 5) -> float:
    """In-play P(A wins match) given current set score and current game score, iid points."""
    q_now = game_win_prob(p_point, start=points) if points != (0, 0) else _game_p_cached(round(p_point, 10))
    q = _game_p_cached(round(p_point, 10))
    need = best_of // 2 + 1
    a, b = sets
    if a >= need:
        return 1.0
    if b >= need:
        return 0.0
    win_this = match_win_from_game(q, best_of, (a + 1, b)) if a + 1 < need else 1.0
    lose_this = match_win_from_game(q, best_of, (a, b + 1)) if b + 1 < need else 0.0
    return q_now * win_this + (1 - q_now) * lose_this
