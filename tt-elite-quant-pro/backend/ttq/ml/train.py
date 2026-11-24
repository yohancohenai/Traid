"""Model training, calibration and evaluation with strictly chronological splits.

Periods (by match start time, never shuffled):
  TRAIN | TUNE (Optuna / feature ablation / model choice) | CALIB (probability calibration) | TEST (untouched)
The TEST period is evaluated once per training run and is never used for any choice.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import optuna
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from scipy.optimize import minimize_scalar

from ttq.features.builder import ALL_FEATURES, FEATURES_RATING, FEATURES_FORM

log = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)
EPS = 1e-6

FEATURE_GROUPS = {
    "ratings": ["elo_p", "dyn_elo_p", "glicko_p", "bayes_p", "set_elo_p", "bt_p", "elo_diff", "glicko_diff"],
    "uncertainty": ["glicko_rd", "bayes_sd", "min_n", "n_diff_log"],
    "form": ["wr_diff", "l5_diff", "l10_diff", "l20_diff", "l50_diff", "adj_form_diff", "stability_diff"],
    "h2h": ["h2h_share", "h2h_n", "h2h_days"],
    "sets_points": ["set_pct_diff", "set_diff_avg_diff", "pts_share_diff", "decider_rate_diff", "pts_coverage"],
    "opponents": ["common_opp_diff", "vs_stronger_diff"],
    "workload": ["sameday_diff", "rest_h_diff", "load3d_diff", "inactive_d_diff"],
    "context": ["level_major"],
    "situational": ["mom24_diff", "tod_diff"],
}
PROB_FEATURES = {"elo_p", "dyn_elo_p", "glicko_p", "bayes_p", "set_elo_p", "bt_p", "h2h_share"}


def logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def prep(df: pd.DataFrame, feats: list[str]) -> np.ndarray:
    X = df[feats].astype(float).copy()
    for c in feats:
        if c in PROB_FEATURES:
            X[c] = logit(X[c].values)
    return X.fillna(0).values


# ---------------------------------------------------------------- metrics
def brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def log_loss(y, p):
    p = np.clip(p, EPS, 1 - EPS)
    y = np.asarray(y)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def accuracy(y, p):
    return float(np.mean((np.asarray(p) >= 0.5) == (np.asarray(y) == 1)))


def reliability(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    edges = np.linspace(0, 1, bins + 1)
    out, ece = [], 0.0
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1] if i < bins - 1 else p <= edges[i + 1])
        if m.sum() == 0:
            continue
        mp, my = float(p[m].mean()), float(y[m].mean())
        out.append({"bin": i, "lo": float(edges[i]), "hi": float(edges[i + 1]), "n": int(m.sum()),
                    "mean_pred": mp, "obs_rate": my})
        ece += m.sum() / len(p) * abs(mp - my)
    return out, float(ece)


def metric_block(y, p) -> dict:
    rel, ece = reliability(y, p)
    return {"n": int(len(y)), "brier": brier(y, p), "log_loss": log_loss(y, p), "accuracy": accuracy(y, p),
            "ece": ece, "reliability": rel}


# ---------------------------------------------------------------- calibrators
class Calibrator:
    def __init__(self, method: str = "none"):
        self.method = method
        self.obj = None

    def fit(self, p, y):
        p, y = np.asarray(p), np.asarray(y)
        if self.method == "platt":
            self.obj = LogisticRegression(C=1e6).fit(logit(p).reshape(-1, 1), y)
        elif self.method == "isotonic":
            self.obj = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip").fit(p, y)
        elif self.method == "temperature":
            z = logit(p)
            res = minimize_scalar(lambda T: log_loss(y, sigmoid(z / T)), bounds=(0.25, 4), method="bounded")
            self.obj = float(res.x)
        return self

    def transform(self, p):
        p = np.asarray(p, dtype=float)
        if self.method == "platt":
            return self.obj.predict_proba(logit(p).reshape(-1, 1))[:, 1]
        if self.method == "isotonic":
            return np.clip(self.obj.predict(p), 0.01, 0.99)
        if self.method == "temperature":
            return sigmoid(logit(p) / self.obj)
        return p


def choose_calibrator(p, y) -> Calibrator:
    """Choose calibration method on the CALIB period with a chronological 2-fold check (fit first half, score second)."""
    n = len(p)
    h = n // 2
    best, best_ll = Calibrator("none"), log_loss(y[h:], p[h:])
    for m in ("platt", "temperature", "isotonic"):
        c = Calibrator(m).fit(p[:h], y[:h])
        ll = log_loss(y[h:], c.transform(p[h:]))
        if ll < best_ll - 1e-4:
            best, best_ll = Calibrator(m), ll
    return best.fit(p, y) if best.method != "none" else best


# ---------------------------------------------------------------- base learners
class RatingOnly:
    """Uses a rating engine's probability directly (no fitting)."""
    def __init__(self, col):
        self.col = col
        self.feats = [col]

    def fit(self, df, y):
        return self

    def predict(self, df):
        return np.clip(df[self.col].values.astype(float), EPS, 1 - EPS)


