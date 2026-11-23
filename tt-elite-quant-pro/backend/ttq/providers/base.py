"""Provider adapter interfaces. New data sources are added by implementing these and registering them."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProviderMatch:
    source_ref: str
    p1_name: str
    p2_name: str
    scheduled_at: datetime
    status: str  # SCHEDULED | LIVE | FINISHED | CANCELLED | RETIRED | WALKOVER | POSTPONED
    p1_ref: str | None = None
    p2_ref: str | None = None
    tournament_ref: str | None = None
    tournament_name: str | None = None
    tournament_level: str = "standard"
    finished_at: datetime | None = None
    sets_p1: int | None = None
    sets_p2: int | None = None
    set_points: list[tuple[int, int]] = field(default_factory=list)
    live_state: dict | None = None
    best_of: int = 5


@dataclass
class ProviderQuote:
    event_ref: str            # provider's event id
    p1_name: str
    p2_name: str
    commence_time: datetime
    bookmaker_key: str
    market: str
    selection: str            # p1 | p2 | over | under | "3-0" ...
    american: int | None = None
    decimal_odds: float | None = None
    line: float | None = None
    quoted_at: datetime | None = None
    availability: str = "OPEN"
    settlement_rules: str | None = None
    match_source_ref: str | None = None  # set when the provider shares IDs with the results provider


class ProviderUnavailable(Exception):
    """Raised when a provider is not configured or its access cannot be verified."""


class ResultsProvider:
    key = "base"
    name = "base"
    is_demo = False
    verified = False  # True only after docs/coverage verified for TT Elite Series

    def fetch_matches(self, since: datetime, until: datetime) -> tuple[list[ProviderMatch], dict]:
        """Return (matches, raw_payload)."""
        raise NotImplementedError


class OddsProvider:
    key = "base"
    name = "base"
    is_demo = False
    verified = False
    bookmakers: tuple[str, ...] = ()

    def fetch_odds(self, now: datetime) -> tuple[list[ProviderQuote], dict]:
        raise NotImplementedError
