"""Model monitoring: rolling calibration of the live champion on settled matches, drift detection, retrain gating."""
from __future__ import annotations

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ttq.ml.train import brier, log_loss, reliability
from ttq.models import Match, ModelVersion, Prediction
from ttq.services.app_settings import get_setting


def first_predictions(db: Session, is_demo: bool, live_only: bool = True):
    """For each finished match: the LAST pre-match prediction (as_of <= start), never later ones."""
    q = (select(Prediction, Match).join(Match, Match.id == Prediction.match_id)
         .where(Match.status == "FINISHED", Match.result_verified.is_(True), Match.is_demo == is_demo,
                Prediction.as_of <= Match.scheduled_at))
    if live_only:
        q = q.where(Prediction.is_backtest.is_(False))
    best = {}
    for p, m in db.execute(q).all():
        if m.id not in best or p.as_of > best[m.id][0].as_of:
            best[m.id] = (p, m)
    return sorted(best.values(), key=lambda x: x[1].scheduled_at)


def model_health(db: Session, is_demo: bool) -> dict:
    cfg = get_setting(db, "monitoring")
    champ = db.scalar(select(ModelVersion).where(ModelVersion.status == "CHAMPION", ModelVersion.is_demo == is_demo))
    pairs = first_predictions(db, is_demo, live_only=True)
    source = "live_predictions"
    if len(pairs) < 50:
        pairs = first_predictions(db, is_demo, live_only=False)
        source = "archived_out_of_sample"
    if not pairs:
        return {"status": "NO_DATA", "champion": champ.name if champ else None}
    y = np.array([1.0 if m.winner_id == m.player1_id else 0.0 for _, m in pairs])
    p = np.array([pr.p1_win for pr, _ in pairs])
    W = cfg["drift_window"]
    recent = slice(max(0, len(y) - W), len(y))
    ref_ll = champ.metrics.get("calib", {}).get("log_loss") if champ else None
    rec_ll = log_loss(y[recent], p[recent])
    drift = ref_ll is not None and rec_ll > ref_ll + cfg["drift_logloss_tolerance"]
    # Scoreline validation: does the exact game model match observed scorelines?
    sl_ll = []
    for pr, m in pairs[-W:]:
        if pr.scorelines and m.sets_p1 is not None:
            sl_ll.append(-np.log(max(pr.scorelines.get(f"{m.sets_p1}-{m.sets_p2}", 1e-6), 1e-6)))
    rolling = []
    step = max(50, len(y) // 30)
    for i in range(step, len(y) + 1, step):
        rolling.append({"n": i, "at": pairs[i - 1][1].scheduled_at.isoformat(),
                        "log_loss": log_loss(y[i - step:i], p[i - step:i]), "brier": brier(y[i - step:i], p[i - step:i])})
    return {"status": "DRIFT" if drift else "OK", "source": source, "n": int(len(y)),
            "champion": f"{champ.name}@{champ.version}" if champ else None,
            "reference_log_loss": ref_ll, "recent_log_loss": rec_ll, "recent_brier": brier(y[recent], p[recent]),
            "recent_accuracy": float(np.mean((p[recent] >= 0.5) == (y[recent] == 1))),
            "reliability": reliability(y[recent], p[recent])[0], "rolling": rolling,
            "scoreline_log_loss": float(np.mean(sl_ll)) if sl_ll else None,
            "scoreline_uniform_log_loss": float(np.log(6)) if sl_ll else None}


def retrain_due(db: Session, is_demo: bool) -> tuple[bool, str]:
    cfg = get_setting(db, "monitoring")
    champ = db.scalar(select(ModelVersion).where(ModelVersion.status == "CHAMPION", ModelVersion.is_demo == is_demo))
    if not champ:
        return True, "no champion"
    new = db.scalar(select(func.count(Match.id)).where(Match.is_demo == is_demo, Match.status == "FINISHED",
                                                       Match.finished_at > champ.trained_at))
    if new >= cfg["retrain_min_new_matches"]:
        return True, f"{new} new verified matches since last training"
    h = model_health(db, is_demo)
    if h.get("status") == "DRIFT":
        return True, "calibration drift detected"
    return False, f"{new} new matches (< {cfg['retrain_min_new_matches']}), no drift"
