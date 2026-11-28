"""OddsPapi market data for TT Elite picks: Hard Rock's real price + a fair price from reference books.

Main mode: BULK SWEEPS. /v4/odds-by-tournaments returns every upcoming TT Elite match for ONE bookmaker in ONE
request. A sweep = Hard Rock + the reference books (default DraftKings, bet365) = 3 credits, covering every match on
the board. TT Elite boards fill in the last ~hour before each match, so each sweep covers the matches starting
soon; how often sweeps run sets the coverage (env ODDSPAPI_SWEEP_MINUTES).

Credits are scarce (free plan: 250 requests/month), so every request is counted, including failed ones:
  - at most `daily_cap` requests per UTC day and `monthly_cap` per month (stored in app_settings["oddspapi_usage"]);
  - the fixture list (1 request covers ~2 days of TT Elite) is refreshed only when a pick needs it, at most every
    3 hours;
  - one odds request per pick candidate, only before the match starts (the free plan has no live odds), and each
    match is checked once.
Without a key, or with the budget spent, everything returns None and picks go out as before (minimum price only).
"""
from __future__ import annotations

import logging
import os
import statistics
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from ttq.core.timeutil import as_utc, utcnow
from ttq.identity.names import strip_diacritics
from ttq.models import AppSetting

log = logging.getLogger(__name__)

BASE = "https://api.oddspapi.io/v4"
TT_ELITE_TOURNAMENT = 36377
WINNER = "251"
HARD_ROCK = "hardrockbet"
FIXTURE_REFRESH = timedelta(hours=24)  # the TT Elite list (2 days ahead) is re-read at most once a day


def api_key() -> str:
    return os.environ.get("ODDSPAPI_KEY", "")


def caps() -> tuple[int, int]:
    return int(os.environ.get("ODDSPAPI_DAILY_CAP", "7")), int(os.environ.get("ODDSPAPI_MONTHLY_CAP", "240"))


# ------------------------------------------------------------------ budget
def _get_row(db: Session, key: str) -> dict:
    row = db.get(AppSetting, key)
    return dict(row.value) if row else {}


def _put_row(db: Session, key: str, value: dict) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()


