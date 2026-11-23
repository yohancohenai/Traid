# Run TT Elite Quant Pro on your Mac (free)

Everything runs locally: official TT Elite results, the model, your bet ledger. Nothing to buy.

## One-time setup (about 20 minutes, plus about 45 minutes of automatic background work)

### 1. Check your Mac
Apple menu  → **About This Mac**: note the **Chip** (Apple M1/M2/M3/M4 or Intel) and **memory** (8 GB minimum).

### 2. Install Docker Desktop (free for personal use)
1. https://www.docker.com/products/docker-desktop/ → **Download for Mac**, choosing **Apple Silicon** or **Intel** to match your chip.
2. Open `Docker.dmg` and drag **Docker** into **Applications**. Open it, accept the terms (sign-in is optional).
3. ⚙️ **Settings → General**: tick **"Start Docker Desktop when you sign in to your computer"**.
4. ⚙️ **Settings → Resources**: **Memory ≥ 4 GB** → **Apply & restart**. Wait until the whale icon in the menu bar settles.

### 3. Download the app (no git needed)
1. Sign in to GitHub, open https://github.com/yohancohenai/Traid/tree/claude/tt-elite-quant-pro-6b6pj7
2. Green **Code** button → **Download ZIP**. Unzip it and move the folder somewhere permanent (e.g. Documents).

### 4. Start it
1. Open **Terminal** (⌘ + Space, type Terminal, Enter).
2. Type `cd ` (with a space), drag the **`tt-elite-quant-pro`** folder onto the Terminal window, and press Enter.
3. Run:
   ```bash
   bash deploy/mac-start.sh
   ```
4. **Write down the password** shown in the `####` box (user `admin`). It's also stored in `.env` in that folder.
5. The first build takes 5–10 minutes; then http://localhost:3000 opens. Log in.

### 5. Wait for the first real data (~45 min, automatic)
The official TT Elite history downloads in the background (~35 min), then the first model trains. LIVE pages stay
mostly empty until it finishes. Watch progress (optional):
`docker compose exec api tail -f /app/artifacts/first_run.log` (Ctrl+C to stop watching)

### If something goes wrong
| Symptom | Fix |
|---|---|
| `docker: command not found` | Install Docker Desktop (step 2) and open it once. |
| "Docker Desktop did not start" | Open Docker, wait for the whale icon to settle, re-run the command. |
| Download ZIP asks to sign in / 404 | Sign in to GitHub with the account that owns the repository. |
| Browser "can't connect" | Wait 1–2 min after the build and refresh; `docker compose ps` should show everything running. |
| Forgot password | Open `.env` in the folder (Finder: ⌘⇧. shows hidden files) → `TTQ_ADMIN_PASSWORD`. |

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
TTQ_LAN=1 bash deploy/mac-start.sh
```
It prints an address like `http://your-mac.local:3000`. Open that on your phone. Only devices on your home network can
reach it. For access away from home, install **Tailscale** (free) on the Mac and the phone.

## Useful commands (in the tt-elite-quant-pro folder)
```bash
bash deploy/mac-start.sh                 # start / update after `git pull`
docker compose ps                     # status
docker compose logs -f worker         # scheduler activity
docker compose down                   # stop (data is kept)
```
Backups are written daily to `./backups/`.
