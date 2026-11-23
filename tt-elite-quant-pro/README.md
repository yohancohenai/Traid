# TT Elite Quant Pro

A research platform for **TT Elite Series table tennis**. It computes independent win probabilities and compares them
with **Hard Rock Bet** prices. It ranks potential mispricings by estimated EV and uncertainty, and lets you **manually**
record the bets you actually place. It tracks results, settlement, P/L and bankroll. DraftKings is shown as a
**reference only** and is never executable in Florida.

> This software never places, automates or submits wagers. Estimated EV is conditional on the model being accurate and
> is not a guarantee of profit. When evidence is insufficient the app says **NO QUALIFYING BETS FOUND.**
> If gambling stops being fun: 1-800-GAMBLER.

**Read first:** [docs/LIMITATIONS.md](docs/LIMITATIONS.md) · [docs/DATA_PROVIDERS.md](docs/DATA_PROVIDERS.md) ·
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/RUNBOOK.md](docs/RUNBOOK.md)

## Screenshots (DEMO mode)
![Overview](docs/screenshots/overview.png)
![Opportunities](docs/screenshots/opportunities.png)

## Data status
* **Results and schedule:** official, from www.tt-series.com (the TT Elite Series organiser's public site), polled politely.
  On a fresh install, run `python -m ttq.cli backfill-ttseries --from-id 1`, then `python -m ttq.cli train-force --live`.
* **Hard Rock odds:** upload a screenshot of the Hard Rock TT Elite list (free local OCR, you confirm each row), or type them in. There is no public Hard Rock API.
* **DEMO:** a separate synthetic world for trying the app. It is labelled DEMO everywhere and never mixed with live data.

## Quick start on a Mac (free): see [deploy/MAC.md](deploy/MAC.md)
```bash
./deploy/mac-start.sh            # Docker Desktop required; prints your login on first run
```

## Quick start (Docker, generic)
```bash
cp .env.example .env            # set POSTGRES_PASSWORD, TTQ_JWT_SECRET, admin password
docker compose up -d --build    # db, redis, api :8000, worker, frontend :3000, backup
docker compose exec api python -m ttq.cli seed-demo   # optional: load the DEMO world (~3-5 min)
open http://localhost:3000
```

## Local development
Requirements: Python 3.12+, PostgreSQL 16, Redis 7, Node 22.
```bash
# backend
cd backend
pip install -e ".[dev]"
createdb ttq && export TTQ_DATABASE_URL=postgresql+psycopg://USER:PASS@localhost:5432/ttq
alembic upgrade head
python -m ttq.cli seed-demo            # DEMO data + first model + backtest
uvicorn ttq.main:app --reload --port 8000
python -m ttq.worker                   # scheduler in another shell

# frontend
cd ../frontend && cp .env.example .env.local && npm install && npm run dev
```

## Tests
```bash
cd backend && createdb ttq_test && pytest          # 68 tests; uses TTQ_TEST_DATABASE_URL or the local ttq_test db
cd frontend && npm run build && npm start &        # then:
npx playwright test --trace off                    # 12 e2e tests; needs the API on :8000 with DEMO data seeded
```

## Deployment
* Run the compose stack behind an HTTPS reverse proxy (Caddy, nginx). Expose only the proxy.
* Set strong `TTQ_JWT_SECRET` and `TTQ_ADMIN_PASSWORD_HASH` (`python -m ttq.cli hash-password --password ...`).
* Set `NEXT_PUBLIC_API_URL` to the public API URL at **build** time, and `TTQ_CORS_ORIGINS` to the frontend origin.
* Migrations run automatically on API start (`alembic upgrade head`). Backups land in `./backups` daily.
* Set `TTQ_ENABLE_DEMO=false` once a real source is configured, to hide DEMO data generation.

## What is where
| Path | Purpose |
|---|---|
| `backend/ttq/providers` | adapter interface, DEMO world, The Odds API (unverified), CSV import |
| `backend/ttq/identity` + `services/identity.py` | Polish name normalisation, alias matching, manual review queue |
| `backend/ttq/ratings/engines.py` | Elo, Dynamic Elo, Glicko-2, hierarchical Bayes, set-weighted Elo, Bradley–Terry |
| `backend/ttq/features/builder.py` | leakage-safe chronological features |
| `backend/ttq/ml/train.py` | chronological splits, Optuna, LR / LightGBM / CatBoost / ensemble / stacking, calibration |
| `backend/ttq/sim/tt.py` | exact best-of-five / deuce / service-rotation probability engine |
| `backend/ttq/services/scanner.py` | no-vig, EV, uncertainty-adjusted EV, research filters |
| `backend/ttq/services/bets.py`, `settlement.py`, `performance.py` | real-money ledger, settlement, bankroll |
| `backend/ttq/services/backtest.py` | walk-forward backtests, baselines, bootstrap CIs, filter selection |
| `backend/ttq/services/monitoring.py`, `jobs.py`, `worker.py` | drift, gated retraining, alerts, scheduler |
| `frontend/` | Next.js dashboard |
