# Run TT Elite Quant Pro on your Mac (free)

Everything runs locally: official TT Elite results, the model, your bet ledger. Nothing to buy.

## One-time setup (≈10 minutes, plus a 35-minute background download)
1. Install **Docker Desktop** (free for personal use): https://www.docker.com/products/docker-desktop/
   In Docker Desktop → Settings → General, tick **"Start Docker Desktop when you sign in"**.
2. Get the code (Terminal):
   ```bash
   git clone -b claude/tt-elite-quant-pro-6b6pj7 https://github.com/yohancohenai/Traid.git
   cd Traid/tt-elite-quant-pro
   ./deploy/mac-start.sh
   ```
   The first run prints your **login password once** (it's also kept in `.env` in that folder), builds the app,
   opens http://localhost:3000, and starts downloading the official TT Elite history plus training the first model
   in the background. Watch progress with: `docker compose exec api tail -f /app/artifacts/first_run.log`

## Every day
* The app restarts by itself whenever your Mac is on (Docker restarts it). To open it, go to http://localhost:3000.
* If the Mac was off, the app catches up on missed results automatically (within ~10 minutes of waking).
* To keep updating while you're away from the desk: System Settings → Battery/Energy → "Prevent automatic sleeping
  when the display is off" (optional).

## Entering Hard Rock prices from screenshots
1. In the Hard Rock app, open Table Tennis → TT Elite Series and take a screenshot of the list (moneyline column visible).
2. In TT Elite Quant Pro, go to **Odds Comparison** → **Hard Rock screenshot import**, upload it
   (from your phone too, see below).
3. Check each proposed row against the app. Fix anything misread (amber rows need attention), then press **Save
   confirmed prices**. Opportunities re-scan within seconds.
4. Prices count as verified for 10 minutes, so upload right before you decide.

## Use it from your phone (same Wi-Fi)
```bash
TTQ_LAN=1 ./deploy/mac-start.sh
```
It prints an address like `http://your-mac.local:3000`. Open that on your phone. Only devices on your home network can
reach it. For access away from home, install **Tailscale** (free) on the Mac and the phone.

## Useful commands (in the tt-elite-quant-pro folder)
```bash
./deploy/mac-start.sh                 # start / update after `git pull`
docker compose ps                     # status
docker compose logs -f worker         # scheduler activity
docker compose down                   # stop (data is kept)
```
Backups are written daily to `./backups/`.
