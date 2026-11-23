"""Chronological, leakage-safe feature construction.

Event-driven replay:
  - PREDICT events at each match's decision time (scheduled start)
  - UPDATE events at each match's finish time (result becomes known)
At equal timestamps PREDICT is processed before UPDATE, so simultaneous matches never see each other.
A match's features therefore depend only on matches whose result was known strictly before its start.

Small-sample statistics are shrunk towards 0.5 with a Beta(k/2, k/2) prior.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ttq.ratings.engines import RatingEngine, default_engines, elo_prob

ASSUMED_MATCH_MINUTES = 45  # used only when a finish time is unknown, conservatively late


@dataclass
class MatchRecord:
    id: int
    p1: int
    p2: int
    scheduled_at: datetime
    finished_at: datetime | None = None
    status: str = "FINISHED"
    p1_won: bool | None = None
    sets_p1: int | None = None
    sets_p2: int | None = None
    set_points: list[tuple[int, int]] = field(default_factory=list)
    tournament_level: str = "standard"
    is_demo: bool = False

    @property
    def counts_for_rating(self) -> bool:
        # Retirements / walkovers / cancellations are excluded from strength estimation
        return self.status == "FINISHED" and self.p1_won is not None

    @property
    def known_at(self) -> datetime:
        return self.finished_at or (self.scheduled_at + timedelta(minutes=ASSUMED_MATCH_MINUTES))


def shrunk_rate(wins: float, n: float, k: float = 10.0) -> float:
    return (wins + k / 2) / (n + k)


class PlayerHistory:
    __slots__ = ("results", "resid", "opp", "set_w", "set_n", "pts_w", "pts_n", "pts_matches",
                 "match_times", "n", "wins", "vs_stronger_w", "vs_stronger_n", "deciders", "set_diff")

    def __init__(self):
        self.results: deque = deque(maxlen=50)      # 1/0
        self.resid: deque = deque(maxlen=20)        # result - elo expectation
        self.opp: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])  # opp -> [wins, n]
        self.set_w = self.set_n = 0.0
        self.pts_w = self.pts_n = 0.0
        self.pts_matches = 0
        self.match_times: deque = deque(maxlen=200)
        self.n = 0
        self.wins = 0
        self.vs_stronger_w = self.vs_stronger_n = 0.0
        self.deciders = 0
        self.set_diff = 0.0


FEATURES_RATING = ["elo_p", "dyn_elo_p", "glicko_p", "bayes_p", "set_elo_p", "bt_p",
                   "elo_diff", "glicko_diff", "glicko_rd", "bayes_sd"]
FEATURES_FORM = ["wr_diff", "l5_diff", "l10_diff", "l20_diff", "l50_diff", "adj_form_diff",
                 "h2h_share", "h2h_n", "h2h_days", "set_pct_diff", "set_diff_avg_diff", "pts_share_diff",
                 "common_opp_diff", "vs_stronger_diff", "sameday_diff", "rest_h_diff", "load3d_diff",
                 "inactive_d_diff", "stability_diff", "decider_rate_diff", "min_n", "n_diff_log",
                 "pts_coverage", "level_major"]
ALL_FEATURES = FEATURES_RATING + FEATURES_FORM


class FeatureBuilder:
    def __init__(self, engines: dict[str, RatingEngine] | None = None):
        self.engines = engines or default_engines()
        self.h: dict[int, PlayerHistory] = defaultdict(PlayerHistory)
        self.h2h: dict[tuple[int, int], list] = defaultdict(lambda: [0.0, 0.0, None])  # wins for min-id, n, last
        self.last_update: datetime | None = None

    # ---------------------------------------------------------------- features at time t
    def features(self, m: MatchRecord, t: datetime | None = None) -> dict:
        t = t or m.scheduled_at
        a, b = m.p1, m.p2
        E = self.engines
        ha, hb = self.h[a], self.h[b]
        f: dict[str, float] = {}
        f["elo_p"] = E["elo"].predict(a, b, t)
        f["dyn_elo_p"] = E["dyn_elo"].predict(a, b, t)
        f["glicko_p"] = E["glicko2"].predict(a, b, t)
        f["bayes_p"] = E["bayes"].predict(a, b, t)
        f["set_elo_p"] = E["set_elo"].predict(a, b, t)
        f["bt_p"] = E["bt"].predict(a, b, t)
        f["elo_diff"] = E["elo"].rating(a)[0] - E["elo"].rating(b)[0]
        f["glicko_diff"] = E["glicko2"].rating(a)[0] - E["glicko2"].rating(b)[0]
        f["glicko_rd"] = E["glicko2"].uncertainty(a, b, t)
        f["bayes_sd"] = E["bayes"].uncertainty(a, b, t)
        lo, hi = E["bayes"].credible_interval(a, b, t)
        f["_bayes_lo"], f["_bayes_hi"] = lo, hi

        def wr(h: PlayerHistory, last=None):
            r = list(h.results)[-last:] if last else None
            if last:
                return shrunk_rate(sum(r), len(r), 4)
            return shrunk_rate(h.wins, h.n, 10)

        f["wr_diff"] = wr(ha) - wr(hb)
        for L in (5, 10, 20, 50):
            f[f"l{L}_diff"] = wr(ha, L) - wr(hb, L)
        f["adj_form_diff"] = (sum(ha.resid) / (len(ha.resid) + 5)) - (sum(hb.resid) / (len(hb.resid) + 5))
        key = (min(a, b), max(a, b))
        hw, hn, hlast = self.h2h[key]
        a_w = hw if a == key[0] else hn - hw
        f["h2h_share"] = shrunk_rate(a_w, hn, 6)
        f["h2h_n"] = hn
        f["h2h_days"] = min((t - hlast).total_seconds() / 86400, 365) if hlast else 365.0
        f["set_pct_diff"] = shrunk_rate(ha.set_w, ha.set_n, 20) - shrunk_rate(hb.set_w, hb.set_n, 20)
        f["set_diff_avg_diff"] = ha.set_diff / (ha.n + 5) - hb.set_diff / (hb.n + 5)
        f["pts_share_diff"] = shrunk_rate(ha.pts_w, ha.pts_n, 200) - shrunk_rate(hb.pts_w, hb.pts_n, 200)
        common = set(ha.opp) & set(hb.opp) - {a, b}
        if common:
            aw = sum(ha.opp[o][0] for o in common); an = sum(ha.opp[o][1] for o in common)
            bw = sum(hb.opp[o][0] for o in common); bn = sum(hb.opp[o][1] for o in common)
            f["common_opp_diff"] = shrunk_rate(aw, an, 8) - shrunk_rate(bw, bn, 8)
        else:
            f["common_opp_diff"] = 0.0
        f["vs_stronger_diff"] = shrunk_rate(ha.vs_stronger_w, ha.vs_stronger_n, 8) - shrunk_rate(hb.vs_stronger_w, hb.vs_stronger_n, 8)

        def sameday(h):
            return sum(1 for x in h.match_times if x.date() == t.date() and x <= t)

        def rest_h(h):
            return min((t - h.match_times[-1]).total_seconds() / 3600, 240) if h.match_times else 240.0

        def load3(h):
            return sum(1 for x in h.match_times if (t - x).total_seconds() < 3 * 86400)

        f["sameday_diff"] = sameday(ha) - sameday(hb)
        f["rest_h_diff"] = rest_h(ha) - rest_h(hb)
        f["load3d_diff"] = load3(ha) - load3(hb)
        f["inactive_d_diff"] = min(rest_h(ha), 240) / 24 - min(rest_h(hb), 240) / 24

        def stab(h):
            return float(np.std(h.resid)) if len(h.resid) >= 5 else 0.5

        f["stability_diff"] = stab(ha) - stab(hb)
        f["decider_rate_diff"] = shrunk_rate(ha.deciders, ha.n, 10) - shrunk_rate(hb.deciders, hb.n, 10)
        f["min_n"] = min(ha.n, hb.n)
        f["n_diff_log"] = math.log1p(ha.n) - math.log1p(hb.n)
        f["pts_coverage"] = min(ha.pts_matches / ha.n if ha.n else 0, hb.pts_matches / hb.n if hb.n else 0)
        f["level_major"] = 1.0 if m.tournament_level in ("major", "final", "playoff") else 0.0
        f["_n1"], f["_n2"] = ha.n, hb.n
        return f

    # ---------------------------------------------------------------- state update after result known
    def update(self, m: MatchRecord):
        if not m.counts_for_rating:
            return
        t = m.known_at
        a, b = m.p1, m.p2
        ga, gb = (m.sets_p1 or 0), (m.sets_p2 or 0)
        exp_a = elo_prob(self.engines["elo"].rating(a)[0], self.engines["elo"].rating(b)[0])
        stronger_b = exp_a < 0.5
        for eng in self.engines.values():
            eng.update(a, b, bool(m.p1_won), ga, gb, t)
        for pid, opp, won, gw, gl, exp, stronger in ((a, b, m.p1_won, ga, gb, exp_a, stronger_b),
                                                      (b, a, not m.p1_won, gb, ga, 1 - exp_a, not stronger_b)):
            h = self.h[pid]
            r = 1.0 if won else 0.0
            h.results.append(r)
            h.resid.append(r - exp)
            h.opp[opp][0] += r
            h.opp[opp][1] += 1
            h.set_w += gw
            h.set_n += gw + gl
            h.set_diff += gw - gl
            if m.set_points:
                if pid == a:
                    h.pts_w += sum(x for x, _ in m.set_points); h.pts_n += sum(x + y for x, y in m.set_points)
                else:
                    h.pts_w += sum(y for _, y in m.set_points); h.pts_n += sum(x + y for x, y in m.set_points)
                h.pts_matches += 1
            h.match_times.append(m.scheduled_at)
            h.n += 1
            h.wins += int(r)
            if stronger:
                h.vs_stronger_n += 1
                h.vs_stronger_w += r
            if gw + gl == 5:
                h.deciders += 1
        key = (min(a, b), max(a, b))
        rec = self.h2h[key]
        rec[0] += 1.0 if ((a == key[0]) == bool(m.p1_won)) else 0.0
        rec[1] += 1
        rec[2] = t
        self.last_update = t


def build_dataset(matches: list[MatchRecord], builder: FeatureBuilder | None = None,
                  snapshot_cb=None) -> tuple[pd.DataFrame, FeatureBuilder]:
    """Replay history. Returns one feature row per match (including unfinished matches, label NaN)."""
    fb = builder or FeatureBuilder()
    events = []
    for m in matches:
        events.append((m.scheduled_at, 0, m.id, m))           # predict first
        if m.counts_for_rating:
            events.append((m.known_at, 1, m.id, m))           # then update
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    rows = []
    for t, kind, _, m in events:
        if kind == 0:
            f = fb.features(m, t)
            f.update({"match_id": m.id, "scheduled_at": m.scheduled_at, "p1": m.p1, "p2": m.p2,
                      "y": (1.0 if m.p1_won else 0.0) if m.counts_for_rating else np.nan,
                      "sets_p1": m.sets_p1, "sets_p2": m.sets_p2, "status": m.status})
            rows.append(f)
            if snapshot_cb:
                snapshot_cb(m, fb, t)
        else:
            fb.update(m)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
    return df, fb


def data_quality(n1: int, n2: int, pts_cov: float) -> str:
    mn = min(n1, n2)
    if mn >= 30 and pts_cov >= 0.5:
        return "HIGH"
    if mn >= 10:
        return "MEDIUM"
    return "LOW"
