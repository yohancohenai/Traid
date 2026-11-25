"""Set-score markets, calibrated on real results.

The textbook model (every game independent) is badly off on TT Elite: on 2,161 held-out matches it said 36.8% of
matches go to 5 sets (actual 27.9%) and that the favourite wins 3-0/3-1 37.5% of the time (actual 44.1%). Matches
are more one-sided than independence implies. So these probabilities come from a logistic calibration on past
results instead:
  P(favourite -1.5 sets) = sigmoid(a + b1*L + b2*L^2), L = logit(favourite win chance)
  P(goes to 5 sets)       ~ flat base rate (the model's win chance adds nothing measurable)
Fitted Nov 2026 (held-out: predicted 41.1%, actual 39.9%). Refitted daily by the self-check once enough live
predictions with results exist.
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from ttq.models import AppSetting

DEFAULT = {"a": -0.582, "b1": 0.519, "b2": -0.039, "five_sets": 0.29, "n": 0, "source": "Nov 2026 back-test"}


def params(db: Session | None = None) -> dict:
    if db is not None:
        row = db.get(AppSetting, "set_market_params")
        if row and row.value.get("n", 0) >= 800:
            return row.value
    return DEFAULT


def fav_minus_1_5(p_fav: float, prm: dict | None = None) -> float:
    prm = prm or DEFAULT
    pf = min(max(p_fav, 0.5), 0.98)
    L = math.log(pf / (1 - pf))
    return 1 / (1 + math.exp(-(prm["a"] + prm["b1"] * L + prm["b2"] * L * L)))


def refit(db: Session, pairs: list[tuple[float, int, int, bool]]) -> dict | None:
    """pairs: (favourite win chance, fav sets, dog sets, fav_is_known). Fits on >= 800 live matches."""
    if len(pairs) < 800:
        return None
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    pf = np.clip(np.array([p for p, *_ in pairs]), 0.5, 0.98)
    L = np.log(pf / (1 - pf))
    y = np.array([1 if (fs == 3 and ds <= 1) else 0 for _, fs, ds, _ in pairs])
    five = float(np.mean([1 if fs + ds == 5 else 0 for _, fs, ds, _ in pairs]))
    clf = LogisticRegression(C=1.0).fit(np.c_[L, L * L], y)
    val = {"a": float(clf.intercept_[0]), "b1": float(clf.coef_[0][0]), "b2": float(clf.coef_[0][1]),
           "five_sets": round(five, 4), "n": len(pairs), "source": "live refit"}
    row = db.get(AppSetting, "set_market_params")
    if row:
        row.value = val
    else:
        db.add(AppSetting(key="set_market_params", value=val))
    db.flush()
    return val