class EloLogistic:
    def __init__(self):
        self.feats = ["elo_diff"]
        self.m = LogisticRegression()

    def fit(self, df, y):
        self.m.fit(df[["elo_diff"]].values / 400, y)
        return self

    def predict(self, df):
        return self.m.predict_proba(df[["elo_diff"]].values / 400)[:, 1]


class LogReg:
    def __init__(self, feats, C=1.0):
        self.feats, self.C = feats, C
        self.m = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000))

    def fit(self, df, y):
        self.m.fit(prep(df, self.feats), y)
        return self

    def predict(self, df):
        return self.m.predict_proba(prep(df, self.feats))[:, 1]


class LGBM:
    def __init__(self, feats, params=None):
        import lightgbm as lgb
        self.feats = feats
        self.params = {"n_estimators": 300, "learning_rate": 0.03, "num_leaves": 15, "min_child_samples": 80,
                       "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 5.0,
                       "verbose": -1, "random_state": 0, **(params or {})}
        self.m = lgb.LGBMClassifier(**self.params)

    def fit(self, df, y):
        self.m.fit(prep(df, self.feats), y)
        return self

    def predict(self, df):
        return self.m.predict_proba(prep(df, self.feats))[:, 1]


class CatB:
    def __init__(self, feats, params=None):
        from catboost import CatBoostClassifier
        self.feats = feats
        self.params = {"iterations": 400, "depth": 4, "learning_rate": 0.04, "l2_leaf_reg": 8,
                       "verbose": False, "random_seed": 0, "thread_count": 2, "allow_writing_files": False, **(params or {})}
        self.m = CatBoostClassifier(**self.params)

    def fit(self, df, y):
        self.m.fit(prep(df, self.feats), y)
        return self

    def predict(self, df):
        return self.m.predict_proba(prep(df, self.feats))[:, 1]


class Averager:
    def __init__(self, members: dict):
        self.members = members
        self.feats = sorted({f for m in members.values() for f in m.feats})

    def predict(self, df):
        return sigmoid(np.mean([logit(m.predict(df)) for m in self.members.values()], axis=0))


class Stacker:
    """Meta logistic regression on out-of-fold (expanding-window, chronological) base predictions."""
    def __init__(self, makers: dict, n_folds: int = 4):
        self.makers, self.n_folds = makers, n_folds
        self.base = {}
        self.meta = LogisticRegression(C=1.0)
        self.feats = []

    def fit(self, df, y):
        n = len(df)
        edges = np.linspace(n * 0.4, n, self.n_folds + 1).astype(int)
        oof_rows, oof_y = [], []
        for i in range(self.n_folds):
            tr, va = slice(0, edges[i]), slice(edges[i], edges[i + 1])
            cols = []
            for k, mk in self.makers.items():
                m = mk().fit(df.iloc[tr], y[tr])
                cols.append(logit(m.predict(df.iloc[va])))
            oof_rows.append(np.column_stack(cols)); oof_y.append(y[va])
        self.meta.fit(np.vstack(oof_rows), np.concatenate(oof_y))
        self.base = {k: mk().fit(df, y) for k, mk in self.makers.items()}
        self.feats = sorted({f for m in self.base.values() for f in m.feats})
        self.makers = None  # lambdas are not picklable; base models are kept
        return self

    def predict(self, df):
        X = np.column_stack([logit(m.predict(df)) for m in self.base.values()])
        return self.meta.predict_proba(X)[:, 1]


# ---------------------------------------------------------------- pipeline
@dataclass
class TrainedModel:
    name: str
    model: object
    calibrator: Calibrator
    feats: list[str]
    metrics: dict = field(default_factory=dict)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.calibrator.transform(self.model.predict(df))


def split_periods(df: pd.DataFrame, fr=(0.60, 0.15, 0.10, 0.15)) -> dict[str, pd.DataFrame]:
    d = df[df["y"].notna()].sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
    n = len(d)
    c = np.cumsum([0] + [int(round(f * n)) for f in fr])
    c[-1] = n
    # do not split inside a timestamp (simultaneous matches stay together)
    parts, names = {}, ["train", "tune", "calib", "test"]
    times = d["scheduled_at"].values
    bounds = [0]
    for b in c[1:-1]:
        while 0 < b < n and times[b] == times[b - 1]:
            b += 1
        bounds.append(b)
    bounds.append(n)
    for i, nm in enumerate(names):
        parts[nm] = d.iloc[bounds[i]:bounds[i + 1]]
    return parts


def ablate_features(tr, ytr, tu, ytu) -> tuple[list[str], dict]:
    """Group-wise ablation on the TUNE period with regularised logistic regression.
    A group is kept only if removing it worsens tune log loss by more than 0.0005."""
    full = LogReg(ALL_FEATURES, C=0.3).fit(tr, ytr)
    base_ll = log_loss(ytu, full.predict(tu))
    report, keep = {}, []
    for g, cols in FEATURE_GROUPS.items():
        feats = [f for f in ALL_FEATURES if f not in cols]
        ll = log_loss(ytu, LogReg(feats, C=0.3).fit(tr, ytr).predict(tu))
        delta = ll - base_ll  # >0 means the group helps
        report[g] = {"delta_log_loss_when_removed": round(delta, 6), "kept": bool(delta > 0.0005 or g == "ratings")}
        if report[g]["kept"]:
            keep.extend(cols)
    return keep, {"base_tune_log_loss": base_ll, "groups": report}


