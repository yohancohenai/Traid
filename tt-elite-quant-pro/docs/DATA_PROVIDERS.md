# Data provider comparison (researched 2026-11-23)

## Primary results source: the official www.tt-series.com (VERIFIED, free)
The organiser's own public site, linked from eliteseries.eu.
- **robots.txt** disallows only `/wp-admin/`. The rules, integrity and privacy pages contain no clause restricting
  automated reading, and rule 13.4 says results are announced publicly.
- **Data:** full schedule about 2 days ahead (Europe/Warsaw times) and set scores **with every game's points**.
  Stable numeric player IDs. About 25 round-robin tournaments a day across OSP, OSP2, HSC, HSC2, POCZESNA and
  BLACHOWNIA. Archive by tournament ID from about 2026-11-07.
- **Adapter:** `providers/ttseries.py`. Identified User-Agent, ≤ 1 request / 5 s, polled every 10 min, finished
  tournaments never re-fetched. Backfill: `python -m ttq.cli backfill-ttseries --from-id 1`.
- **Treatment:** results are treated as official (`verified=True`), so bets on finished matches settle
  automatically. Walkovers, interruptions and cancellations go to manual review.
- **If the site's layout changes,** the parser returns no matches rather than wrong ones (fixture tests in
  `tests/test_ttseries.py`). Re-capture fixtures and adjust `parse_tournament`.

## Rejected: scores24.live
Its terms say users may not "use automated programs to interact with the Site", and its robots.txt blocks
table-tennis match pages, the odds and data feeds, and AI crawlers. Not used.

---

**Bottom line: no provider could be verified for TT Elite Series from the build environment.** Every host named in
the brief failed DNS resolution from the build sandbox. Web search returned no trace of four of them. The app is
therefore built around **pluggable adapters, CSV import of licensed exports, and fast manual Hard Rock odds entry**,
plus a clearly labelled **DEMO** synthetic world for exercising the pipeline.

| Provider | TT Elite coverage | Results / sets / points | Historical odds | Hard Rock | DraftKings | Access | Status in app |
|---|---|---|---|---|---|---|---|
| eliteseries.eu (organiser) | Official | Expected | n/a | n/a | n/a | No public API found; ToS unknown | Not scraped. Read its ToS before any automated access |
| tt-lossbeater.com/api | Unknown | Unknown | Unknown | Unknown | Unknown | DNS failure; no search results | **Not found.** No adapter |
| valueoddsapi.com | Unknown | – | – | – | – | DNS failure; no search results | **Not found.** No adapter |
| deucelab.io | Unknown | – | – | – | – | DNS failure; no search results | **Not found.** No adapter |
| pongdata.com | Unknown | – | – | – | – | DNS failure; no search results | **Not found.** No adapter |
| The Odds API v4 | **Not confirmed.** No table-tennis sport key found | Scores for covered sports only | Paid historical snapshots | `hardrockbet`, `hardrockbet_fl` keys (us2) | `draftkings` | `apiKey` query param; quota headers | Adapter built (`providers/the_odds_api.py`), **UNVERIFIED**, disabled until a TT sport key is confirmed with `/v4/sports?all=true` |
| OddsPapi | Claimed (marketing pages list TT Elite fixtures; table tennis sportId 25) | Unknown | Unknown | Claimed | Claimed | Unknown (docs unreachable) | Best lead. Adapter **not** built until docs are verified |
| Sportradar Table Tennis v2 | Check the coverage matrix | Official-grade | Separate odds product | No | No | Enterprise contract | Most legitimate results source *if* TT Elite is covered |
| SportsGameOdds / odds-api.io | Table tennis claimed, TT Elite not named | – | – | Claimed | – | Unknown | Ask vendor for the league list |
| Statscore | Lists TT Star Series, not TT Elite | – | – | – | – | – | Not suitable |

(All rows except "Not found" come from search-result summaries, not fetched docs. Treat them as leads to verify.)

## Recommended path to real data
1. **Results:** ask Sportradar (or OddsPapi) for written confirmation of TT Elite Series coverage, history depth and
   set/point scores. Implement a `ResultsProvider` (see `backend/ttq/providers/base.py`). Until then, import licensed
   exports with **Data Sources → Results CSV import** (format in `providers/csv_import.py`).
2. **Hard Rock odds:** Hard Rock has **no public first-party API**. Options: (a) **manual entry** (built, fast,
   timestamped); (b) an aggregator that contractually supplies `hardrockbet_fl` prices for TT Elite (verify
   per-league before paying).
3. **DraftKings:** reference only. DraftKings Sportsbook is **not legal in Florida** and the app hard-codes it as
   non-executable (`scanner.is_executable`).

## Adding a provider
Implement `ResultsProvider.fetch_matches` or `OddsProvider.fetch_odds`, set `verified=True` only after documented
coverage is confirmed, and register it in `providers/registry.py`. Raw payloads are stored in `raw_observations`
automatically. Unverified results sources never auto-settle bets; their settlements go to manual review.
