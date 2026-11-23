"""Leakage, rating sanity and calibration tests on a synthetic world."""
import copy
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ttq.features.builder import MatchRecord, build_dataset, ALL_FEATURES
from ttq.ratings.engines import default_engines, BayesGaussian, Glicko2


def world(n_players=20, days=60, seed=0):
    rng = np.random.default_rng(seed)
    skill = rng.normal(0, 0.6, n_players)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recs, i = [], 0
    for d in range(days):
        for k in range(12):
            a, b = rng.choice(n_players, 2, replace=False)
            at = t0 + timedelta(days=d, minutes=30 * (k // 2))  # pairs of simultaneous matches
            pw = 1 / (1 + np.exp(-(skill[a] - skill[b])))
            won = rng.random() < pw
            i += 1
            recs.append(MatchRecord(id=i, p1=int(a), p2=int(b), scheduled_at=at, finished_at=at + timedelta(minutes=25),
                                    p1_won=bool(won), sets_p1=3 if won else 1, sets_p2=1 if won else 3))
    return recs


def test_features_do_not_depend_on_future_or_simultaneous_results():
    recs = world()
    df1, _ = build_dataset(copy.deepcopy(recs))
    cut = recs[len(recs) // 2].scheduled_at
    flipped = copy.deepcopy(recs)
    for r in flipped:
        if r.scheduled_at >= cut:            # flip every result at or after the cutoff (incl. simultaneous)
            r.p1_won = not r.p1_won
            r.sets_p1, r.sets_p2 = r.sets_p2, r.sets_p1
    df2, _ = build_dataset(flipped)
    cols = ALL_FEATURES
    a = df1[df1.scheduled_at <= cut].set_index("match_id")[cols]
    b = df2[df2.scheduled_at <= cut].set_index("match_id")[cols]
    pd_eq = np.allclose(a.values.astype(float), b.loc[a.index].values.astype(float), equal_nan=True)
    assert pd_eq, "features before the cutoff changed when only later/simultaneous results changed"
    # and after the cutoff they DO change (sanity: the test can detect leakage)
    a2 = df1[df1.scheduled_at > cut + timedelta(days=1)].set_index("match_id")["elo_p"]
    b2 = df2[df2.scheduled_at > cut + timedelta(days=1)].set_index("match_id")["elo_p"]
    assert not np.allclose(a2.values, b2.loc[a2.index].values)


def test_all_engine_probabilities_valid_and_learn():
    recs = world(days=80)
    df, fb = build_dataset(recs)
    for c in ("elo_p", "dyn_elo_p", "glicko_p", "bayes_p", "set_elo_p", "bt_p"):
        assert df[c].between(0, 1).all()
        late = df.iloc[len(df) // 2:]
        acc = ((late[c] >= 0.5) == (late["y"] == 1)).mean()
        assert acc > 0.6, c


def test_new_players_are_uncertain():
    b = BayesGaussian()
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(50):
        b.update(1, 2, True, 3, 0, t + timedelta(hours=i))
    assert b.uncertainty(1, 3, t) > b.uncertainty(1, 2, t)
    g = Glicko2()
    g.update(1, 2, True, 3, 0, t)
    assert g.rating(99)[1] > g.rating(1)[1]


def test_training_is_chronological_and_calibration_measured():
    from ttq.ml.train import split_periods, train_all
    recs = world(n_players=30, days=200, seed=1)
    df, _ = build_dataset(recs)
    P = split_periods(df)
    assert P["train"].scheduled_at.max() <= P["tune"].scheduled_at.min()
    assert P["tune"].scheduled_at.max() <= P["calib"].scheduled_at.min()
    assert P["calib"].scheduled_at.max() <= P["test"].scheduled_at.min()
    res = train_all(df, fast=True)
    for name, tm in res["models"].items():
        m = tm.metrics["test"]
        assert 0 <= m["brier"] <= 1 and m["log_loss"] > 0 and 0 <= m["ece"] <= 1
        assert m["reliability"]
        p = tm.predict(P["test"])
        assert ((p >= 0) & (p <= 1)).all()
    assert res["champion"] in res["models"]
