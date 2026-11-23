# Known limitations (read before relying on anything)

1. **No verified live data source yet.** There is no verified TT Elite results feed and no verified Hard Rock odds
   feed. Real use requires (a) a licensed results provider or licensed CSV exports, and (b) manual Hard Rock entry or a
   contracted aggregator. Until then, LIVE mode is empty, and **"NO QUALIFYING BETS FOUND."** is the correct output.
2. **DEMO results say nothing about real profitability.** In DEMO data the synthetic "market" is generated as
   truth plus noise, so the model can beat it by construction. The DEMO backtest showing positive ROI is a pipeline
   test, not evidence of an edge. Seed run (test period, champion = stacked model): 426 paper bets, ROI +13.0%
   (bootstrap 95% CI +6.7% to +19.5%), but average CLV −0.25%. The synthetic market is noisy even at the close,
   so CLV cannot show skill there. Probability accuracy: model log loss 0.498 vs Hard Rock no-vig 0.517 on the same
   matches. Real books will not be this beatable.
3. **Real markets are much sharper.** Expect real TT Elite closing lines to be hard to beat. Claim profitability only
   with ≥ several hundred genuinely out-of-sample real bets, a positive bootstrap ROI lower bound, and positive CLV.
4. **Point-level markets** (totals, point handicaps) assume independent points with a constant probability. They are
   not validated for staking and are capped at WATCH. Service-specific modelling needs verified serve data, which no
   source provides.
5. **Retirement/walkover rules** differ between books, so these always go to manual settlement review.
6. **Live analysis** uses the results feed's score plus the pre-match strength. No licensed live odds feed exists, so
   live odds show UNAVAILABLE.
7. **Edges above `max_ev` (default 25%)** never qualify. They are shown as WATCH with a "verify the price"
   reason, because such gaps are far more often bad data than real value.
8. **Probability intervals** are heuristic (Bayesian strength uncertainty plus model disagreement), not guaranteed coverage.
9. **Single-operator auth.** One admin account (JWT). Put the app behind HTTPS (reverse proxy) before exposing it.
10. Docker images were written but **not built in the development sandbox** (no Docker daemon). Run
   `docker compose up --build` and the test suite on first deployment.
11. Hard Rock Bet terms prohibit automated access to its site and apps. This software never logs in, scrapes or bets.
