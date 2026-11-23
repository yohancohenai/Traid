"""CSV importers for licensed exports (results and historical odds).

Results CSV columns (header required):
  source_ref, scheduled_at_utc, player1, player2, status, sets_p1, sets_p2, set_scores, finished_at_utc,
  tournament_ref, tournament_name, tournament_level
  - set_scores like "11-7;9-11;11-5;11-8" (optional)
Odds CSV columns:
  match_source_ref, bookmaker, market, selection, american, line, quoted_at_utc, is_closing
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from ttq.core.timeutil import as_utc
from ttq.providers.base import ProviderMatch, ProviderQuote
from ttq.odds.math import american_to_decimal


def _dt(s):
    return as_utc(datetime.fromisoformat(s.replace("Z", "+00:00"))) if s else None


def parse_results_csv(text: str) -> list[ProviderMatch]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        pts = []
        if row.get("set_scores"):
            for part in row["set_scores"].split(";"):
                a, b = part.strip().split("-")
                pts.append((int(a), int(b)))
        out.append(ProviderMatch(
            source_ref=row["source_ref"], p1_name=row["player1"].strip(), p2_name=row["player2"].strip(),
            scheduled_at=_dt(row["scheduled_at_utc"]), status=(row.get("status") or "FINISHED").upper(),
            sets_p1=int(row["sets_p1"]) if row.get("sets_p1") else None,
            sets_p2=int(row["sets_p2"]) if row.get("sets_p2") else None, set_points=pts,
            finished_at=_dt(row.get("finished_at_utc")), tournament_ref=row.get("tournament_ref") or None,
            tournament_name=row.get("tournament_name") or None,
            tournament_level=row.get("tournament_level") or "standard"))
    return out


def parse_odds_csv(text: str) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        am = int(row["american"])
        out.append({"match_source_ref": row["match_source_ref"], "bookmaker_key": row["bookmaker"].strip().lower(),
                    "market": row.get("market") or "match_winner", "selection": row["selection"],
                    "american": am, "decimal_odds": american_to_decimal(am),
                    "line": float(row["line"]) if row.get("line") else None,
                    "quoted_at": _dt(row["quoted_at_utc"]),
                    "is_closing": str(row.get("is_closing", "")).lower() in ("1", "true", "yes")})
    return out
