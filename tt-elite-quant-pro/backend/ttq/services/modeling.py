"""Glue between the database and the rating / ML / simulation engines."""
from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session, selectinload

from ttq.core.config import get_settings
from ttq.core.timeutil import as_utc, utcnow
from ttq.features.builder import FeatureBuilder, MatchRecord, build_dataset, data_quality
from ttq.ml.train import TrainedModel, logit, sigmoid, train_all
from ttq.models import Match, ModelVersion, OddsQuote, Player, Prediction, RatingSnapshot
from ttq.odds.math import no_vig_multiplicative
from ttq.services.app_settings import get_filters, get_setting
from ttq.services.audit import audit
from ttq.sim.tt import full_match_model

log = logging.getLogger(__name__)
MIN_TRAIN_MATCHES = 1500
COMPONENTS = ["elo_baseline", "glicko2_baseline", "bayes_hier", "logreg", "lightgbm", "catboost"]


def load_records(db: Session, is_demo: bool, until: datetime | None = None) -> list[MatchRecord]:
    q = select(Match).options(selectinload(Match.sets), selectinload(Match.tournament)).where(Match.is_demo == is_demo)
    if until is not None:
        q = q.where(Match.scheduled_at <= until)
    out = []
    for m in db.scalars(q).all():
        won = None
        if m.status == "FINISHED" and m.winner_id is not None and m.sets_p1 is not None:
            won = m.winner_id == m.player1_id
        out.append(MatchRecord(
            id=m.id, p1=m.player1_id, p2=m.player2_id, scheduled_at=as_utc(m.scheduled_at),
            finished_at=as_utc(m.finished_at), status=m.status if won is not None or m.status != "FINISHED" else "UNVERIFIED",
            p1_won=won, sets_p1=m.sets_p1, sets_p2=m.sets_p2,
            set_points=[(s.p1_points, s.p2_points) for s in m.sets if s.p1_points is not None],
            tournament_level=m.tournament.level if m.tournament else "standard", is_demo=m.is_demo))
    return out


def market_frame(db: Session, is_demo: bool, decision_minutes: int = 30) -> pd.DataFrame:
    """No-vig market probability for player 1 at decision time (latest quote captured >= decision_minutes before
    start), plus the closing no-vig probability. Hard Rock first, otherwise any reference book."""
    rows = db.execute(select(OddsQuote.match_id, OddsQuote.bookmaker_key, OddsQuote.selection, OddsQuote.decimal_odds,
                             OddsQuote.captured_at, OddsQuote.is_closing, Match.scheduled_at)
                      .join(Match, Match.id == OddsQuote.match_id)
                      .where(OddsQuote.market == "match_winner", OddsQuote.is_demo == is_demo)).all()
    if not rows:
        return pd.DataFrame(columns=["match_id", "mkt_p1", "close_p1", "hr_dec_p1", "hr_dec_p2", "hr_close_p1", "hr_close_p2"])
    q = pd.DataFrame(rows, columns=["match_id", "book", "sel", "dec", "cap", "closing", "sched"])
    q["dec"] = q["dec"].astype(float)
    q["cap"] = pd.to_datetime(q["cap"], utc=True)
    q["sched"] = pd.to_datetime(q["sched"], utc=True)
    dec = q[q["cap"] <= q["sched"] - pd.Timedelta(minutes=decision_minutes)]
    out = {}

    def piv(frame, tag):
        last = frame.sort_values("cap").groupby(["match_id", "book", "sel"]).tail(1)
        return last.pivot_table(index=["match_id", "book"], columns="sel", values="dec", aggfunc="last")

    for tag, frame in (("dec", dec), ("close", q[q["closing"]])):
        if frame.empty:
            continue
        pv = piv(frame, tag).dropna()
        for (mid, book), r in pv.iterrows():
            d = out.setdefault(mid, {})
            d[f"{book}_{tag}"] = (r.get("p1"), r.get("p2"))
    recs = []
    for mid, d in out.items():
        rec = {"match_id": mid}
        for tag, col in (("dec", "mkt_p1"), ("close", "close_p1")):
            pair = d.get(f"hardrock_{tag}") or d.get(f"draftkings_{tag}")
            rec[col] = no_vig_multiplicative(list(pair))[0] if pair else np.nan
            hr = d.get(f"hardrock_{tag}")
            rec[f"hr_{tag}_p1"], rec[f"hr_{tag}_p2"] = (hr if hr else (np.nan, np.nan))
        recs.append(rec)
    return pd.DataFrame(recs)


