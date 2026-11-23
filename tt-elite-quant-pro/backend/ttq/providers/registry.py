from ttq.core.config import get_settings
from ttq.providers.base import OddsProvider, ResultsProvider

# Documented provider catalogue (see docs/DATA_PROVIDERS.md). `status` reflects what was verifiable.
CATALOGUE = [
    {"key": "demo_results", "name": "DEMO synthetic results", "kind": "results", "is_demo": True,
     "verification": "Synthetic. Never real.", "hard_rock": False, "draftkings": False},
    {"key": "demo_odds", "name": "DEMO synthetic odds", "kind": "odds", "is_demo": True,
     "verification": "Synthetic. Never real.", "hard_rock": False, "draftkings": False},
    {"key": "manual", "name": "Manual Hard Rock entry", "kind": "odds", "is_demo": False,
     "verification": "User-entered from the Hard Rock Bet app; timestamped at entry.", "hard_rock": True, "draftkings": False},
    {"key": "csv_import", "name": "CSV import (licensed exports)", "kind": "both", "is_demo": False,
     "verification": "Depends on the export's licence and provenance.", "hard_rock": None, "draftkings": None},
    {"key": "the_odds_api", "name": "The Odds API v4", "kind": "odds", "is_demo": False,
     "verification": "UNVERIFIED for TT Elite. Has hardrockbet/draftkings bookmaker keys; TT sport key not confirmed.",
     "hard_rock": "unverified", "draftkings": "unverified"},
    {"key": "oddspapi", "name": "OddsPapi", "kind": "odds", "is_demo": False,
     "verification": "UNVERIFIED. Public pages claim TT Elite fixtures and a Hard Rock Bet feed; docs not reachable. Adapter not built.",
     "hard_rock": "claimed", "draftkings": "claimed"},
    {"key": "sportradar_tt", "name": "Sportradar Table Tennis v2", "kind": "results", "is_demo": False,
     "verification": "UNVERIFIED. Enterprise licence; TT Elite coverage must be checked in its coverage matrix. Adapter not built.",
     "hard_rock": False, "draftkings": False},
    {"key": "tt-lossbeater/valueoddsapi/deucelab/pongdata", "name": "Named in brief", "kind": "unknown", "is_demo": False,
     "verification": "NOT FOUND: hosts did not resolve and web search returned no trace. No adapter.",
     "hard_rock": None, "draftkings": None},
]


def results_providers() -> list[ResultsProvider]:
    out: list[ResultsProvider] = []
    if get_settings().enable_demo:
        from ttq.providers.demo import DemoResultsProvider
        out.append(DemoResultsProvider())
    return out


def odds_providers() -> list[OddsProvider]:
    s = get_settings()
    out: list[OddsProvider] = []
    if s.enable_demo:
        from ttq.providers.demo import DemoOddsProvider
        out.append(DemoOddsProvider())
    if s.the_odds_api_key and s.the_odds_api_sport_key:
        from ttq.providers.the_odds_api import TheOddsApiProvider
        out.append(TheOddsApiProvider())
    return out
