"""Bets, bankroll, backtests, models, data sources, settings, alerts, audit, jobs."""
from __future__ import annotations

import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ttq.api.serialize import iso, match_brief, row
from ttq.core.db import get_db
from ttq.core.security import current_user
from ttq.core.timeutil import utcnow
from ttq.models import (Alert, AuditLog, BacktestRun, BankrollTransaction, Bet, BetRevision, DataSource, JobRun, Match,
                        ModelVersion, PaperTrade, Recommendation, SettlementProposal)
from ttq.providers.base import ProviderUnavailable
from ttq.providers.csv_import import parse_results_csv
from ttq.providers.registry import CATALOGUE
from ttq.services import backtest as bt_svc
from ttq.services import bets as bet_svc
from ttq.services import jobs, monitoring, performance, settlement
from ttq.services.app_settings import DEFAULTS, get_setting, set_setting
from ttq.services.audit import audit

router = APIRouter(dependencies=[Depends(current_user)])


# ---------------------------------------------------------------- bets (ledger A)
class BetIn(BaseModel):
    match_id: int
    market: str = Field("match_winner", pattern="^(match_winner|set_handicap|point_handicap|total_points|correct_score|set_winner)$")
    selection: str = Field(min_length=1, max_length=16)
    line: float | None = None
    accepted_american: int | None = None
    accepted_decimal: float | None = Field(None, gt=1.0, le=1001)
    stake: float = Field(gt=0, le=1_000_000)
    placed_at: datetime | None = None
    bet_ref: str | None = Field(None, max_length=128)
    notes: str | None = Field(None, max_length=2000)
    recommendation_id: int | None = None
    client_request_id: str | None = Field(None, max_length=64)
    override_risk: bool = False
    allow_duplicate: bool = False

    @model_validator(mode="after")
    def _odds(self):
        if self.accepted_american is None and self.accepted_decimal is None:
            raise ValueError("accepted odds are required")
        if self.accepted_american is not None and -100 < self.accepted_american < 100:
            raise ValueError("American odds must be <= -100 or >= +100")
        return self


