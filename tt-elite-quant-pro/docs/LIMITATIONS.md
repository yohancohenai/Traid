# Known limitations (read before relying on anything)

1. **No verified live data source yet.** There is no verified TT Elite results feed and no verified Hard Rock odds
   feed. Real use requires (a) a licensed results provider or licensed CSV exports, and (b) manual Hard Rock entry or a
   contracted aggregator. Until then, LIVE mode is empty, and **"NO QUALIFYING BETS FOUND."** is the correct output.
2. **DEMO results say nothing about real profitability.** In DEMO data the synthetic "market" is generated as
   truth plus noise, so the model can beat it by construction. The DEMO backtest showing positive ROI is a pipeline
   test, not evidence of an edge.
3. **Real markets are much sharper.** Expect real TT Elite closing lines to be hard to beat. Claim profitability only
   with ≥ several hundred genuinely out-of-sample real bets, a positive bootstrap ROI lower bound, and positive CLV.
4. **Point-level markets** (totals, point handicaps) assume independent points with a constant probability. They are
   not validated for staking and are capped at WATCH. Service-specific modelling needs verified serve data, which no
   source provides.
5. **Retirement/walkover rules** differ between books, so these always go to manual settlement review.
6. **Live analysis** uses the results feed's score plus the pre-match strength. No licensed live odds feed exists, so
   live odds show UNAVAILABLE.
7. **Probability intervals** are heuristic (Bayesian strength uncertainty plus model disagreement), not guaranteed coverage.
8. **Single-operator auth.** One admin account (JWT). Put the app behind HTTPS (reverse proxy) before exposing it.
9. Docker images were written but **not built in the development sandbox** (no Docker daemon). Run
   `docker compose up --build` and the test suite on first deployment.
10. Hard Rock Bet terms prohibit automated access to its site and apps. This software never logs in, scrapes or bets.