def build_features(db: Session, is_demo: bool, store_snapshots: bool = False) -> tuple[pd.DataFrame, FeatureBuilder]:
    recs = load_records(db, is_demo)
    snaps = []
    keep = ("elo", "glicko2", "bayes")

    def cb(m, fb, t):
        if not store_snapshots or not m.counts_for_rating:
            return
        for pid in (m.p1, m.p2):
            for k in keep:
                r, u, n = fb.engines[k].rating(pid)
                snaps.append({"player_id": pid, "model": k, "as_of": t, "match_id": m.id, "rating": r,
                              "uncertainty": u, "games": n})

    df, fb = build_dataset(recs, snapshot_cb=cb)
    if store_snapshots:
        db.execute(delete(RatingSnapshot).where(RatingSnapshot.player_id.in_(select(Player.id).where(Player.is_demo == is_demo))))
        for i in range(0, len(snaps), 5000):
            db.execute(insert(RatingSnapshot), snaps[i:i + 5000])
    mk = market_frame(db, is_demo)
    if not df.empty and not mk.empty:
        df = df.merge(mk, on="match_id", how="left")
    return df, fb


def artifact_path(name: str) -> str:
    d = get_settings().artifacts_dir
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def train_and_register(db: Session, is_demo: bool, actor: str = "system", fast: bool = False,
                       promote: str = "auto") -> dict:
    """Train all candidates. promote: 'auto' (promote only if no champion exists, or the challenger beats the
    champion on the shared CALIB period by the configured margin), 'never', or 'force'."""
    df, fb = build_features(db, is_demo, store_snapshots=True)
    labeled = int(df["y"].notna().sum()) if not df.empty else 0
    if labeled < MIN_TRAIN_MATCHES:
        return {"status": "INSUFFICIENT_DATA", "labeled_matches": labeled, "required": MIN_TRAIN_MATCHES}
    res = train_all(df, fast=fast)
    version = utcnow().strftime("%Y%m%d%H%M%S")
    path = artifact_path(f"run_{'demo' if is_demo else 'live'}_{version}.joblib")
    joblib.dump({"models": res["models"], "features": res["features"]}, path)
    cutoff = pd.to_datetime(res["splits"]["test"]["end"], utc=True).to_pydatetime() if res["splits"]["test"]["n"] else None
    rows = {}
    for name, tm in res["models"].items():
        mv = ModelVersion(name=name, kind=type(tm.model).__name__, version=version, status="CANDIDATE",
                          params=res["params"].get(name, {}), features=tm.feats, metrics=tm.metrics,
                          splits=res["splits"], artifact_path=path, train_cutoff=cutoff, is_demo=is_demo,
                          notes=f"ablation={res['ablation']['groups']}" if name == res["champion"] else None)
        db.add(mv)
        rows[name] = mv
    db.flush()
    current = db.scalar(select(ModelVersion).where(ModelVersion.status == "CHAMPION", ModelVersion.is_demo == is_demo))
    challenger = rows[res["champion"]]
    decision = "kept_existing"
    margin = get_setting(db, "monitoring")["promotion_min_logloss_gain"]
    if promote == "force" or (promote == "auto" and current is None):
        decision = "promoted"
    elif promote == "auto" and current is not None:
        # Compare on the challenger's CALIB period (out-of-sample for both, since champion was trained earlier)
        cur_ll = evaluate_existing_on(db, current, df, res["splits"]["calib"])
        new_ll = challenger.metrics["calib"]["log_loss"]
        challenger.metrics = {**challenger.metrics, "promotion_check": {"champion_ll": cur_ll, "challenger_ll": new_ll, "required_gain": margin}}
        if cur_ll is None or new_ll < cur_ll - margin:
            decision = "promoted"
    if decision == "promoted":
        if current:
            current.status = "RETIRED"
        challenger.status = "CHAMPION"
        challenger.promoted_at = utcnow()
    audit(db, actor, "train_models", "model_version", challenger.id, decision=decision, version=version,
          champion_candidate=res["champion"], is_demo=is_demo)
    # Store out-of-sample predictions for calib+test periods (archived; used for monitoring and backtests)
    store_oos_predictions(db, df, res, rows, is_demo)
    return {"status": "OK", "version": version, "best_candidate": res["champion"], "decision": decision,
            "features": res["features"], "ablation": res["ablation"], "splits": res["splits"],
            "metrics": {k: {"calib_ll": v.metrics["calib"]["log_loss"], "test_ll": v.metrics["test"]["log_loss"],
                            "test_brier": v.metrics["test"]["brier"], "test_acc": v.metrics["test"]["accuracy"]}
                        for k, v in res["models"].items()}}


def evaluate_existing_on(db, mv: ModelVersion, df: pd.DataFrame, period: dict) -> float | None:
    from ttq.ml.train import log_loss
    try:
        art = joblib.load(mv.artifact_path)
    except Exception:  # noqa
        return None
    tm: TrainedModel = art["models"][mv.name]
    s, e = pd.to_datetime(period["start"], utc=True), pd.to_datetime(period["end"], utc=True)
    d = df[(df["y"].notna()) & (pd.to_datetime(df["scheduled_at"], utc=True) >= s) & (pd.to_datetime(df["scheduled_at"], utc=True) <= e)]
    if d.empty:
        return None
    return log_loss(d["y"].values, tm.predict(d))


