"""Overview, matches, opportunities, live, players, identity, analyzer, odds."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ttq.api.serialize import iso, match_brief, pred_out, quote_out, rec_out, row
from ttq.core.db import get_db
from ttq.core.security import current_user
from ttq.core.timeutil import as_utc, utcnow
from ttq.features.builder import MatchRecord, data_quality
from ttq.identity.names import normalize_name
from ttq.models import (Bet, DataSource, IdentityReview, Match, ModelVersion, OddsQuote, Player, PlayerAlias, Prediction,
                        RatingSnapshot, Recommendation)
from ttq.odds.math import (american_to_decimal, break_even_prob, decimal_to_american, ev_sensitivity, expected_value,
                           no_vig_multiplicative, no_vig_power, no_vig_shin, overround)
from ttq.providers.csv_import import parse_odds_csv
from ttq.services import identity as identity_svc
from ttq.services import monitoring, performance
from ttq.services.app_settings import get_filters, get_setting
from ttq.services.audit import audit
from ttq.services.modeling import build_features, latest_prediction, load_champion, uncertainty_interval, COMPONENTS
from ttq.services.scanner import ensure_bookmakers, is_executable, latest_quotes
from ttq.sim.tt import full_match_model, live_match_win_prob, point_prob_from_game, prob_set_handicap, prob_total_over, prob_point_handicap

router = APIRouter(dependencies=[Depends(current_user)])


def _demo(demo: bool | None) -> bool:
    return bool(demo)


# ---------------------------------------------------------------- overview
@router.get("/overview")
def overview(demo: bool = False, db: Session = Depends(get_db)):
    now = utcnow()
    nxt = db.scalars(select(Match).where(Match.is_demo == demo, Match.status == "SCHEDULED", Match.scheduled_at > now)
                     .order_by(Match.scheduled_at).limit(8)).all()
    recent = db.scalars(select(Match).where(Match.is_demo == demo, Match.status.in_(["FINISHED", "RETIRED", "CANCELLED"]))
                        .order_by(Match.finished_at.desc().nullslast()).limit(8)).all()
    recs = db.scalars(select(Recommendation).join(Match, Match.id == Recommendation.match_id)
                      .where(Recommendation.is_current.is_(True), Recommendation.is_demo == demo,
                             Recommendation.status == "QUALIFIES", Match.scheduled_at > now)
                      .order_by(Recommendation.ev.desc()).limit(10)).all()
    rec_list = [x for x in (rec_out(db, r) for r in recs) if x["status"] == "QUALIFIES"]
    pend = db.scalars(select(Bet).where(Bet.is_demo == demo, Bet.status.in_(["PLACED", "PENDING_RESULT", "SETTLEMENT_REVIEW"]))
                      .order_by(Bet.placed_at.desc()).limit(10)).all()
    summ = performance.summary(db, demo)
    health = monitoring.model_health(db, demo)
    sources = db.scalars(select(DataSource).where(DataSource.is_demo == demo)).all()
    last_hr = db.scalar(select(func.max(OddsQuote.captured_at)).where(OddsQuote.is_demo == demo, OddsQuote.bookmaker_key == "hardrock"))
    last_dk = db.scalar(select(func.max(OddsQuote.captured_at)).where(OddsQuote.is_demo == demo, OddsQuote.bookmaker_key == "draftkings"))
    return {
        "is_demo": demo, "now": iso(now), "next_matches": [_with_pred(db, m) for m in nxt],
        "opportunities": rec_list, "no_qualifying": len(rec_list) == 0,
        "recent_matches": [match_brief(m) for m in recent],
        "pending_bets": [{**row(b), "match": match_brief(db.get(Match, b.match_id))} for b in pend],
        "pl": {k: summ[k] for k in ("net_pl", "roi", "total_bets", "pending", "bankroll", "total_wagered", "win_pct")},
        "model": {k: health.get(k) for k in ("status", "champion", "recent_log_loss", "reference_log_loss", "recent_brier", "recent_accuracy", "n", "source")},
        "sources": [{"key": s.key, "name": s.name, "status": s.status, "last_success_at": iso(s.last_success_at)} for s in sources],
        "latest_odds": {"hardrock": iso(last_hr), "draftkings": iso(last_dk)},
    }


def _with_pred(db, m):
    d = match_brief(m)
    p = latest_prediction(db, m.id)
    d["prediction"] = {"p1_win": p.p1_win, "p1_ci": [p.p1_ci_low, p.p1_ci_high], "data_quality": p.data_quality, "as_of": iso(p.as_of)} if p else None
    hr = latest_quotes(db, m.id, "hardrock")
    d["hardrock"] = {sel: quote_out(q, m) for (sel, line), q in hr.items()}
    return d


# ---------------------------------------------------------------- matches
@router.get("/matches")
def list_matches(demo: bool = False, status: str | None = None, q: str | None = None, days_back: int = 1,
                 days_ahead: int = 2, limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    now = utcnow()
    stmt = select(Match).where(Match.is_demo == demo, Match.scheduled_at >= now - timedelta(days=days_back),
                               Match.scheduled_at <= now + timedelta(days=days_ahead))
    if status:
        stmt = stmt.where(Match.status.in_(status.upper().split(",")))
    if q:
        n = f"%{normalize_name(q)}%"
        ids = select(Player.id).where(Player.normalized_name.like(n))
        stmt = stmt.where(or_(Match.player1_id.in_(ids), Match.player2_id.in_(ids)))
    ms = db.scalars(stmt.order_by(Match.scheduled_at).limit(limit)).all()
    return [_with_pred(db, m) for m in ms]


@router.get("/matches/{match_id}")
def match_detail(match_id: int, db: Session = Depends(get_db)):
    m = db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "match not found")
    p = latest_prediction(db, m.id)
    quotes = db.scalars(select(OddsQuote).where(OddsQuote.match_id == m.id).order_by(OddsQuote.captured_at)).all()
    h2h = db.scalars(select(Match).where(or_((Match.player1_id == m.player1_id) & (Match.player2_id == m.player2_id),
                                             (Match.player1_id == m.player2_id) & (Match.player2_id == m.player1_id)),
                                         Match.status == "FINISHED", Match.scheduled_at < m.scheduled_at)
                     .order_by(Match.scheduled_at.desc()).limit(10)).all()
    recs = db.scalars(select(Recommendation).where(Recommendation.match_id == m.id, Recommendation.is_current.is_(True))).all()
    derived = None
    if p:
        fm = full_match_model(p.p1_win, with_points=True)
        cov = (p.features or {}).get("pts_coverage") or 0
        derived = {"p_game": fm["p_game"], "p_point": fm["p_point"], "scorelines": fm["scorelines"],
                   "set_handicap": {f"{l:+}": prob_set_handicap(fm["scorelines"], l) for l in (-2.5, -1.5, 1.5, 2.5)},
                   "total_points": {str(l): prob_total_over(fm["totals"], l) for l in (70.5, 74.5, 78.5, 82.5)},
                   "point_handicap": {f"{l:+}": prob_point_handicap(fm["margins"], l) for l in (-6.5, -3.5, 3.5, 6.5)},
                   "points_markets_status": "EXPERIMENTAL" if cov >= 0.5 else "UNSUPPORTED (insufficient point-level data)",
                   "assumptions": "Exact DP: games to 11, win by 2, deuce; best of five; iid points/games. Point-level "
                                  "outputs are derived, not independently validated."}
    pl = {}
    for side, pid in (("p1", m.player1_id), ("p2", m.player2_id)):
        last = db.scalars(select(Match).where(or_(Match.player1_id == pid, Match.player2_id == pid), Match.status == "FINISHED",
                                              Match.scheduled_at < m.scheduled_at).order_by(Match.scheduled_at.desc()).limit(10)).all()
        pl[side] = [{"id": x.id, "at": iso(x.scheduled_at), "won": x.winner_id == pid,
                     "opponent": (x.player2 if x.player1_id == pid else x.player1).canonical_name,
                     "score": f"{x.sets_p1}-{x.sets_p2}" if x.player1_id == pid else f"{x.sets_p2}-{x.sets_p1}"} for x in last]
    preds = db.scalars(select(Prediction).where(Prediction.match_id == m.id, Prediction.is_backtest.is_(False))
                       .order_by(Prediction.created_at)).all()
    mv = db.get(ModelVersion, p.model_version_id) if p and p.model_version_id else None
    return {"match": match_brief(m), "prediction": pred_out(p), "model": f"{mv.name}@{mv.version}" if mv else None,
            "prediction_history": [{"at": iso(x.created_at), "p1_win": x.p1_win} for x in preds],
            "derived_markets": derived, "quotes": [quote_out(q, m) for q in quotes[-200:]],
            "h2h": [match_brief(x) for x in h2h], "recent": pl, "recommendations": [rec_out(db, r) for r in recs]}


# ---------------------------------------------------------------- opportunities
@router.get("/opportunities")
def opportunities(demo: bool = False, status: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db)):
    now = utcnow()
    rs = db.scalars(select(Recommendation).join(Match, Match.id == Recommendation.match_id)
                    .where(Recommendation.is_current.is_(True), Recommendation.is_demo == demo, Match.scheduled_at > now,
                           Match.status == "SCHEDULED").order_by(Recommendation.ev.desc().nullslast())).all()
    out = [rec_out(db, r) for r in rs]
    n_q = sum(o["status"] == "QUALIFIES" for o in out)   # counted before the status filter
    if status:
        out = [o for o in out if o["status"] in status.upper().split(",")]
    out.sort(key=lambda o: ({"QUALIFIES": 0, "WATCH": 1, "PASS": 2}[o["status"]], -(o["ev"] or -9)))
    return {"items": out[offset:offset + limit], "total": len(out), "qualifying": n_q,
            "message": None if n_q else "NO QUALIFYING BETS FOUND.", "filters": get_filters(db, demo)}


@router.post("/opportunities/{rec_id}/skip")
def skip(rec_id: int, reason: str | None = None, db: Session = Depends(get_db), user: str = Depends(current_user)):
    from ttq.services.bets import BetError, skip_recommendation
    try:
        r = skip_recommendation(db, rec_id, user, reason)
    except BetError as e:
        raise HTTPException(e.code, str(e))
    db.commit()
    return {"id": r.id, "user_action": r.user_action}


# ---------------------------------------------------------------- live
@router.get("/live")
def live(demo: bool = False, db: Session = Depends(get_db)):
    ms = db.scalars(select(Match).where(Match.is_demo == demo, Match.status == "LIVE").order_by(Match.scheduled_at)).all()
    out = []
    for m in ms:
        d = match_brief(m)
        age = (utcnow() - as_utc(m.live_updated_at)).total_seconds() if m.live_updated_at else None
        d["feed_status"] = "UNAVAILABLE" if age is None else ("LIVE" if age < 30 else "DELAYED" if age < 180 else "STALE")
        d["feed_age_seconds"] = age
        p = latest_prediction(db, m.id)
        if p and m.live_state:
            pp = point_prob_from_game(p.p_set or 0.5)
            s, pts = m.live_state.get("sets", [0, 0]), m.live_state.get("points", [0, 0])
            d["live_p1_win"] = live_match_win_prob(pp, tuple(s), tuple(pts))
            d["pre_match_p1_win"] = p.p1_win
            d["live_note"] = ("In-play estimate from the pre-match point strength and the current score under an iid-point "
                              "model. It does not use live odds, and it is only as current as the feed.")
        out.append(d)
    return {"items": out, "live_odds": "UNAVAILABLE",
            "note": "No licensed live odds feed is configured. Live scores shown are from the configured results provider "
                    "and are labelled by feed age."}


# ---------------------------------------------------------------- players & identity
@router.get("/players")
def players(demo: bool = False, q: str | None = None, model: str = "glicko2", limit: int = 200, db: Session = Depends(get_db)):
    stmt = select(Player).where(Player.is_demo == demo)
    if q:
        stmt = stmt.where(Player.normalized_name.like(f"%{normalize_name(q)}%"))
    ps = db.scalars(stmt).all()
    latest = {}
    sub = (select(RatingSnapshot.player_id, func.max(RatingSnapshot.as_of).label("mx"))
           .where(RatingSnapshot.model == model).group_by(RatingSnapshot.player_id).subquery())
    for r in db.scalars(select(RatingSnapshot).join(sub, (sub.c.player_id == RatingSnapshot.player_id) & (sub.c.mx == RatingSnapshot.as_of))
                        .where(RatingSnapshot.model == model)).all():
        latest[r.player_id] = r
    counts = dict(db.execute(select(Match.player1_id, func.count()).where(Match.status == "FINISHED", Match.is_demo == demo).group_by(Match.player1_id)).all())
    for k, v in db.execute(select(Match.player2_id, func.count()).where(Match.status == "FINISHED", Match.is_demo == demo).group_by(Match.player2_id)).all():
        counts[k] = counts.get(k, 0) + v
    wins = dict(db.execute(select(Match.winner_id, func.count()).where(Match.status == "FINISHED", Match.is_demo == demo).group_by(Match.winner_id)).all())
    out = []
    for p in ps:
        r = latest.get(p.id)
        n = counts.get(p.id, 0)
        out.append({"id": p.id, "name": p.canonical_name, "rating": r.rating if r else None, "uncertainty": r.uncertainty if r else None,
                    "matches": n, "win_rate": wins.get(p.id, 0) / n if n else None, "rated_at": iso(r.as_of) if r else None,
                    "is_demo": p.is_demo})
    out.sort(key=lambda x: -(x["rating"] or 0))
    return out[:limit]


@router.get("/players/{pid}")
def player_detail(pid: int, db: Session = Depends(get_db)):
    p = db.get(Player, pid)
    if not p:
        raise HTTPException(404, "player not found")
    hist = {}
    for model in ("elo", "glicko2", "bayes"):
        rows = db.scalars(select(RatingSnapshot).where(RatingSnapshot.player_id == pid, RatingSnapshot.model == model)
                          .order_by(RatingSnapshot.as_of)).all()
        step = max(1, len(rows) // 300)
        hist[model] = [{"at": iso(r.as_of), "rating": r.rating, "unc": r.uncertainty} for r in rows[::step]]
    ms = db.scalars(select(Match).where(or_(Match.player1_id == pid, Match.player2_id == pid), Match.status == "FINISHED")
                    .order_by(Match.scheduled_at.desc()).limit(30)).all()
    return {"id": p.id, "name": p.canonical_name, "is_demo": p.is_demo,
            "aliases": [{"alias": a.alias, "source": a.source_key, "how": a.confirmed_by} for a in p.aliases],
            "rating_history": hist, "recent": [match_brief(m) for m in ms]}


@router.get("/identity/reviews")
def reviews(status: str = "OPEN", db: Session = Depends(get_db)):
    return [row(r) for r in db.scalars(select(IdentityReview).where(IdentityReview.status == status).order_by(IdentityReview.created_at.desc()).limit(200))]


class ReviewAction(BaseModel):
    action: str = Field(pattern="^(MERGE|NEW_PLAYER|REJECT)$")
    player_id: int | None = None


@router.post("/identity/reviews/{rid}/resolve")
def resolve(rid: int, body: ReviewAction, db: Session = Depends(get_db), user: str = Depends(current_user)):
    try:
        r = identity_svc.resolve_review(db, rid, body.action, body.player_id, user)
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return row(r)


# ---------------------------------------------------------------- analyzer
_FB_CACHE: dict[bool, tuple[float, object, object]] = {}


def _state(db, demo):
    c = _FB_CACHE.get(demo)
    if c and time.time() - c[0] < 300:
        return c[1], c[2]
    df, fb = build_features(db, demo)
    _FB_CACHE[demo] = (time.time(), fb, df)
    return fb, df


class AnalyzeIn(BaseModel):
    player1_id: int
    player2_id: int
    demo: bool = False
    p1_american: int | None = None
    p2_american: int | None = None

    @field_validator("p1_american", "p2_american")
    @classmethod
    def _am(cls, v):
        if v is not None and -100 < v < 100:
            raise ValueError("American odds must be <= -100 or >= +100")
        return v


@router.post("/analyzer")
def analyze(body: AnalyzeIn, db: Session = Depends(get_db)):
    if body.player1_id == body.player2_id:
        raise HTTPException(422, "choose two different players")
    mv, art = load_champion(db, body.demo)
    fb, _ = _state(db, body.demo)
    now = utcnow()
    rec = MatchRecord(id=-1, p1=body.player1_id, p2=body.player2_id, scheduled_at=now, status="SCHEDULED")
    f = fb.features(rec, now)
    import pandas as pd
    X = pd.DataFrame([f])
    comps = {}
    if art:
        p = float(art["models"][mv.name].predict(X)[0])
        comps = {c: float(art["models"][c].predict(X)[0]) for c in COMPONENTS if c in art["models"]}
        src = f"{mv.name}@{mv.version}"
    else:
        p, src = f["bayes_p"], "bayes_hier (no trained champion yet)"
    lo, hi = uncertainty_interval(p, f["bayes_sd"], list(comps.values()), get_filters(db, body.demo)["uncertainty_scale"])
    fm = full_match_model(p, with_points=True)
    out = {"model": src, "p1_win": p, "p1_ci": [lo, hi], "components": comps,
           "rating_probs": {k: f[k] for k in ("elo_p", "dyn_elo_p", "glicko_p", "bayes_p", "set_elo_p", "bt_p")},
           "data_quality": data_quality(f["_n1"], f["_n2"], f["pts_coverage"]), "sample": [f["_n1"], f["_n2"]],
           "scorelines": fm["scorelines"], "p_game": fm["p_game"], "p_point": fm["p_point"],
           "fair": {"p1": {"decimal": 1 / p, "american": decimal_to_american(1 / p)},
                    "p2": {"decimal": 1 / (1 - p), "american": decimal_to_american(1 / (1 - p))}},
           "features": {k: v for k, v in f.items() if not k.startswith("_")}}
    if body.p1_american and body.p2_american:
        d1, d2 = american_to_decimal(body.p1_american), american_to_decimal(body.p2_american)
        out["market"] = {"overround": overround([d1, d2]), "novig_mult": no_vig_multiplicative([d1, d2]),
                         "novig_power": no_vig_power([d1, d2]), "novig_shin": no_vig_shin([d1, d2]),
                         "ev_p1": expected_value(p, d1), "ev_p2": expected_value(1 - p, d2),
                         "break_even": [break_even_prob(d1), break_even_prob(d2)],
                         "sensitivity_p1": ev_sensitivity(p, d1), "sensitivity_p2": ev_sensitivity(1 - p, d2)}
    return out


# ---------------------------------------------------------------- odds
@router.get("/odds/{match_id}")
def odds_comparison(match_id: int, db: Session = Depends(get_db)):
    m = db.get(Match, match_id)
    if not m:
        raise HTTPException(404, "match not found")
    p = latest_prediction(db, m.id)
    books = {}
    for book in ("hardrock", "draftkings"):
        lq = latest_quotes(db, m.id, book)
        q1, q2 = lq.get(("p1", None)), lq.get(("p2", None))
        entry = {"quotes": {sel: quote_out(q, m) for (sel, line), q in lq.items()}, "executable_in_fl": is_executable(book)}
        if q1 and q2:
            d = [float(q1.decimal_odds), float(q2.decimal_odds)]
            entry.update({"overround": overround(d), "novig": no_vig_multiplicative(d), "novig_power": no_vig_power(d)})
            if p:
                entry["ev"] = [expected_value(p.p1_win, d[0]), expected_value(1 - p.p1_win, d[1])]
        first = db.scalars(select(OddsQuote).where(OddsQuote.match_id == m.id, OddsQuote.bookmaker_key == book,
                                                   OddsQuote.market == "match_winner").order_by(OddsQuote.captured_at).limit(2)).all()
        entry["opening"] = {q.selection: float(q.decimal_odds) for q in first}
        books[book] = entry
    hist = db.scalars(select(OddsQuote).where(OddsQuote.match_id == m.id, OddsQuote.market == "match_winner").order_by(OddsQuote.captured_at)).all()
    return {"match": match_brief(m), "prediction": pred_out(p), "books": books,
            "history": [{"at": iso(q.captured_at), "book": q.bookmaker_key, "sel": q.selection, "dec": float(q.decimal_odds)} for q in hist[-400:]]}


class ManualQuote(BaseModel):
    match_id: int
    market: str = Field("match_winner", pattern="^(match_winner|set_handicap|point_handicap|total_points|correct_score|set_winner)$")
    selection: str = Field(min_length=1, max_length=16)
    american: int
    line: float | None = None
    availability: str = Field("OPEN", pattern="^(OPEN|SUSPENDED)$")
    observed_at: datetime | None = None
    settlement_rules: str | None = None

    @field_validator("american")
    @classmethod
    def _am(cls, v):
        if -100 < v < 100 or abs(v) > 100000:
            raise ValueError("American odds must be <= -100 or >= +100")
        return v


@router.post("/odds/manual")
def manual_quote(items: list[ManualQuote], db: Session = Depends(get_db), user: str = Depends(current_user)):
    """Fast manual entry of Hard Rock prices read from the Hard Rock Bet app. Timestamped at entry."""
    ensure_bookmakers(db)
    out, warnings = [], []
    now = utcnow()
    for it in items:
        m = db.get(Match, it.match_id)
        if not m:
            raise HTTPException(404, f"match {it.match_id} not found")
        obs = as_utc(it.observed_at) or now
        if obs > now + timedelta(minutes=2):
            raise HTTPException(422, "observed_at cannot be in the future")
        if m.status != "SCHEDULED":
            warnings.append(f"match {m.id} is {m.status}; quote stored but cannot be VERIFIED")
        q = OddsQuote(match_id=m.id, bookmaker_key="hardrock", market=it.market, selection=it.selection, line=it.line,
                      american=it.american, decimal_odds=round(american_to_decimal(it.american), 4), quoted_at=obs,
                      captured_at=obs, source_key="manual", availability=it.availability, entered_by=user,
                      settlement_rules=it.settlement_rules, is_demo=m.is_demo)
        db.add(q)
        db.flush()
        out.append(quote_out(q, m))
    by_match = {}
    for it in items:
        if it.market == "match_winner":
            by_match.setdefault(it.match_id, {})[it.selection] = american_to_decimal(it.american)
    for mid, d in by_match.items():
        if "p1" in d and "p2" in d:
            ov = overround([d["p1"], d["p2"]])
            if not (0.0 <= ov <= 0.15):
                warnings.append(f"match {mid}: overround {ov:.1%} looks implausible; check the prices entered")
    audit(db, user, "manual_quotes", "odds_quote", None, count=len(out))
    db.commit()
    return {"stored": out, "warnings": warnings}


@router.post("/odds/import-csv")
async def import_odds_csv(file: UploadFile, db: Session = Depends(get_db), user: str = Depends(current_user)):
    text = (await file.read()).decode("utf-8-sig")
    try:
        rows = parse_odds_csv(text)
    except KeyError as e:
        raise HTTPException(422, f"CSV is missing required column {e}. Required: match_source_ref, bookmaker, selection, american, quoted_at_utc")
    except (ValueError, TypeError) as e:
        raise HTTPException(422, f"CSV has an invalid value: {e}")
    stored = rejected = 0
    for r in rows:
        m = db.scalar(select(Match).where(Match.source_ref == r["match_source_ref"], Match.is_demo.is_(False)))
        if not m or r["quoted_at"] is None:
            rejected += 1
            continue
        db.add(OddsQuote(match_id=m.id, bookmaker_key=r["bookmaker_key"], market=r["market"], selection=r["selection"],
                         line=r["line"], american=r["american"], decimal_odds=r["decimal_odds"], quoted_at=r["quoted_at"],
                         captured_at=r["quoted_at"], source_key="csv_import", is_closing=r["is_closing"], is_demo=False))
        stored += 1
    audit(db, user, "odds_csv_import", "odds_quote", None, stored=stored, rejected=rejected)
    db.commit()
    return {"stored": stored, "rejected": rejected}