def usage(db: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    u = _get_row(db, "oddspapi_usage")
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    return {"day": day, "month": month, "today": u.get("days", {}).get(day, 0), "this_month": u.get("months", {}).get(month, 0)}


def paced_allowance(d_cap: int, now: datetime) -> int:
    """Spread the daily credits over the day: by hour h at most ceil(cap * (h + 6) / 24) may be used, so a
    2-credit Hard Rock + DraftKings check is always possible from midnight UTC."""
    import math
    hours = now.hour + now.minute / 60
    return min(d_cap, math.ceil(d_cap * (hours + 6) / 24))


def can_spend(db: Session, n: int = 1, now: datetime | None = None) -> bool:
    if not api_key():
        return False
    now = now or utcnow()
    u = usage(db, now)
    d, m = caps()
    return u["today"] + n <= paced_allowance(d, now) and u["this_month"] + n <= m


def _record(db: Session, now: datetime) -> None:
    u = _get_row(db, "oddspapi_usage")
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    days = {k: v for k, v in u.get("days", {}).items() if k >= (now - timedelta(days=40)).strftime("%Y-%m-%d")}
    months = dict(u.get("months", {}))
    days[day] = days.get(day, 0) + 1
    months[month] = months.get(month, 0) + 1
    _put_row(db, "oddspapi_usage", {"days": days, "months": months})


def _request(db: Session, path: str, now: datetime, **params):
    """One counted request. Returns parsed JSON or None. Never logs the key."""
    _record(db, now)
    params["apiKey"] = api_key()
    try:
        r = httpx.get(f"{BASE}/{path}", params=params, timeout=30)
    except Exception as e:  # noqa
        log.warning("oddspapi %s failed: %s", path, e.__class__.__name__)
        return None
    if r.status_code != 200:
        try:
            msg = (r.json().get("error") or {}).get("code")
        except Exception:  # noqa
            msg = None
        log.warning("oddspapi %s: HTTP %s %s", path, r.status_code, msg)
        return None
    return r.json()


# ------------------------------------------------------------------ names and matching
def norm(name: str) -> frozenset:
    """'Brunner, Marian' and 'Marian Brunner' -> the same token set."""
    s = strip_diacritics(name or "").lower().replace(",", " ").replace(".", " ").replace("-", " ")
    return frozenset(t for t in s.split() if t)


def find_fixture(fixtures: list[dict], p1: str, p2: str, start: datetime) -> tuple[dict, bool] | None:
    """Returns (fixture, flipped) where flipped means OddsPapi lists our player 2 first."""
    a, b = norm(p1), norm(p2)
    best = None
    for f in fixtures:
        st = datetime.fromisoformat(f["startTime"].replace("Z", "+00:00"))
        if abs((st - as_utc(start)).total_seconds()) > 45 * 60:
            continue
        x, y = norm(f.get("participant1Name", "")), norm(f.get("participant2Name", ""))
        if (x, y) == (a, b):
            best = (f, False)
        elif (x, y) == (b, a):
            best = (f, True)
    return best


def fixtures(db: Session, need_start: datetime, now: datetime | None = None) -> list[dict]:
    """Cached TT Elite fixture list; refreshed (1 credit) only when called after a cache miss, at most every 6 h."""
    now = now or utcnow()
    cache = _get_row(db, "oddspapi_fixtures")
    fx = cache.get("fixtures", [])
    fetched = datetime.fromisoformat(cache["fetched_at"]) if cache.get("fetched_at") else None
    if fetched and now - fetched < FIXTURE_REFRESH:     # at most one list request every 3 hours
        return fx
    if not can_spend(db, 2, now):          # keep 1 credit for the odds call itself
        return fx
    until = (now + timedelta(days=2)).strftime("%Y-%m-%d")
    data = _request(db, "fixtures", now, tournamentId=TT_ELITE_TOURNAMENT,
                    **{"from": now.strftime("%Y-%m-%d"), "to": until})
    if data is None:
        return fx
    keep = [{"fixtureId": f["fixtureId"], "startTime": f["startTime"], "participant1Name": f.get("participant1Name", ""),
             "participant2Name": f.get("participant2Name", ""), "statusName": f.get("statusName", "")}
            for f in data if f.get("statusName") != "Cancelled"]
    _put_row(db, "oddspapi_fixtures", {"fixtures": keep, "fetched_at": now.isoformat(), "until": until})
    return keep


# ------------------------------------------------------------------ board parsing
def winner_pairs(board: dict) -> dict[str, tuple[float, float]]:
    out = {}
    for slug, book in (board.get("bookmakerOdds") or {}).items():
        if "+" in slug or slug in ("demo", "singbet-b"):
            continue
        if book.get("suspended") or book.get("bookmakerIsActive") is False:
            continue
        legs = ((book.get("markets") or {}).get(WINNER) or {}).get("outcomes", {})
        try:
            a, b = legs["251"]["players"]["0"], legs["252"]["players"]["0"]
        except KeyError:
            continue
        if a.get("active") is False or b.get("active") is False:
            continue
        pa, pb = float(a["price"]), float(b["price"])
        if pa <= 1.0 or pb <= 1.0 or 1 / pa + 1 / pb <= 1.0:
            continue
        out[slug] = (pa, pb)
    return out


def consensus_p1(pairs: dict[str, tuple[float, float]]) -> float | None:
    """Median no-vig probability for participant 1 over distinct price pairs (book skins share pairs)."""
    distinct = set(pairs.values())
    if len(distinct) < 3:
        return None
    return statistics.median((1 / a) / (1 / a + 1 / b) for a, b in distinct)


def market_check(db: Session, p1_name: str, p2_name: str, start: datetime, now: datetime | None = None) -> dict | None:
    """Hard Rock's Winner prices and the consensus, oriented to OUR player 1. None if unavailable or no budget."""
    now = now or utcnow()
    if not api_key() or as_utc(start) <= now + timedelta(minutes=2):
        return None
    cached = _get_row(db, "oddspapi_fixtures").get("fixtures", [])
    hit = find_fixture(cached, p1_name, p2_name, start)
    if not hit:                                    # only a miss can cost a list request
        hit = find_fixture(fixtures(db, start, now), p1_name, p2_name, start)
    if not hit or not can_spend(db, 1, now):
        return {"status": "no_fixture" if not hit else "no_budget"}
    f, flipped = hit
    board = _request(db, "odds", now, fixtureId=f["fixtureId"])
    if board is None:
        return {"status": "error"}
    pairs = winner_pairs(board)
    if flipped:
        pairs = {k: (b, a) for k, (a, b) in pairs.items()}
    hr = pairs.get(HARD_ROCK)
    refs = {k: v for k, v in pairs.items() if k != HARD_ROCK}
    cons = consensus_p1(refs)
    if cons is None and refs:                       # fewer than 3 distinct books: use what there is
        cons, _ = fair_p1(refs, list(refs))
    return {"status": "ok", "books": len(refs), "hard_rock": hr, "consensus_p1": cons, "fixture_id": f["fixtureId"],
            "flipped": flipped, "refs": refs}


def board_by_fixture(db: Session, fixture_id: str, flipped: bool, now: datetime | None = None) -> dict | None:
    """Re-read one known fixture (1 credit), e.g. for the closing price. Oriented to our player 1."""
    now = now or utcnow()
    if not can_spend(db, 1, now):
        return None
    board = _request(db, "odds", now, fixtureId=fixture_id)
    if board is None:
        return None
    pairs = winner_pairs(board)
    if flipped:
        pairs = {k: (b, a) for k, (a, b) in pairs.items()}
    return {"status": "ok", "books": len(pairs), "hard_rock": pairs.get(HARD_ROCK), "consensus_p1": consensus_p1(pairs)}


# ------------------------------------------------------------------ bulk sweeps (all matches, one book per credit)
def ref_books() -> list[str]:
    return [b.strip() for b in os.environ.get("ODDSPAPI_REF_BOOKS", "draftkings").split(",") if b.strip()]


def sweep_minutes() -> int:
    return int(os.environ.get("ODDSPAPI_SWEEP_MINUTES", "420"))


def sweep_fresh_minutes() -> int:
    """How long a board counts as live prices (Hard Rock moves; keep it short)."""
    return int(os.environ.get("ODDSPAPI_FRESH_MINUTES", "50"))


def sweep_status(db: Session, now: datetime | None = None) -> dict:
    """Short summary for the run log: when the last sweep ran, how many matches each book priced, credits used."""
    now = now or utcnow()
    sw = latest_sweep(db)
    per_book: dict[str, int] = {}
    for b in sw.get("boards", {}).values():
        for slug in b.get("books", {}):
            per_book[slug] = per_book.get(slug, 0) + 1
    age = round((now - datetime.fromisoformat(sw["fetched_at"])).total_seconds() / 60) if sw.get("fetched_at") else None
    checks = (_get_row(db, "market_checks").get("items") or [])[-6:]
    recent = [{"at": c.get("at", "")[11:16], "match": c.get("match"), "pick": c.get("pick"), "sent": c.get("sent"),
               "reason": c.get("reason")} for c in checks]
    cov = (_get_row(db, "oddspapi_coverage").get("items") or [])[-4:]
    return {"last_sweep_min_ago": age, "matches": len(sw.get("boards", {})), "priced_by": per_book,
            "usage": usage(db, now), "recent_market_checks": recent, "coverage": cov}


def fair_p1(pairs: dict[str, tuple[float, float]], books: list[str]) -> tuple[float | None, int]:
    """Median no-vig chance for participant 1 across the reference books that price the match."""
    vals = [(1 / a) / (1 / a + 1 / b) for slug, (a, b) in pairs.items() if slug in books]
    return (statistics.median(vals), len(vals)) if vals else (None, 0)


def latest_sweep(db: Session) -> dict:
    return _get_row(db, "oddspapi_sweep")


NEED_GAP_MIN = int(os.environ.get("ODDSPAPI_NEED_GAP_MINUTES", "45"))   # a pick candidate missing from the last sweep triggers a new one, at most this often


def sweep(db: Session, now: datetime | None = None, force: bool = False, need: bool = False) -> dict:
    """Run one bulk sweep if it's due (or a pick candidate needs it), and the budget allows. Stores all boards."""
    import time
    now = now or utcnow()
    if not api_key():
        return {"swept": False, "why": "no key"}
    last = latest_sweep(db)
    gap = NEED_GAP_MIN if need else sweep_minutes()
    if not force and last.get("fetched_at") and \
            now - datetime.fromisoformat(last["fetched_at"]) < timedelta(minutes=gap):
        return {"swept": False, "why": "not due"}
    # Hard Rock coverage of TT Elite on OddsPapi is patchy: "alt" adds it on every other sweep to measure when (how
    # long before start) Hard Rock prices appear, without halving the number of market sweeps.
    mode = os.environ.get("ODDSPAPI_SWEEP_HARDROCK", "1")
    with_hr = mode == "1" or (mode == "alt" and HARD_ROCK not in (last.get("books") or []))
    books = ([HARD_ROCK] if with_hr else []) + ref_books()
    cache = _get_row(db, "oddspapi_fixtures")
    fx_fresh = cache.get("fetched_at") and now - datetime.fromisoformat(cache["fetched_at"]) < FIXTURE_REFRESH
    cost = len(books) + (0 if fx_fresh else 1)
    reserve = int(os.environ.get("ODDSPAPI_VERIFY_RESERVE", "0")) if need else 0
    if not can_spend(db, cost, now) or usage(db, now)["today"] + cost + reserve > caps()[0]:
        return {"swept": False, "why": f"budget (needs {cost}, keeping {reserve} for Hard Rock checks)"}
    names = {f["fixtureId"]: f for f in fixtures(db, now + timedelta(hours=2), now)} if not fx_fresh else \
        {f["fixtureId"]: f for f in cache.get("fixtures", [])}
    boards: dict[str, dict] = {}
    returned: dict[str, int] = {}
    for i, slug in enumerate(books):
        if i:
            time.sleep(1.2)                       # endpoint rate limit: 1 call per second
        data = _request(db, "odds-by-tournaments", now, tournamentIds=str(TT_ELITE_TOURNAMENT), bookmaker=slug)
        returned[slug] = len(data or [])
        for f in data or []:
            if f.get("statusId", 0) != 0:          # only matches that haven't started
                continue
            fid = f["fixtureId"]
            pr = winner_pairs({"bookmakerOdds": {slug: (f.get("bookmakerOdds") or {}).get(slug, {})}}).get(slug)
            if not pr:
                continue
            meta = names.get(fid, {})
            b = boards.setdefault(fid, {"start": f.get("startTime"), "p1": meta.get("participant1Name", ""),
                                        "p2": meta.get("participant2Name", ""), "books": {}})
            b["books"][slug] = list(pr)
    _put_row(db, "oddspapi_sweep", {"fetched_at": now.isoformat(), "boards": boards, "books": books})
    n_hr = sum(1 for b in boards.values() if HARD_ROCK in b["books"])
    _log_coverage(db, now, books, returned, boards)
    return {"swept": True, "matches": len(boards), "with_hard_rock": n_hr, "credits": cost}


def _lead(b: dict, now: datetime) -> int | None:
    try:
        return round((datetime.fromisoformat(b["start"].replace("Z", "+00:00")) - now).total_seconds() / 60)
    except Exception:  # noqa
        return None


def _log_coverage(db: Session, now: datetime, books: list[str], returned: dict, boards: dict) -> None:
    """Which books priced which matches, by minutes before start: tells when Hard Rock's TT lines appear."""
    entry = {"at": now.isoformat()[:16], "books": books, "returned": returned,
             "priced": {s: sum(1 for b in boards.values() if s in b["books"]) for s in books}}
    for s in books:
        leads = sorted(x for x in (_lead(b, now) for b in boards.values() if s in b["books"]) if x is not None)
        entry[f"{s}_leads"] = leads[:40]
    items = (_get_row(db, "oddspapi_coverage").get("items") or [])[-199:] + [entry]
    _put_row(db, "oddspapi_coverage", {"items": items})


def from_sweep(db: Session, p1_name: str, p2_name: str, start: datetime, now: datetime | None = None,
               max_age_min: int | None = None) -> dict | None:
    """Market data for one match from the latest sweep (no credits). A sweep stays usable until the next one is due
    (every pick still says "bet only if Hard Rock >= X", so a moved price is caught when you place it)."""
    now = now or utcnow()
    max_age_min = max_age_min or sweep_fresh_minutes()
    sw = latest_sweep(db)
    if not sw.get("fetched_at") or now - datetime.fromisoformat(sw["fetched_at"]) > timedelta(minutes=max_age_min):
        return {"status": "no fresh sweep"}
    rows = [{"fixtureId": fid, "startTime": b["start"], "participant1Name": b["p1"], "participant2Name": b["p2"]}
            for fid, b in sw.get("boards", {}).items() if b.get("start")]
    hit = find_fixture(rows, p1_name, p2_name, start)
    if not hit:
        return {"status": "not in sweep"}
    f, flipped = hit
    pairs = {k: tuple(v) for k, v in sw["boards"][f["fixtureId"]]["books"].items()}
    if flipped:
        pairs = {k: (b, a) for k, (a, b) in pairs.items()}
    fair, n = fair_p1(pairs, ref_books())
    return {"status": "ok", "books": n, "hard_rock": pairs.get(HARD_ROCK), "consensus_p1": fair,
            "fixture_id": f["fixtureId"], "flipped": flipped, "swept_at": sw["fetched_at"],
            "refs": {k: v for k, v in pairs.items() if k != HARD_ROCK}}

