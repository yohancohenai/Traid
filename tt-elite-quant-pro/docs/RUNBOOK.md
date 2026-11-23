# Operational runbook

## Daily
1. Open **Overview**. Check the Data feed status (OK / STALE / ERROR / UNAVAILABLE) and the latest verified odds timestamps.
2. **Bet Opportunities** shows QUALIFIES items only while the Hard Rock quote is under `max_quote_age_seconds` old.
   Before placing anything, re-check the price in the Hard Rock app. If you use manual entry, enter the new price
   (Odds Comparison → Manual entry) and the scanner will re-evaluate within 5 minutes (or run `predict_scan` from Data Sources).
3. After placing a bet in the Hard Rock app, click **BET PLACED** and enter the **accepted** odds and stake. Use the
   bet-slip reference: it prevents duplicate entries.
4. **My Bets**: settle anything in SETTLEMENT_REVIEW (retirements, cancellations, unverified results) against Hard Rock's actual settlement.

## Weekly
* **Model Performance**: compare recent log loss with the reference. On DRIFT, retraining is triggered by the daily
  job. You can also click Train challenger. A challenger is promoted only if it beats the champion out of sample by `promotion_min_logloss_gain`.
* **Backtesting**: every run is stored, losing ones included. Look at the run count before trusting a single good result.

## Incidents
| Symptom | Action |
|---|---|
| Provider STALE / ERROR | Data Sources → job history shows the error. Fix credentials in `.env`, then `docker compose restart worker`. |
| No predictions | Check that a CHAMPION model exists (Model Performance). With < 1,500 verified matches, training refuses (`INSUFFICIENT_DATA`). |
| Wrong bet entry | My Bets → Correct (a reason is required; the before/after snapshot is kept). |
| Bad model promoted | Model Performance → promote the previous version (rollback). Archived predictions are never altered. |
| Identity conflicts | Data Sources → Identity review: MERGE, NEW_PLAYER or REJECT. Nothing is merged automatically. |

## Backups and restore
The `backup` service writes `backups/ttq_<UTC>.sql.gz` daily and keeps 14 days.
Restore: `gunzip -c backups/<file> | docker compose exec -T db psql -U ttq ttq`.

## CLI
`python -m ttq.cli {seed-demo|ingest|predict|settle|monitor|retrain|train-force|hash-password}` (add `--live` for live data with `train-force`).