@router.post("/bets", status_code=201)
def create_bet(body: BetIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    try:
        res = bet_svc.confirm_bet(db, actor=user, **body.model_dump())
    except bet_svc.BetError as e:
        db.rollback()
        raise HTTPException(e.code, {"message": str(e), **e.detail})
    db.commit()
    return res


@router.get("/bets")
def list_bets(demo: bool = False, status: str | None = None, db: Session = Depends(get_db)):
    rows = performance.bets_frame(db, demo)
    if status:
        rows = [r for r in rows if r["status"] in status.upper().split(",")]
    return [{k: (iso(v) if isinstance(v, datetime) else v) for k, v in r.items()} for r in reversed(rows)]


@router.get("/bets/{bet_id}")
def get_bet(bet_id: int, db: Session = Depends(get_db)):
    b = db.get(Bet, bet_id)
    if not b:
        raise HTTPException(404, "bet not found")
    return {"bet": row(b), "match": match_brief(db.get(Match, b.match_id)),
            "revisions": [row(r) for r in db.scalars(select(BetRevision).where(BetRevision.bet_id == bet_id).order_by(BetRevision.changed_at))],
            "settlements": [row(p) for p in db.scalars(select(SettlementProposal).where(SettlementProposal.bet_id == bet_id).order_by(SettlementProposal.created_at))]}


class BetCorrection(BaseModel):
    changes: dict
    reason: str = Field(min_length=3, max_length=1000)


@router.patch("/bets/{bet_id}")
def patch_bet(bet_id: int, body: BetCorrection, db: Session = Depends(get_db), user: str = Depends(current_user)):
    try:
        out = bet_svc.correct_bet(db, bet_id, body.changes, body.reason, user)
    except (bet_svc.BetError, ValueError) as e:
        db.rollback()
        raise HTTPException(getattr(e, "code", 422), str(e))
    db.commit()
    return out


class SettleIn(BaseModel):
    result: str = Field(pattern="^(WON|LOST|PUSH|VOID)$")
    note: str | None = None


@router.post("/bets/{bet_id}/settle")
def settle_bet(bet_id: int, body: SettleIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    try:
        b = settlement.resolve_review(db, bet_id, body.result, user, body.note)
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return row(b)


# ---------------------------------------------------------------- bankroll & ledgers
@router.get("/bankroll")
def bankroll(demo: bool = False, db: Session = Depends(get_db)):
    return {"summary": performance.summary(db, demo), "risk": get_setting(db, "risk"),
            "recommendations_ledger": performance.recommendations_ledger(db, demo)}


class TxIn(BaseModel):
    kind: str = Field(pattern="^(DEPOSIT|WITHDRAWAL|ADJUSTMENT)$")
    amount: float = Field(gt=0, le=10_000_000)
    note: str | None = None
    demo: bool = False


@router.post("/bankroll/transactions", status_code=201)
def add_tx(body: TxIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    amt = body.amount if body.kind in ("DEPOSIT", "ADJUSTMENT") else -body.amount
    t = BankrollTransaction(kind=body.kind, amount=round(amt, 2), note=body.note, is_demo=body.demo)
    db.add(t)
    audit(db, user, "bankroll_tx", "bankroll_transaction", None, kind=body.kind, amount=amt)
    db.commit()
    return row(t)


@router.get("/bankroll/export.csv", response_class=PlainTextResponse)
def export(demo: bool = False, db: Session = Depends(get_db)):
    return PlainTextResponse(performance.export_csv(db, demo), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=ttq_bets_{'demo' if demo else 'actual'}.csv"})


class StakeSimIn(BaseModel):
    bankroll: float = Field(gt=0)
    prob: float = Field(gt=0, lt=1)
    decimal_odds: float = Field(gt=1)
    prob_low: float | None = Field(None, gt=0, lt=1)
    prob_high: float | None = Field(None, gt=0, lt=1)


@router.post("/bankroll/stake-sim")
def stake_sim(body: StakeSimIn, db: Session = Depends(get_db)):
    R = get_setting(db, "risk")
    return performance.stake_simulation(body.bankroll, body.prob, body.decimal_odds, body.prob_low, body.prob_high,
                                        R["kelly_fraction"], R["fixed_stake"], R["fixed_pct"], R["max_stake"])


@router.get("/ledgers/paper")
def paper(run_id: int | None = None, demo: bool = False, db: Session = Depends(get_db)):
    q = select(PaperTrade).where(PaperTrade.is_demo == demo)
    if run_id:
        q = q.where(PaperTrade.backtest_run_id == run_id)
    ts = db.scalars(q.order_by(PaperTrade.decided_at.desc()).limit(500)).all()
    return {"ledger": "PAPER_TRADING (hypothetical, never real money)", "items": [row(t) for t in ts]}


# ---------------------------------------------------------------- backtests
class BacktestIn(BaseModel):
    name: str = "manual run"
    demo: bool = False
    period: str = Field("test", pattern="^(tune|calib|test)$")
    slippage: float = Field(0.01, ge=0, le=0.2)
    decision_minutes: int = Field(30, ge=0, le=1440)
    delay_minutes: int = Field(2, ge=0, le=120)
    filters: dict | None = None


@router.get("/backtests")
def backtests(demo: bool = False, db: Session = Depends(get_db)):
    rs = db.scalars(select(BacktestRun).where(BacktestRun.is_demo == demo).order_by(BacktestRun.created_at.desc()).limit(100)).all()
    return [{"id": r.id, "name": r.name, "created_at": iso(r.created_at), "outcome": r.outcome, "config": r.config,
             "model": r.metrics.get("model_version"), "bets": r.metrics.get("strategies", {}).get("model", {}).get("bets"),
             "roi": r.metrics.get("strategies", {}).get("model", {}).get("roi")} for r in rs]


@router.get("/backtests/{rid}")
def backtest_detail(rid: int, db: Session = Depends(get_db)):
    r = db.get(BacktestRun, rid)
    if not r:
        raise HTTPException(404, "not found")
    return row(r)


@router.post("/backtests")
def run_bt(body: BacktestIn, db: Session = Depends(get_db)):
    res = bt_svc.run_backtest(db, body.demo, body.name, body.filters, body.slippage, body.decision_minutes,
                              body.delay_minutes, body.period)
    db.commit()
    return res


@router.post("/backtests/select-filters")
def select_filters(demo: bool = False, db: Session = Depends(get_db), user: str = Depends(current_user)):
    res = bt_svc.select_filters(db, demo, user)
    db.commit()
    return res


# ---------------------------------------------------------------- models
@router.get("/models")
def models(demo: bool = False, db: Session = Depends(get_db)):
    ms = db.scalars(select(ModelVersion).where(ModelVersion.is_demo == demo).order_by(ModelVersion.trained_at.desc()).limit(200)).all()
    return [{"id": m.id, "name": m.name, "kind": m.kind, "version": m.version, "status": m.status, "trained_at": iso(m.trained_at),
             "promoted_at": iso(m.promoted_at), "features": m.features, "params": m.params, "splits": m.splits,
             "metrics": m.metrics, "notes": m.notes} for m in ms]


@router.get("/models/health")
def health(demo: bool = False, db: Session = Depends(get_db)):
    due, why = monitoring.retrain_due(db, demo)
    return {**monitoring.model_health(db, demo), "retrain_due": due, "retrain_reason": why}


_training = threading.Lock()


@router.post("/models/train")
def train(demo: bool = False, user: str = Depends(current_user)):
    if not _training.acquire(blocking=False):
        raise HTTPException(409, "training already running")

    def work():
        try:
            from ttq.services.modeling import train_and_register
            jobs.run_job("train_manual", lambda db: train_and_register(db, demo, actor=user, promote="auto"))
        finally:
            _training.release()
    threading.Thread(target=work, daemon=True).start()
    return {"status": "STARTED", "note": "Challenger is promoted only if it beats the champion out-of-sample."}


@router.post("/models/{mid}/promote")
def promote(mid: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    m = db.get(ModelVersion, mid)
    if not m or m.status == "REJECTED":
        raise HTTPException(404, "model not found")
    for c in db.scalars(select(ModelVersion).where(ModelVersion.status == "CHAMPION", ModelVersion.is_demo == m.is_demo)):
        c.status = "RETIRED"
    m.status, m.promoted_at = "CHAMPION", utcnow()
    audit(db, user, "model_promote_manual", "model_version", mid, name=m.name, version=m.version)
    db.commit()
    return {"id": m.id, "status": m.status}


# ---------------------------------------------------------------- data sources & jobs
@router.get("/sources")
def sources(db: Session = Depends(get_db)):
    st = {s.key: row(s) for s in db.scalars(select(DataSource))}
    runs = db.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(40)).all()
    return {"catalogue": [{**c, "runtime": st.get(c["key"])} for c in CATALOGUE],
            "jobs": [{"job": r.job, "started_at": iso(r.started_at), "finished_at": iso(r.finished_at), "ok": r.ok,
                      "detail": r.detail} for r in runs]}


JOBS = {"ingest_results": jobs.ingest_results_job, "ingest_odds": jobs.ingest_odds_job, "predict_scan": jobs.predict_scan_job,
        "settle": jobs.settle_job, "monitor": jobs.monitor_job, "retrain": jobs.retrain_job}


@router.post("/jobs/{name}")
def run_named_job(name: str, user: str = Depends(current_user)):
    if name not in JOBS:
        raise HTTPException(404, "unknown job")
    return jobs.run_job(name, JOBS[name])


@router.post("/sources/the-odds-api/discover")
def discover():
    from ttq.providers.the_odds_api import TheOddsApiProvider
    try:
        return {"table_tennis_sports": TheOddsApiProvider().discover_sports()}
    except ProviderUnavailable as e:
        raise HTTPException(424, str(e))


@router.post("/import/results-csv")
async def import_results(file: UploadFile, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from ttq.providers.base import ResultsProvider
    from ttq.services.ingest import ensure_source, save_raw, upsert_match
    text = (await file.read()).decode("utf-8-sig")
    try:
        ms = parse_results_csv(text)
    except KeyError as e:
        raise HTTPException(422, f"CSV is missing required column {e}. See the documented header in the import help.")
    except (ValueError, TypeError) as e:
        raise HTTPException(422, f"CSV has an invalid value: {e}")

    class CsvProvider(ResultsProvider):
        key, name, is_demo, verified = "csv_import", "CSV import", False, False

    p = CsvProvider()
    ensure_source(db, p.key, p.name, "results", False)
    save_raw(db, p.key, f"upload:{file.filename}", {"rows": len(ms), "text": text[:200000]}, False)
    counts = {}
    for pm in ms:
        _, st = upsert_match(db, pm, p)
        counts[st] = counts.get(st, 0) + 1
    audit(db, user, "results_csv_import", "match", None, **counts)
    db.commit()
    return {"rows": len(ms), **counts,
            "note": "CSV results are UNVERIFIED unless confirmed by a second source; settlements from them go to review."}


# ---------------------------------------------------------------- settings
@router.get("/settings")
def all_settings(db: Session = Depends(get_db)):
    return {**{k: get_setting(db, k) for k in DEFAULTS}, "filters_demo": get_setting(db, "filters_demo")}


@router.put("/settings/{key}")
def put_setting(key: str, value: dict, db: Session = Depends(get_db), user: str = Depends(current_user)):
    if key not in DEFAULTS and key != "filters_demo":
        raise HTTPException(404, "unknown settings group")
    try:
        out = set_setting(db, key, value)
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit(db, user, "settings_update", "app_settings", key, changes=value)
    db.commit()
    return out


# ---------------------------------------------------------------- alerts & audit
@router.get("/alerts")
def alerts(unread: bool = False, limit: int = 100, demo: bool | None = None, db: Session = Depends(get_db)):
    q = select(Alert)
    if demo is not None:
        q = q.where(Alert.is_demo == demo)
    if unread:
        q = q.where(Alert.read.is_(False))
    return [row(a) for a in db.scalars(q.order_by(Alert.created_at.desc()).limit(limit))]


@router.post("/alerts/read-all")
def read_all(demo: bool | None = None, db: Session = Depends(get_db)):
    q = select(Alert).where(Alert.read.is_(False))
    if demo is not None:
        q = q.where(Alert.is_demo == demo)
    for a in db.scalars(q):
        a.read = True
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = 200, db: Session = Depends(get_db)):
    return [row(a) for a in db.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(limit))]
