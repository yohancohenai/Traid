"""Walk-forward backtesting on archived out-of-sample predictions and archived, time-stamped quotes.

Decision rule: at decision time T = start - decision_minutes, take the latest Hard Rock quote captured <= T - delay.
Price is reduced by `slippage` (fraction of the decimal payout). The prediction used is the archived out-of-sample
prediction (as_of <= start, from a model whose training ended before the period). Every run is stored, including
losing ones, and the run count is reported so multiple-testing risk is visible.
"""
from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from ttq.core.timeutil import utcnow
from ttq.ml.train import brier, log_loss, reliability
from ttq.models import BacktestRun, Match, ModelVersion, OddsQuote, PaperTrade, Prediction
from ttq.odds.math import clv, expected_value, no_vig_multiplicative
from ttq.services.app_settings import get_setting, set_setting
from ttq.services.audit import audit


def _load(db: Session, is_demo: bool, start=None, end=None, decision_minutes=30, delay_minutes=2):
    preds = db.execute(select(Prediction.match_id, Prediction.p1_win, Prediction.p1_ci_low, Prediction.p1_ci_high,
                              Prediction.component_probs, Prediction.data_quality, Prediction.model_version_id)
                       .where(Prediction.is_backtest.is_(True), Prediction.is_demo == is_demo)).all()
    P = pd.DataFrame(preds, columns=["match_id", "p1", "lo", "hi", "comps", "dq", "mv"]).drop_duplicates("match_id", keep="last")
    ms = db.execute(select(Match.id, Match.scheduled_at, Match.status, Match.sets_p1, Match.sets_p2, Match.result_verified,
                           Match.player1_id, Match.player2_id).where(Match.is_demo == is_demo, Match.id.in_(P["match_id"].tolist()))).all()
    M = pd.DataFrame(ms, columns=["match_id", "sched", "status", "s1", "s2", "verified", "pl1", "pl2"])
    qs = db.execute(select(OddsQuote.match_id, OddsQuote.bookmaker_key, OddsQuote.selection, OddsQuote.decimal_odds,
                           OddsQuote.captured_at, OddsQuote.is_closing)
                    .where(OddsQuote.market == "match_winner", OddsQuote.is_demo == is_demo,
                           OddsQuote.match_id.in_(P["match_id"].tolist()))).all()
    Q = pd.DataFrame(qs, columns=["match_id", "book", "sel", "dec", "cap", "closing"])
    Q["dec"] = Q["dec"].astype(float)
    df = P.merge(M, on="match_id")
    df["sched"] = pd.to_datetime(df["sched"], utc=True)
    if start is not None:
        df = df[df["sched"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["sched"] <= pd.Timestamp(end)]
    Q["cap"] = pd.to_datetime(Q["cap"], utc=True)
    Q = Q.merge(df[["match_id", "sched"]], on="match_id")
    cutoff = Q["sched"] - pd.Timedelta(minutes=decision_minutes + delay_minutes)
    dq = Q[Q["cap"] <= cutoff].sort_values("cap").groupby(["match_id", "book", "sel"]).tail(1)
    cq = Q[Q["closing"]].sort_values("cap").groupby(["match_id", "book", "sel"]).tail(1)

    def wide(x, tag):
        if x.empty:
            return pd.DataFrame(columns=["match_id"])
        w = x.pivot_table(index="match_id", columns=["book", "sel"], values="dec", aggfunc="last")
        w.columns = [f"{tag}_{b}_{s}" for b, s in w.columns]
        return w.reset_index()

    df = df.merge(wide(dq, "dec"), on="match_id", how="left").merge(wide(cq, "close"), on="match_id", how="left")
    return df.sort_values("sched").reset_index(drop=True)


def _simulate(df: pd.DataFrame, F: dict, slippage: float, strategy: str = "model") -> pd.DataFrame:
    rows = []
    for r in df.itertuples(index=False):
        if r.status not in ("FINISHED", "RETIRED", "CANCELLED") or not r.verified and r.status == "FINISHED":
            continue
        h1, h2 = getattr(r, "dec_hardrock_p1", np.nan), getattr(r, "dec_hardrock_p2", np.nan)
        if not (h1 == h1 and h2 == h2):  # missing price -> no bet possible
            continue
        nv = no_vig_multiplicative([h1, h2])
        d1, d2 = getattr(r, "dec_draftkings_p1", np.nan), getattr(r, "dec_draftkings_p2", np.nan)
        dk = no_vig_multiplicative([d1, d2]) if (d1 == d1 and d2 == d2) else None
        for side, idx, dec in (("p1", 0, h1), ("p2", 1, h2)):
            if strategy == "model":
                p = r.p1 if side == "p1" else 1 - r.p1
                lo = r.lo if side == "p1" else 1 - r.hi
                comps = [v if side == "p1" else 1 - v for v in (r.comps or {}).values()] or [p]
                spread = max(comps) - min(comps)
            elif strategy == "elo_only":
                c = (r.comps or {}).get("elo_baseline")
                if c is None:
                    continue
                p = c if side == "p1" else 1 - c
                lo, spread = p, 0
            elif strategy == "glicko_only":
                c = (r.comps or {}).get("glicko2_baseline")
                if c is None:
                    continue
                p = c if side == "p1" else 1 - c
                lo, spread = p, 0
            elif strategy == "market_consensus":
                if dk is None:
                    continue
                p = dk[idx]; lo, spread = p, 0
            else:  # novig: bets only if the book's own no-vig says +EV (should never happen) -> baseline sanity
                p = nv[idx]; lo, spread = p, 0
            exec_dec = 1 + (dec - 1) * (1 - slippage)
            ev = expected_value(p, exec_dec)
            ev_lo = expected_value(lo, exec_dec)
            if ev < F["min_ev"] or (p - nv[idx]) < F["min_edge"] or not (F["min_decimal_odds"] <= exec_dec <= F["max_decimal_odds"]):
                continue
            if strategy == "model" and (ev_lo < F["min_ev_low"] or spread > F["max_model_disagreement"]
                                        or (F["min_data_quality"] == "HIGH" and r.dq != "HIGH")
                                        or (F["min_data_quality"] == "MEDIUM" and r.dq == "LOW")):
                continue
            if r.status != "FINISHED":
                res, profit = "VOID", 0.0
            else:
                won = (r.s1 > r.s2) if side == "p1" else (r.s2 > r.s1)
                res, profit = ("WON", exec_dec - 1) if won else ("LOST", -1.0)
            close = getattr(r, f"close_hardrock_{side}", np.nan)
            rows.append({"match_id": r.match_id, "sched": r.sched, "side": side, "p": p, "dec": exec_dec, "ev": ev,
                         "result": res, "profit": profit, "close": close if close == close else None,
                         "clv": clv(exec_dec, close) if close == close else None, "day": r.sched.date(),
                         "pl1": r.pl1, "pl2": r.pl2})
            break  # at most one side per match
    return pd.DataFrame(rows)


def _metrics(trades: pd.DataFrame, n_boot: int = 1000, seed: int = 0) -> dict:
    if trades.empty:
        return {"bets": 0, "roi": None, "note": "No bets met the filters: NO QUALIFYING BETS in this period."}
    staked = (trades["result"] != "VOID").sum()
    roi = trades["profit"].sum() / staked if staked else None
    curve = trades["profit"].cumsum().values
    peak = np.maximum.accumulate(np.concatenate([[0], curve]))
    dd = float((peak - np.concatenate([[0], curve])).max())
    # Day-block bootstrap (accounts for clustering of bets on the same day / tournament)
    rng = np.random.default_rng(seed)
    days = trades.groupby("day")["profit"].agg(["sum", "count"])
    boots = []
    if len(days) >= 5:
        s, c = days["sum"].values, days["count"].values
        for _ in range(n_boot):
            i = rng.integers(0, len(days), len(days))
            boots.append(s[i].sum() / c[i].sum())
    ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if boots else (None, None)
    p_le_0 = float(np.mean(np.array(boots) <= 0)) if boots else None
    clvs = trades["clv"].dropna()
    return {"bets": int(len(trades)), "staked_units": int(staked), "profit_units": float(trades["profit"].sum()),
            "roi": roi, "roi_ci95": ci, "p_roi_le_0_bootstrap": p_le_0, "win_rate": float((trades["result"] == "WON").mean()),
            "avg_odds": float(trades["dec"].mean()), "avg_ev": float(trades["ev"].mean()),
            "avg_clv": float(clvs.mean()) if len(clvs) else None, "clv_positive_rate": float((clvs > 0).mean()) if len(clvs) else None,
            "max_drawdown_units": dd, "active_days": int(len(days)), "bets_per_day": float(len(trades) / max(len(days), 1)),
            "curve": [{"i": i, "cum": float(v)} for i, v in enumerate(curve)][:: max(1, len(curve) // 300)]}


def run_backtest(db: Session, is_demo: bool, name: str = "walk-forward", filters: dict | None = None,
                 slippage: float = 0.01, decision_minutes: int = 30, delay_minutes: int = 2,
                 period: str = "test", store_trades: bool = True) -> dict:
    F = {**get_setting(db, "filters"), **(filters or {})}
    champ = db.scalar(select(ModelVersion).where(ModelVersion.status == "CHAMPION", ModelVersion.is_demo == is_demo))
    if not champ:
        return {"status": "NO_MODEL"}
    sp = champ.splits.get(period) if champ.splits else None
    start, end = (sp["start"], sp["end"]) if sp else (None, None)
    df = _load(db, is_demo, start, end, decision_minutes, delay_minutes)
    if df.empty:
        return {"status": "NO_DATA"}
    y = (df.loc[df["status"] == "FINISHED", "s1"] > df.loc[df["status"] == "FINISHED", "s2"]).astype(float).values
    pf = df.loc[df["status"] == "FINISHED", "p1"].values
    fin = df[df["status"] == "FINISHED"]
    have_mkt = fin.dropna(subset=["dec_hardrock_p1", "dec_hardrock_p2"])
    mkt_p = np.array([no_vig_multiplicative([a, b])[0] for a, b in zip(have_mkt["dec_hardrock_p1"], have_mkt["dec_hardrock_p2"])])
    y_m = (have_mkt["s1"] > have_mkt["s2"]).astype(float).values
    prob_metrics = {
        "n": int(len(y)), "model": {"brier": brier(y, pf), "log_loss": log_loss(y, pf)},
        "model_on_priced": {"n": int(len(y_m)), "brier": brier(y_m, have_mkt["p1"].values) if len(y_m) else None,
                            "log_loss": log_loss(y_m, have_mkt["p1"].values) if len(y_m) else None},
        "hardrock_novig_on_priced": {"brier": brier(y_m, mkt_p) if len(y_m) else None,
                                     "log_loss": log_loss(y_m, mkt_p) if len(y_m) else None},
        "reliability": reliability(y, pf)[0],
    }
    strategies = {}
    for strat in ("model", "elo_only", "glicko_only", "market_consensus", "novig"):
        t = _simulate(df, F, slippage, strat)
        strategies[strat] = _metrics(t)
        if strat == "model":
            model_trades = t
    sens = {}
    for s in (0.0, 0.02, 0.04):
        sens[f"slippage_{s}"] = _metrics(_simulate(df, F, s, "model"), n_boot=200).get("roi")
    m = strategies["model"]
    if m["bets"] >= 200 and m.get("roi_ci95", (None,))[0] is not None and m["roi_ci95"][0] > 0:
        outcome = "POSITIVE"
    elif m["bets"] >= 200 and m.get("roi_ci95", (None, None))[1] is not None and m["roi_ci95"][1] < 0:
        outcome = "NEGATIVE"
    else:
        outcome = "INCONCLUSIVE"
    n_runs = (db.scalar(select(func.count(BacktestRun.id)).where(BacktestRun.is_demo == is_demo)) or 0) + 1
    metrics = {"probability": prob_metrics, "strategies": strategies, "slippage_sensitivity": sens,
               "model_version": f"{champ.name}@{champ.version}", "period": period,
               "multiple_testing": {"runs_so_far": n_runs,
                                    "note": "Each extra configuration tried raises the chance of a false positive. Treat "
                                            "a single positive run among many as weak evidence."},
               "demo_warning": "DEMO synthetic data: results say nothing about real-world profitability." if is_demo else None}
    run = BacktestRun(name=name, config={"filters": F, "slippage": slippage, "decision_minutes": decision_minutes,
                                         "delay_minutes": delay_minutes, "period": period},
                      metrics=metrics, period_start=pd.Timestamp(start).to_pydatetime() if start else None,
                      period_end=pd.Timestamp(end).to_pydatetime() if end else None, outcome=outcome, is_demo=is_demo)
    db.add(run)
    db.flush()
    if store_trades and not model_trades.empty:
        db.execute(insert(PaperTrade), [{"backtest_run_id": run.id, "match_id": int(r.match_id), "decided_at": r.sched.to_pydatetime() - timedelta(minutes=decision_minutes),
                                         "selection": r.side, "decimal_odds": float(r.dec), "model_prob": float(r.p), "ev": float(r.ev),
                                         "closing_decimal": r.close, "result": r.result, "profit_units": float(r.profit), "is_demo": is_demo}
                                        for r in model_trades.itertuples()])
    audit(db, "system", "backtest_run", "backtest_run", run.id, outcome=outcome, period=period)
    return {"status": "OK", "id": run.id, "outcome": outcome, "metrics": metrics}


def select_filters(db: Session, is_demo: bool, actor: str = "system") -> dict:
    """Choose min_ev / min_edge on the CALIB period (never TEST). Objective: bootstrap lower bound of ROI with a
    minimum bet count, which penalises overfitting to a lucky threshold."""
    grid = [(ev, ed) for ev in (0.02, 0.03, 0.05, 0.08) for ed in (0.01, 0.02, 0.04)]
    best, best_score, table = None, -math.inf, []
    champ = db.scalar(select(ModelVersion).where(ModelVersion.status == "CHAMPION", ModelVersion.is_demo == is_demo))
    if not champ:
        return {"status": "NO_MODEL"}
    sp = champ.splits["calib"]
    df = _load(db, is_demo, sp["start"], sp["end"])
    base = get_setting(db, "filters")
    for ev, ed in grid:
        F = {**base, "min_ev": ev, "min_edge": ed}
        m = _metrics(_simulate(df, F, 0.01, "model"), n_boot=300)
        lo = m.get("roi_ci95", (None,))[0] if m["bets"] >= 50 else None
        table.append({"min_ev": ev, "min_edge": ed, "bets": m["bets"], "roi": m.get("roi"), "roi_ci_low": lo})
        if lo is not None and lo > best_score:
            best_score, best = lo, (ev, ed)
    if best is None:
        return {"status": "NO_CANDIDATE", "grid": table}
    set_setting(db, "filters", {"min_ev": best[0], "min_edge": best[1], "selected_by": f"calib-period grid ({sp['start'][:10]}..{sp['end'][:10]})"})
    audit(db, actor, "filters_selected", "app_settings", "filters", choice=best, score=best_score)
    return {"status": "OK", "chosen": {"min_ev": best[0], "min_edge": best[1]}, "grid": table}