def store_oos_predictions(db, df, res, rows, is_demo):
    from ttq.services.modeling import uncertainty_interval
    champ = res["models"][res["champion"]]
    period_ids = set()
    for k in ("calib", "test"):
        s, e = pd.to_datetime(res["splits"][k]["start"], utc=True), pd.to_datetime(res["splits"][k]["end"], utc=True)
        sched = pd.to_datetime(df["scheduled_at"], utc=True)
        period_ids |= set(df[(sched >= s) & (sched <= e) & df["y"].notna()]["match_id"])
    d = df[df["match_id"].isin(period_ids)]
    if d.empty:
        return
    p = champ.predict(d)
    comps = {c: res["models"][c].predict(d) for c in COMPONENTS if c in res["models"]}
    recs = []
    for i, (_, r) in enumerate(d.iterrows()):
        cp = {c: float(v[i]) for c, v in comps.items()}
        lo, hi = uncertainty_interval(float(p[i]), float(r["bayes_sd"]), list(cp.values()), 0.5)
        recs.append({"match_id": int(r["match_id"]), "model_version_id": rows[res["champion"]].id,
                     "as_of": r["scheduled_at"], "created_at": utcnow(), "p1_win": float(p[i]), "p1_ci_low": lo,
                     "p1_ci_high": hi, "component_probs": cp, "features": {}, "scorelines": {},
                     "data_quality": data_quality(int(r["_n1"]), int(r["_n2"]), float(r["pts_coverage"])),
                     "is_backtest": True, "is_demo": is_demo})
    for i in range(0, len(recs), 2000):
        db.execute(insert(Prediction), recs[i:i + 2000])


def uncertainty_interval(p: float, bayes_sd: float, component_probs: list[float], scale: float, z: float = 1.645):
    """Heuristic 90% interval for the probability estimate: posterior strength uncertainty (Bayesian model)
    scaled by `scale`, combined with between-model disagreement, applied on the logit scale."""
    comp = np.array([logit(x) for x in component_probs]) if component_probs else np.array([0.0])
    dis = float(comp.std()) if len(comp) > 1 else 0.0
    w = z * math.sqrt((scale * bayes_sd) ** 2 + dis ** 2)
    c = float(logit(p))
    return float(sigmoid(c - w)), float(sigmoid(c + w))


def load_champion(db: Session, is_demo: bool) -> tuple[ModelVersion | None, dict | None]:
    mv = db.scalar(select(ModelVersion).where(ModelVersion.status == "CHAMPION", ModelVersion.is_demo == is_demo))
    if not mv:
        return None, None
    try:
        return mv, joblib.load(mv.artifact_path)
    except Exception:  # noqa
        log.exception("champion artifact missing")
        return mv, None


def predict_upcoming(db: Session, is_demo: bool, horizon_hours: int = 48) -> dict:
    """Create fresh (append-only) predictions for scheduled matches within the horizon."""
    mv, art = load_champion(db, is_demo)
    if not mv or not art:
        return {"status": "NO_CHAMPION", "predicted": 0}
    now = utcnow()
    df, fb = build_features(db, is_demo)
    if df.empty:
        return {"status": "OK", "predicted": 0}
    sched = pd.to_datetime(df["scheduled_at"], utc=True)
    up = df[(df["status"] == "SCHEDULED") & (sched > now) & (sched <= now + timedelta(hours=horizon_hours))]
    if up.empty:
        return {"status": "OK", "predicted": 0}
    models = art["models"]
    champ: TrainedModel = models[mv.name]
    p = champ.predict(up)
    comps = {c: models[c].predict(up) for c in COMPONENTS if c in models}
    scale = get_filters(db, is_demo)["uncertainty_scale"]
    n = 0
    for i, (_, r) in enumerate(up.iterrows()):
        cp = {c: float(v[i]) for c, v in comps.items()}
        pi = float(np.clip(p[i], 0.01, 0.99))
        lo, hi = uncertainty_interval(pi, float(r["bayes_sd"]), list(cp.values()), scale)
        fm = full_match_model(pi, with_points=False)
        feats = {k: (None if (isinstance(v, float) and math.isnan(v)) else (float(v) if isinstance(v, (int, float, np.floating, np.integer)) else str(v)))
                 for k, v in r.items() if k not in ("scheduled_at",)}
        db.add(Prediction(match_id=int(r["match_id"]), model_version_id=mv.id, as_of=now, p1_win=pi, p1_ci_low=lo,
                          p1_ci_high=hi, p_set=fm["p_game"], scorelines=fm["scorelines"], component_probs=cp,
                          features=feats, data_quality=data_quality(int(r["_n1"]), int(r["_n2"]), float(r["pts_coverage"])),
                          is_demo=is_demo))
        n += 1
    db.flush()
    return {"status": "OK", "predicted": n, "model": mv.name, "version": mv.version}


def latest_prediction(db: Session, match_id: int, backtest: bool = False) -> Prediction | None:
    return db.scalar(select(Prediction).where(Prediction.match_id == match_id, Prediction.is_backtest == backtest)
                     .order_by(Prediction.created_at.desc(), Prediction.id.desc()).limit(1))
