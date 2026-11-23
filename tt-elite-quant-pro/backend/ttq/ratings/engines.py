"""Player rating engines. All are *online*: `predict` uses only state accumulated from past `update` calls.

A  Elo                 - fixed K.
B  DynamicElo          - K decays with experience, inactivity decay towards mean, opponent-strength via expectation.
C  Glicko2             - rating deviation, volatility, RD inflation during inactivity.
D  BayesGaussian       - hierarchical Gaussian ratings: new players drawn from an empirically estimated
                         population prior (partial pooling); posterior updated by assumed-density filtering
                         (Laplace approximation of the logistic likelihood). Gives credible intervals.
E  SetWeightedElo      - experimental: updates on share of games won vs expected share.
F  BradleyTerry        - regularised, time-decayed paired-comparison MLE, refit periodically.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

LN10_400 = math.log(10) / 400


def logistic(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def elo_prob(ra: float, rb: float) -> float:
    return 1 / (1 + 10 ** ((rb - ra) / 400))


class RatingEngine:
    name = "base"

    def predict(self, a: int, b: int, t: datetime) -> float:
        raise NotImplementedError

    def update(self, a: int, b: int, a_won: bool, games_a: int, games_b: int, t: datetime) -> None:
        raise NotImplementedError

    def rating(self, pid: int) -> tuple[float, float | None, int]:
        raise NotImplementedError

    def uncertainty(self, a: int, b: int, t: datetime) -> float | None:
        return None


# ---------------------------------------------------------------- A
class Elo(RatingEngine):
    name = "elo"

    def __init__(self, k: float = 24.0, init: float = 1500.0):
        self.k, self.init = k, init
        self.r: dict[int, float] = {}
        self.n: dict[int, int] = {}

    def _r(self, p):
        return self.r.get(p, self.init)

    def predict(self, a, b, t):
        return elo_prob(self._r(a), self._r(b))

    def update(self, a, b, a_won, games_a, games_b, t):
        e = self.predict(a, b, t)
        s = 1.0 if a_won else 0.0
        self.r[a] = self._r(a) + self.k * (s - e)
        self.r[b] = self._r(b) - self.k * (s - e)
        self.n[a] = self.n.get(a, 0) + 1
        self.n[b] = self.n.get(b, 0) + 1

    def rating(self, pid):
        return self._r(pid), None, self.n.get(pid, 0)


# ---------------------------------------------------------------- B
class DynamicElo(Elo):
    name = "dyn_elo"

    def __init__(self, k_base: float = 16.0, k_new: float = 48.0, half_life_games: float = 20.0,
                 decay_per_day: float = 0.0, init: float = 1500.0, margin_weight: float = 0.0):
        super().__init__(k_base, init)
        self.k_new, self.hl, self.decay, self.mw = k_new, half_life_games, decay_per_day, margin_weight
        self.last: dict[int, datetime] = {}

    def _k(self, p):
        n = self.n.get(p, 0)
        return self.k + (self.k_new - self.k) * 0.5 ** (n / self.hl)

    def _decayed(self, p, t):
        r = self._r(p)
        if self.decay and p in self.last:
            days = max(0.0, (t - self.last[p]).total_seconds() / 86400)
            r = self.init + (r - self.init) * (1 - self.decay) ** days
        return r

    def predict(self, a, b, t):
        return elo_prob(self._decayed(a, t), self._decayed(b, t))

    def update(self, a, b, a_won, games_a, games_b, t):
        ra, rb = self._decayed(a, t), self._decayed(b, t)
        e = elo_prob(ra, rb)
        s = 1.0 if a_won else 0.0
        mult = 1.0 + self.mw * (abs(games_a - games_b) - 1) if self.mw else 1.0
        self.r[a] = ra + self._k(a) * mult * (s - e)
        self.r[b] = rb - self._k(b) * mult * (s - e)
        for p in (a, b):
            self.n[p] = self.n.get(p, 0) + 1
            self.last[p] = t


# ---------------------------------------------------------------- E
from functools import lru_cache


@lru_cache(maxsize=2048)
def _game_q(p: float) -> float:
    from ttq.sim.tt import game_prob_from_match
    return game_prob_from_match(min(max(p, 0.001), 0.999))


class SetWeightedElo(Elo):
    """Experimental challenger: target is the share of games won, expectation is the share implied by the
    rating gap through the exact best-of-5 game model (approximated by the per-game probability)."""
    name = "set_elo"

    def __init__(self, k: float = 32.0, init: float = 1500.0):
        super().__init__(k, init)

    def update(self, a, b, a_won, games_a, games_b, t):
        p = elo_prob(self._r(a), self._r(b))
        q = _game_q(round(p, 3))
        tot = games_a + games_b
        s = games_a / tot if tot else (1.0 if a_won else 0.0)
        self.r[a] = self._r(a) + self.k * (s - q)
        self.r[b] = self._r(b) - self.k * (s - q)
        self.n[a] = self.n.get(a, 0) + 1
        self.n[b] = self.n.get(b, 0) + 1


# ---------------------------------------------------------------- C
GLICKO_SCALE = 173.7178


@dataclass
class _G2:
    mu: float = 0.0
    phi: float = 350 / GLICKO_SCALE
    sigma: float = 0.06
    last: datetime | None = None
    n: int = 0


class Glicko2(RatingEngine):
    """Each match is treated as its own rating period; RD inflates with elapsed time (period_days)."""
    name = "glicko2"

    def __init__(self, tau: float = 0.5, period_days: float = 1.0, init_rd: float = 350.0, max_rd: float = 350.0):
        self.tau, self.period_days = tau, period_days
        self.init_phi, self.max_phi = init_rd / GLICKO_SCALE, max_rd / GLICKO_SCALE
        self.s: dict[int, _G2] = {}

    def _get(self, p, t):
        st = self.s.get(p)
        if st is None:
            return _G2(phi=self.init_phi)
        phi = st.phi
        if st.last is not None:
            periods = max(0.0, (t - st.last).total_seconds() / 86400 / self.period_days)
            phi = min(math.sqrt(phi ** 2 + periods * st.sigma ** 2), self.max_phi)
        return _G2(st.mu, phi, st.sigma, st.last, st.n)

    @staticmethod
    def _g(phi):
        return 1 / math.sqrt(1 + 3 * phi ** 2 / math.pi ** 2)

    def predict(self, a, b, t):
        A, B = self._get(a, t), self._get(b, t)
        # Expected score including both players' uncertainty
        g = self._g(math.sqrt(A.phi ** 2 + B.phi ** 2))
        return 1 / (1 + math.exp(-g * (A.mu - B.mu)))

    def uncertainty(self, a, b, t):
        A, B = self._get(a, t), self._get(b, t)
        return math.sqrt(A.phi ** 2 + B.phi ** 2) * GLICKO_SCALE

    def _update_one(self, P: _G2, O: _G2, score: float) -> _G2:
        g = self._g(O.phi)
        E = 1 / (1 + math.exp(-g * (P.mu - O.mu)))
        v = 1 / (g * g * E * (1 - E))
        delta = v * g * (score - E)
        a = math.log(P.sigma ** 2)
        tau = self.tau

        def f(x):
            ex = math.exp(x)
            return ex * (delta ** 2 - P.phi ** 2 - v - ex) / (2 * (P.phi ** 2 + v + ex) ** 2) - (x - a) / tau ** 2

        A_ = a
        if delta ** 2 > P.phi ** 2 + v:
            B_ = math.log(delta ** 2 - P.phi ** 2 - v)
        else:
            k = 1
            while f(a - k * tau) < 0:
                k += 1
            B_ = a - k * tau
        fA, fB = f(A_), f(B_)
        for _ in range(100):
            if abs(B_ - A_) < 1e-6:
                break
            C = A_ + (A_ - B_) * fA / (fB - fA)
            fC = f(C)
            if fC * fB <= 0:
                A_, fA = B_, fB
            else:
                fA /= 2
            B_, fB = C, fC
        sigma = math.exp(A_ / 2)
        phi_star = math.sqrt(P.phi ** 2 + sigma ** 2)
        phi = 1 / math.sqrt(1 / phi_star ** 2 + 1 / v)
        mu = P.mu + phi ** 2 * g * (score - E)
        return _G2(mu, phi, sigma, None, P.n + 1)

    def update(self, a, b, a_won, games_a, games_b, t):
        A, B = self._get(a, t), self._get(b, t)
        s = 1.0 if a_won else 0.0
        nA, nB = self._update_one(A, B, s), self._update_one(B, A, 1 - s)
        nA.last = nB.last = t
        self.s[a], self.s[b] = nA, nB

    def rating(self, pid):
        st = self.s.get(pid)
        if st is None:
            return 1500.0, self.init_phi * GLICKO_SCALE, 0
        return 1500 + st.mu * GLICKO_SCALE, st.phi * GLICKO_SCALE, st.n


# ---------------------------------------------------------------- D
class BayesGaussian(RatingEngine):
    """Hierarchical Gaussian skill model on the logit scale.

    theta_i ~ N(m, tau^2)                     (population prior, m and tau^2 estimated from current pool)
    P(i beats j) = sigmoid(theta_i - theta_j)
    Posterior of each theta approximated by N(mu, s^2) and updated by ADF / Laplace step.
    Skill drift: s^2 += drift_per_day * days since last match.
    """
    name = "bayes"

    def __init__(self, drift_per_day: float = 0.002, prior_tau2: float = 0.5, min_pool: int = 20):
        self.drift = drift_per_day
        self.mu: dict[int, float] = {}
        self.var: dict[int, float] = {}
        self.last: dict[int, datetime] = {}
        self.n: dict[int, int] = {}
        self.prior_tau2, self.min_pool = prior_tau2, min_pool

    def population_prior(self) -> tuple[float, float]:
        """Empirical-Bayes estimate of (m, tau^2) from established players (partial pooling)."""
        est = [p for p, k in self.n.items() if k >= 10]
        if len(est) < self.min_pool:
            return 0.0, self.prior_tau2
        mus = np.array([self.mu[p] for p in est])
        vs = np.array([self.var[p] for p in est])
        tau2 = max(float(mus.var() - vs.mean()), 0.05)
        # New entrants tend to be weaker than the established pool; shrink to the mean of low-experience history
        return float(mus.mean()), tau2

    def _state(self, p, t):
        if p not in self.mu:
            m, tau2 = self.population_prior()
            return m, tau2
        v = self.var[p]
        if p in self.last:
            v += self.drift * max(0.0, (t - self.last[p]).total_seconds() / 86400)
        return self.mu[p], min(v, 2.0)

    def predict(self, a, b, t):
        ma, va = self._state(a, t)
        mb, vb = self._state(b, t)
        # E[sigmoid(d)] with d ~ N(mean, var), probit approximation
        return logistic((ma - mb) / math.sqrt(1 + math.pi * (va + vb) / 8))

    def credible_interval(self, a, b, t, z: float = 1.645) -> tuple[float, float]:
        ma, va = self._state(a, t)
        mb, vb = self._state(b, t)
        d, s = ma - mb, math.sqrt(va + vb)
        return logistic(d - z * s), logistic(d + z * s)

    def uncertainty(self, a, b, t):
        _, va = self._state(a, t)
        _, vb = self._state(b, t)
        return math.sqrt(va + vb)

    def update(self, a, b, a_won, games_a, games_b, t):
        ma, va = self._state(a, t)
        mb, vb = self._state(b, t)
        y = 1.0 if a_won else 0.0
        # Laplace step at the prior mean
        p = logistic(ma - mb)
        grad = y - p
        hess = p * (1 - p)
        # Posterior precision update for each player
        for pid, m, v, sign in ((a, ma, va, 1), (b, mb, vb, -1)):
            new_v = 1 / (1 / v + hess)
            self.mu[pid] = m + sign * new_v * grad
            self.var[pid] = new_v
            self.n[pid] = self.n.get(pid, 0) + 1
            self.last[pid] = t

    def rating(self, pid):
        if pid not in self.mu:
            m, tau2 = self.population_prior()
            return 1500 + m * 400 / math.log(10), math.sqrt(tau2) * 400 / math.log(10), 0
        return 1500 + self.mu[pid] * 400 / math.log(10), math.sqrt(self.var[pid]) * 400 / math.log(10), self.n[pid]


# ---------------------------------------------------------------- F
class BradleyTerry(RatingEngine):
    """Time-decayed, L2-regularised Bradley-Terry refit on all *completed* matches every `refit_hours`.
    Between refits, strengths are frozen (no leakage: only matches already passed to `update`)."""
    name = "bt"

    def __init__(self, half_life_days: float = 60.0, l2: float = 1.0, refit_hours: float = 24.0, window_days: float = 240.0):
        self.hl, self.l2, self.refit_h, self.window = half_life_days, l2, refit_hours, window_days
        self.hist: list[tuple[int, int, float, datetime]] = []
        self.theta: dict[int, float] = {}
        self.fitted_at: datetime | None = None
        self.n: dict[int, int] = {}

    def _maybe_refit(self, t):
        if self.fitted_at is not None and (t - self.fitted_at).total_seconds() < self.refit_h * 3600:
            return
        self.fitted_at = t
        rows = [h for h in self.hist if (t - h[3]).days <= self.window]
        if len(rows) < 30:
            return
        players = sorted({r[0] for r in rows} | {r[1] for r in rows})
        idx = {p: i for i, p in enumerate(players)}
        A = np.array([idx[r[0]] for r in rows])
        B = np.array([idx[r[1]] for r in rows])
        y = np.array([r[2] for r in rows])
        w = np.array([0.5 ** ((t - r[3]).total_seconds() / 86400 / self.hl) for r in rows])
        th = np.array([self.theta.get(p, 0.0) for p in players])
        # Newton iterations on penalised weighted log-likelihood (diagonal Hessian approx + few iterations)
        for _ in range(25):
            d = th[A] - th[B]
            p = 1 / (1 + np.exp(-d))
            r = w * (y - p)
            h = w * p * (1 - p)
            g = np.zeros(len(players)); H = np.full(len(players), self.l2)
            np.add.at(g, A, r); np.add.at(g, B, -r)
            np.add.at(H, A, h); np.add.at(H, B, h)
            g -= self.l2 * th
            step = g / H
            th += step
            if np.abs(step).max() < 1e-6:
                break
        self.theta = {p: float(th[i]) for p, i in idx.items()}

    def predict(self, a, b, t):
        self._maybe_refit(t)
        return logistic(self.theta.get(a, 0.0) - self.theta.get(b, 0.0))

    def update(self, a, b, a_won, games_a, games_b, t):
        self.hist.append((a, b, 1.0 if a_won else 0.0, t))
        for p in (a, b):
            self.n[p] = self.n.get(p, 0) + 1

    def rating(self, pid):
        return 1500 + self.theta.get(pid, 0.0) * 400 / math.log(10), None, self.n.get(pid, 0)


def default_engines() -> dict[str, RatingEngine]:
    return {
        "elo": Elo(),
        "dyn_elo": DynamicElo(),
        "glicko2": Glicko2(),
        "bayes": BayesGaussian(),
        "set_elo": SetWeightedElo(),
        "bt": BradleyTerry(),
    }
