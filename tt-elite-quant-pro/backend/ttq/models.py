"""SQLAlchemy ORM schema for TT Elite Quant Pro.

Conventions
- All timestamps are timezone-aware UTC (TIMESTAMP WITH TIME ZONE).
- `is_demo` marks synthetic data. Demo rows must never be presented as live.
- Predictions are append-only: they record `as_of` (information cutoff) and are never updated.
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ttq.core.db import Base
from ttq.core.timeutil import utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")
TS = DateTime(timezone=True)


def ts_col(nullable=False, default=True):
    return mapped_column(TS, nullable=nullable, default=utcnow if default else None)


# ---------------------------------------------------------------- sources & raw data
class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))  # results | odds | both | manual | demo
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="UNAVAILABLE")  # OK | STALE | ERROR | UNAVAILABLE
    last_success_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawObservation(Base):
    """Every payload fetched from a provider is preserved verbatim."""
    __tablename__ = "raw_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), index=True)
    endpoint: Mapped[str] = mapped_column(String(512))
    fetched_at: Mapped[datetime] = ts_col()
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONType)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- players & identity
class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(String(128), index=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = ts_col()
    aliases: Mapped[list[PlayerAlias]] = relationship(back_populates="player")


class PlayerAlias(Base):
    __tablename__ = "player_aliases"
    __table_args__ = (UniqueConstraint("source_key", "alias", name="uq_alias_source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    alias: Mapped[str] = mapped_column(String(128))
    normalized: Mapped[str] = mapped_column(String(128), index=True)
    source_key: Mapped[str] = mapped_column(String(64))
    source_player_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_by: Mapped[str] = mapped_column(String(32), default="exact")  # exact | manual | source_id
    created_at: Mapped[datetime] = ts_col()
    player: Mapped[Player] = relationship(back_populates="aliases")


class IdentityReview(Base):
    """Ambiguous names are queued here and are NEVER auto-merged."""
    __tablename__ = "identity_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    raw_name: Mapped[str] = mapped_column(String(128))
    normalized: Mapped[str] = mapped_column(String(128))
    source_key: Mapped[str] = mapped_column(String(64))
    source_player_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    candidates: Mapped[list] = mapped_column(JSONType, default=list)  # [{player_id, name, score}]
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | MERGED | NEW_PLAYER | REJECTED
    resolved_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    created_at: Mapped[datetime] = ts_col()
    resolved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


# ---------------------------------------------------------------- tournaments & matches
class Tournament(Base):
    __tablename__ = "tournaments"
    __table_args__ = (UniqueConstraint("source_key", "source_ref", name="uq_tournament_src"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    level: Mapped[str] = mapped_column(String(32), default="standard")
    starts_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    source_key: Mapped[str] = mapped_column(String(64))
    source_ref: Mapped[str] = mapped_column(String(128))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("source_key", "source_ref", name="uq_match_src"),
        Index("ix_match_sched", "scheduled_at"),
        CheckConstraint("player1_id <> player2_id", name="ck_distinct_players"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("tournaments.id"), nullable=True)
    source_key: Mapped[str] = mapped_column(String(64))
    source_ref: Mapped[str] = mapped_column(String(128))
    competition: Mapped[str] = mapped_column(String(64), default="TT Elite Series")
    player1_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    player2_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(TS)
    started_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    # SCHEDULED | LIVE | FINISHED | CANCELLED | RETIRED | WALKOVER | POSTPONED
    status: Mapped[str] = mapped_column(String(16), default="SCHEDULED", index=True)
    best_of: Mapped[int] = mapped_column(Integer, default=5)
    sets_p1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sets_p2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    result_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    result_sources: Mapped[list] = mapped_column(JSONType, default=list)
    live_state: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    live_updated_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    data_quality: Mapped[str] = mapped_column(String(8), default="MEDIUM")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = ts_col()
    updated_at: Mapped[datetime] = ts_col()
    sets: Mapped[list[MatchSet]] = relationship(order_by="MatchSet.set_no", cascade="all, delete-orphan")
    player1: Mapped[Player] = relationship(foreign_keys=[player1_id])
    player2: Mapped[Player] = relationship(foreign_keys=[player2_id])
    tournament: Mapped[Tournament | None] = relationship()


class MatchSet(Base):
    __tablename__ = "match_sets"
    __table_args__ = (UniqueConstraint("match_id", "set_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    set_no: Mapped[int] = mapped_column(Integer)
    p1_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p2_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_server: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 | 2 when known


class RatingSnapshot(Base):
    """Pre-match rating of a player under a given rating model (as known before the match)."""
    __tablename__ = "rating_snapshots"
    __table_args__ = (Index("ix_rating_player_model", "player_id", "model", "as_of"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    model: Mapped[str] = mapped_column(String(32))
    as_of: Mapped[datetime] = mapped_column(TS)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"), nullable=True)
    rating: Mapped[float] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float, nullable=True)
    games: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------- odds
class Bookmaker(Base):
    __tablename__ = "bookmakers"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    # Only books legally available to the user may be executable. DraftKings is NOT legal in Florida.
    executable_regions: Mapped[list] = mapped_column(JSONType, default=list)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class OddsQuote(Base):
    __tablename__ = "odds_quotes"
    __table_args__ = (Index("ix_quote_match_book", "match_id", "bookmaker_key", "market", "captured_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    bookmaker_key: Mapped[str] = mapped_column(String(64))
    market: Mapped[str] = mapped_column(String(32))  # match_winner | set_handicap | point_handicap | total_points | correct_score | set_winner
    selection: Mapped[str] = mapped_column(String(32))  # p1 | p2 | over | under | "3-1" ...
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    american: Mapped[int] = mapped_column(Integer)
    decimal_odds: Mapped[float] = mapped_column(Numeric(10, 4))
    quoted_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)  # provider timestamp
    captured_at: Mapped[datetime] = ts_col()  # when we first observed this exact price
    last_confirmed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)  # last time the same price was re-observed
    source_key: Mapped[str] = mapped_column(String(64))
    availability: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | SUSPENDED | CLOSED
    is_closing: Mapped[bool] = mapped_column(Boolean, default=False)
    settlement_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # for manual quotes
    raw_observation_id: Mapped[int | None] = mapped_column(ForeignKey("raw_observations.id"), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- models & predictions
class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="CANDIDATE")  # CANDIDATE | CHAMPION | RETIRED | REJECTED
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    features: Mapped[list] = mapped_column(JSONType, default=list)
    metrics: Mapped[dict] = mapped_column(JSONType, default=dict)
    splits: Mapped[dict] = mapped_column(JSONType, default=dict)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    trained_at: Mapped[datetime] = ts_col()
    train_cutoff: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    promoted_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Prediction(Base):
    """Append-only. `as_of` is the information cutoff used to build features."""
    __tablename__ = "predictions"
    __table_args__ = (Index("ix_pred_match_created", "match_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    created_at: Mapped[datetime] = ts_col()
    as_of: Mapped[datetime] = mapped_column(TS)
    p1_win: Mapped[float] = mapped_column(Float)
    p1_ci_low: Mapped[float] = mapped_column(Float)
    p1_ci_high: Mapped[float] = mapped_column(Float)
    p_set: Mapped[float | None] = mapped_column(Float, nullable=True)
    scorelines: Mapped[dict] = mapped_column(JSONType, default=dict)
    component_probs: Mapped[dict] = mapped_column(JSONType, default=dict)
    features: Mapped[dict] = mapped_column(JSONType, default=dict)
    data_quality: Mapped[str] = mapped_column(String(8), default="MEDIUM")
    is_backtest: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (Index("ix_rec_match", "match_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("odds_quotes.id"), nullable=True)
    created_at: Mapped[datetime] = ts_col()
    market: Mapped[str] = mapped_column(String(32))
    selection: Mapped[str] = mapped_column(String(32))
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    bookmaker_key: Mapped[str] = mapped_column(String(64))
    decimal_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_prob: Mapped[float] = mapped_column(Float)
    prob_low: Mapped[float] = mapped_column(Float)
    prob_high: Mapped[float] = mapped_column(Float)
    ev: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    novig_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # QUALIFIES | WATCH | PASS
    user_action: Mapped[str] = mapped_column(String(16), default="RECOMMENDED")  # RECOMMENDED | SKIPPED | PLACED
    reasons_for: Mapped[list] = mapped_column(JSONType, default=list)
    reasons_against: Mapped[list] = mapped_column(JSONType, default=list)
    filter_results: Mapped[dict] = mapped_column(JSONType, default=dict)
    data_quality: Mapped[str] = mapped_column(String(8))
    model_agreement: Mapped[dict] = mapped_column(JSONType, default=dict)
    quote_status: Mapped[str] = mapped_column(String(16), default="UNAVAILABLE")  # VERIFIED | STALE | UNAVAILABLE
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    hypothetical_result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    hypothetical_profit_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)


# ---------------------------------------------------------------- real-money ledger (ledger A)
class Bet(Base):
    __tablename__ = "bets"
    __table_args__ = (
        CheckConstraint("stake > 0", name="ck_stake_pos"),
        CheckConstraint("accepted_decimal > 1", name="ck_decimal_gt1"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendations.id"), nullable=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    bookmaker_key: Mapped[str] = mapped_column(String(64), default="hardrock")
    market: Mapped[str] = mapped_column(String(32))
    selection: Mapped[str] = mapped_column(String(32))
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    accepted_american: Mapped[int] = mapped_column(Integer)
    accepted_decimal: Mapped[float] = mapped_column(Numeric(10, 4))
    stake: Mapped[float] = mapped_column(Numeric(12, 2))
    placed_at: Mapped[datetime] = mapped_column(TS)
    bet_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PLACED | PENDING_RESULT | WON | LOST | PUSH | VOID | SETTLEMENT_REVIEW
    status: Mapped[str] = mapped_column(String(24), default="PLACED", index=True)
    potential_payout: Mapped[float] = mapped_column(Numeric(12, 2))
    potential_profit: Mapped[float] = mapped_column(Numeric(12, 2))
    net_profit: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    model_prob_at_placement: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev_at_placement: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    closing_decimal: Mapped[float | None] = mapped_column(Float, nullable=True)
    clv: Mapped[float | None] = mapped_column(Float, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = ts_col()
    updated_at: Mapped[datetime] = ts_col()


class BetRevision(Base):
    __tablename__ = "bet_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    bet_id: Mapped[int] = mapped_column(ForeignKey("bets.id"), index=True)
    changed_at: Mapped[datetime] = ts_col()
    actor: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    before: Mapped[dict] = mapped_column(JSONType)
    after: Mapped[dict] = mapped_column(JSONType)


class SettlementProposal(Base):
    __tablename__ = "settlement_proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    bet_id: Mapped[int] = mapped_column(ForeignKey("bets.id"), index=True)
    created_at: Mapped[datetime] = ts_col()
    proposed_status: Mapped[str] = mapped_column(String(24))
    proposed_net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[str] = mapped_column(String(8))  # HIGH | LOW
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict)
    state: Mapped[str] = mapped_column(String(16), default="PROPOSED")  # PROPOSED | APPLIED | REJECTED | REVIEW
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class BankrollTransaction(Base):
    __tablename__ = "bankroll_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = ts_col()
    kind: Mapped[str] = mapped_column(String(24))  # DEPOSIT | WITHDRAWAL | STAKE | RETURN | ADJUSTMENT
    amount: Mapped[float] = mapped_column(Numeric(12, 2))  # signed
    bet_id: Mapped[int | None] = mapped_column(ForeignKey("bets.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- paper ledger (ledger C)
class PaperTrade(Base):
    __tablename__ = "paper_trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_run_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_runs.id"), nullable=True, index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    decided_at: Mapped[datetime] = mapped_column(TS)
    selection: Mapped[str] = mapped_column(String(32))
    market: Mapped[str] = mapped_column(String(32), default="match_winner")
    decimal_odds: Mapped[float] = mapped_column(Float)
    stake_units: Mapped[float] = mapped_column(Float, default=1.0)
    model_prob: Mapped[float] = mapped_column(Float)
    ev: Mapped[float] = mapped_column(Float)
    closing_decimal: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[str | None] = mapped_column(String(8), nullable=True)
    profit_units: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = ts_col()
    name: Mapped[str] = mapped_column(String(128))
    config: Mapped[dict] = mapped_column(JSONType)
    metrics: Mapped[dict] = mapped_column(JSONType, default=dict)
    period_start: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="INCONCLUSIVE")  # POSITIVE | NEGATIVE | INCONCLUSIVE
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- settings, alerts, audit
class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = ts_col()


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = ts_col()
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8), default="INFO")
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(256), unique=True)
    channels_sent: Mapped[list] = mapped_column(JSONType, default=list)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = ts_col()
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = ts_col()
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
