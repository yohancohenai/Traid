"""One-off OddsPapi probe (about 6 credits): does Hard Rock Bet price TT Elite Series, and which books do?
Prints only odds/coverage facts, never the API key."""
import os, statistics, sys, time
from datetime import datetime, timedelta, timezone

import requests

KEY = os.environ.get("ODDSPAPI_KEY", "")
BASE = "https://api.oddspapi.io/v4"
TT_ELITE = 36377
calls = 0


def get(path, **params):
    global calls
    params["apiKey"] = KEY
    r = requests.get(f"{BASE}/{path}", params=params, timeout=120)
    calls += 1
    if r.status_code != 200:
        try:
            msg = r.json()
        except Exception:  # noqa
            msg = r.text[:300]
        print(f"  {path}: HTTP {r.status_code} {str(msg)[:300]}")
        return None
    return r.json()


def winner(book):
    legs = ((book.get("markets") or {}).get("251") or {}).get("outcomes", {})
    try:
        return legs["251"]["players"]["0"]["price"], legs["252"]["players"]["0"]["price"]
    except KeyError:
        return None


if not KEY:
    sys.exit("ODDSPAPI_KEY secret is empty")
now = datetime.now(timezone.utc)
fx = get("fixtures", tournamentId=TT_ELITE, **{"from": now.strftime("%Y-%m-%d"),
                                               "to": (now + timedelta(days=2)).strftime("%Y-%m-%d")})
if fx is None:
    sys.exit(f"fixtures call failed (credits used: {calls})")
ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
ahead = sorted((f for f in fx if f.get("statusName") != "Cancelled" and ts(f["startTime"]) > now),
               key=lambda f: f["startTime"])
print(f"TT Elite fixtures in the next 2 days: {len(ahead)}, with odds: {sum(1 for f in ahead if f.get('hasOdds'))}")
seen_hr = 0
for f in ahead[:4]:
    mins = (ts(f["startTime"]) - now).total_seconds() / 60
    board = get("odds", fixtureId=f["fixtureId"])
    time.sleep(1.2)
    if not board:
        continue
    books = board.get("bookmakerOdds", {})
    pairs = {s: winner(b) for s, b in books.items()}
    pairs = {s: p for s, p in pairs.items() if p}
    cons = statistics.median((1 / a) / (1 / a + 1 / b) for a, b in set(pairs.values())) if pairs else None
    hr = pairs.get("hardrockbet")
    seen_hr += bool(hr)
    print(f"{f['participant1Name']} v {f['participant2Name']}  in {mins:.0f} min: {len(books)} books, "
          f"{len(pairs)} winner quotes, consensus P1 {cons:.1%}" if cons else f"{f['participant1Name']}: no winner quotes")
    print(f"   hardrockbet: {hr}   sbobet: {pairs.get('sbobet')}   draftkings: {pairs.get('draftkings')}   "
          f"fanduel: {pairs.get('fanduel')}")
    us = sorted(s for s in books if any(k in s for k in ("hardrock", "draftkings", "fanduel", "betmgm", "caesars", "espn", "fanatics")))
    print(f"   US books on board: {us}")
print(f"\nHard Rock priced {seen_hr} of the fixtures checked. Credits used by this probe: {calls}")
