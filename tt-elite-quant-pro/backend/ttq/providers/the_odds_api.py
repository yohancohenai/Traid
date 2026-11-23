"""The Odds API v4 adapter (https://the-odds-api.com).

STATUS: UNVERIFIED for TT Elite Series. Bookmaker keys `hardrockbet` / `draftkings` exist in its US regions, but
no table-tennis sport key was confirmed during research (docs host unreachable from the build sandbox).
Before enabling: call `discover_sports()` (does not consume quota) and set TTQ_THE_ODDS_API_SPORT_KEY to a key
that actually covers TT Elite Series. Without key + sport key the adapter raises ProviderUnavailable.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from ttq.core.config import get_settings
from ttq.core.timeutil import as_utc
from ttq.odds.math import american_to_decimal
from ttq.providers.base import OddsProvider, ProviderQuote, ProviderUnavailable

BASE = "https://api.the-odds-api.com/v4"
BOOK_MAP = {"hardrockbet": "hardrock", "hardrockbet_fl": "hardrock", "draftkings": "draftkings"}


class TheOddsApiProvider(OddsProvider):
    key = "the_odds_api"
    name = "The Odds API v4"
    verified = False
    bookmakers = ("hardrock", "draftkings")

    def __init__(self, client: httpx.Client | None = None):
        s = get_settings()
        self.api_key, self.sport_key = s.the_odds_api_key, s.the_odds_api_sport_key
        self.client = client or httpx.Client(timeout=20)

    def discover_sports(self) -> list[dict]:
        if not self.api_key:
            raise ProviderUnavailable("TTQ_THE_ODDS_API_KEY not set")
        r = self.client.get(f"{BASE}/sports", params={"apiKey": self.api_key, "all": "true"})
        r.raise_for_status()
        return [s for s in r.json() if "table" in (s.get("key", "") + s.get("title", "") + s.get("group", "")).lower()]

    def fetch_odds(self, now: datetime):
        if not self.api_key or not self.sport_key:
            raise ProviderUnavailable("The Odds API key or verified TT sport key not configured")
        r = self.client.get(f"{BASE}/sports/{self.sport_key}/odds", params={
            "apiKey": self.api_key, "regions": "us,us2", "markets": "h2h",
            "bookmakers": "hardrockbet,draftkings", "oddsFormat": "american", "dateFormat": "iso"})
        r.raise_for_status()
        payload = r.json()
        meta = {"x-requests-remaining": r.headers.get("x-requests-remaining"),
                "x-requests-used": r.headers.get("x-requests-used")}
        return self.parse(payload), {"events": payload, "meta": meta}

    @staticmethod
    def parse(payload: list[dict]) -> list[ProviderQuote]:
        out = []
        for ev in payload:
            home, away = ev["home_team"], ev["away_team"]
            commence = as_utc(datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")))
            for bk in ev.get("bookmakers", []):
                book = BOOK_MAP.get(bk["key"])
                if not book:
                    continue
                last = as_utc(datetime.fromisoformat(bk["last_update"].replace("Z", "+00:00"))) if bk.get("last_update") else None
                for mk in bk.get("markets", []):
                    if mk["key"] != "h2h":
                        continue
                    for oc in mk["outcomes"]:
                        sel = "p1" if oc["name"] == home else "p2" if oc["name"] == away else None
                        if sel is None:
                            continue
                        am = int(oc["price"])
                        out.append(ProviderQuote(event_ref=ev["id"], p1_name=home, p2_name=away, commence_time=commence,
                                                 bookmaker_key=book, market="match_winner", selection=sel, american=am,
                                                 decimal_odds=american_to_decimal(am), quoted_at=last))
        return out
