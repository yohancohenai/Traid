# Architecture

```
providers (demo | the_odds_api | csv | manual) ──► ingest (raw_observations, identity, validation)
        │                                                   │
        ▼                                                   ▼
   odds_quotes ◄── closing-line marking            matches / match_sets / players / aliases
        │                                                   │
        │                     FeatureBuilder (event replay: PREDICT before UPDATE at equal timestamps)
        │                       ├─ rating engines: Elo, Dynamic Elo, Glicko-2, hierarchical Bayes, set-weighted Elo, Bradley–Terry
        │                       └─ form / H2H / sets & points / workload / common opponents (shrunk)
        │                                                   │
        │                ML: train | tune (Optuna, ablation) | calib (Platt/isotonic/temperature) | test (untouched)
        │                    logistic, LightGBM, CatBoost, averaged ensemble, stacked (time-series OOF)
        │                                                   │
        └──────────► scanner (no-vig, EV, EV@lower-bound, edge, filters) ──► recommendations (QUALIFIES/WATCH/PASS)
                                                            │
                                    user confirms in UI ──► bets (ledger A) ──► settlement ──► bankroll
                    recommendations hypothetical (ledger B) · backtest paper trades (ledger C)
```

* **Backend:** FastAPI + SQLAlchemy 2 + Alembic on PostgreSQL. Redis is used for health checks. The app degrades
  gracefully without it.
* **Worker:** APScheduler (`python -m ttq.worker`). Ingests results every 2 min and odds every 3 min. Predicts and
  scans every 5 min, settles every 2 min, monitors every 10 min, and runs gated retraining daily.
* **Frontend:** Next.js + TypeScript + Tailwind, a client of the REST API.
* **Time:** all timestamps are stored as `timestamptz` in UTC. The UI renders them in `TTQ_USER_TIMEZONE`.

## Key invariants (each covered by tests)
| Invariant | Where |
|---|---|
| Features use only results known strictly before the match starts; simultaneous matches are invisible to each other | `features/builder.py`, `tests/test_leakage_and_models.py` |
| Predictions are append-only, with `as_of` | `models.Prediction`, `services/modeling.py` |
| Fuzzy player names are never auto-merged | `services/identity.py`, `tests/test_identity.py` |
| A quote is VERIFIED only if fresh, open, pre-start and sourced; freshness is re-evaluated at read time | `scanner.quote_status`, `api/serialize.rec_out` |
| DraftKings is never executable in Florida | `scanner.is_executable`, `bets.confirm_bet` |
| Recommendations never become bets without user confirmation | `bets.confirm_bet` is the only writer of `bets` |
| Bet corrections write `bet_revisions` and audit logs | `bets.correct_bet` |
| Three ledgers never mix | `bets` / `recommendations.hypothetical_*` / `paper_trades` |
| Champion is chosen on the CALIB period, never on TEST and never on ROI | `ml/train.py`, `modeling.train_and_register` |
| Research filters are selected on the CALIB period | `backtest.select_filters` |

## Model notes
* **Hierarchical Bayes** (`BayesGaussian`): Gaussian skill posteriors updated by a Laplace/ADF step. New players get
  an empirical-Bayes population prior (partial pooling), and variance grows with inactivity. It provides the
  credible-interval input for uncertainty.
* **Probability interval** shown to the user: logit(p) ± 1.645·√((scale·σ_bayes)² + σ²_model-disagreement). This is a
  heuristic interval, not a frequentist guarantee. `uncertainty_scale` is configurable.
* **Simulator** (`sim/tt.py`): exact dynamic programming for games to 11, win by 2, deuce, service rotation
  (2 serves, then 1 at deuce) and best of five. It maps match probability to per-game and per-point probabilities,
  and from there to scorelines, set handicaps, total points and point handicaps. Point-level markets are labelled
  EXPERIMENTAL or UNSUPPORTED depending on point-data coverage. Derivative markets are capped at WATCH.