def tune_lgbm(tr, ytr, tu, ytu, feats, n_trials=12):
    def obj(trial):
        params = {"num_leaves": trial.suggest_int("num_leaves", 4, 31),
                  "min_child_samples": trial.suggest_int("min_child_samples", 30, 300, log=True),
                  "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
                  "n_estimators": trial.suggest_int("n_estimators", 100, 500, step=50),
                  "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 30, log=True)}
        return log_loss(ytu, LGBM(feats, params).fit(tr, ytr).predict(tu))
    st = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=0))
    st.optimize(obj, n_trials=n_trials)
    return st.best_params, st.best_value


def tune_logreg(tr, ytr, tu, ytu, feats, n_trials=10):
    def obj(trial):
        C = trial.suggest_float("C", 1e-3, 10, log=True)
        return log_loss(ytu, LogReg(feats, C).fit(tr, ytr).predict(tu))
    st = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=0))
    st.optimize(obj, n_trials=n_trials)
    return st.best_params, st.best_value


def market_metrics(test: pd.DataFrame, p_model: np.ndarray) -> dict | None:
    if "mkt_p1" not in test or test["mkt_p1"].notna().sum() < 30:
        return None
    m = test["mkt_p1"].notna().values
    y = test["y"].values[m]
    return {"n": int(m.sum()), "model": {"brier": brier(y, p_model[m]), "log_loss": log_loss(y, p_model[m])},
            "market_novig": {"brier": brier(y, test["mkt_p1"].values[m]), "log_loss": log_loss(y, test["mkt_p1"].values[m])}}


def train_all(df: pd.DataFrame, n_trials: int = 12, fast: bool = False) -> dict:
    """Train every candidate, calibrate on CALIB, evaluate once on TEST. Champion chosen on CALIB (post-calibration)
    log loss -- never on TEST and never on ROI."""
    P = split_periods(df)
    tr, tu, ca, te = P["train"], P["tune"], P["calib"], P["test"]
    ytr, ytu, yca, yte = (x["y"].values.astype(int) for x in (tr, tu, ca, te))
    feats, ablation = ablate_features(tr, ytr, tu, ytu)
    lr_params, _ = tune_logreg(tr, ytr, tu, ytu, feats, n_trials=4 if fast else 10)
    lgb_params, _ = tune_lgbm(tr, ytr, tu, ytu, feats, n_trials=3 if fast else n_trials)
    cat_params = {"iterations": 150 if fast else 400}

    # Fit on TRAIN+TUNE for final candidates (tuning choices are fixed already)
    fit_df = pd.concat([tr, tu])
    yfit = fit_df["y"].values.astype(int)
    makers = {
        "logreg": lambda: LogReg(feats, **lr_params),
        "lightgbm": lambda: LGBM(feats, lgb_params),
        "catboost": lambda: CatB(feats, cat_params),
    }
    cands = {
        "elo_baseline": EloLogistic().fit(fit_df, yfit),
        "glicko2_baseline": RatingOnly("glicko_p"),
        "bayes_hier": RatingOnly("bayes_p"),
        "bradley_terry": RatingOnly("bt_p"),
        "set_elo": RatingOnly("set_elo_p"),
        "dyn_elo": RatingOnly("dyn_elo_p"),
    }
    for k, mk in makers.items():
        cands[k] = mk().fit(fit_df, yfit)
    cands["ensemble"] = Averager({k: cands[k] for k in ("logreg", "lightgbm", "catboost", "bayes_hier")})
    cands["stacked"] = Stacker(makers, n_folds=3 if fast else 4).fit(fit_df, yfit)

    results = {}
    for name, m in cands.items():
        raw_ca = m.predict(ca)
        cal = choose_calibrator(raw_ca, yca)
        tm = TrainedModel(name, m, cal, getattr(m, "feats", feats))
        p_ca, p_te = tm.predict(ca), tm.predict(te)
        tm.metrics = {"calib": metric_block(yca, p_ca), "test": metric_block(yte, p_te),
                      "calibration_method": cal.method, "vs_market_test": market_metrics(te, p_te)}
        results[name] = tm
    champion = min(results, key=lambda k: results[k].metrics["calib"]["log_loss"])
    splits = {k: {"start": str(v["scheduled_at"].min()), "end": str(v["scheduled_at"].max()), "n": int(len(v))}
              for k, v in P.items()}
    return {"models": results, "champion": champion, "features": feats, "ablation": ablation,
            "params": {"logreg": lr_params, "lightgbm": lgb_params, "catboost": cat_params}, "splits": splits,
            "test_ids": te["match_id"].tolist()}
