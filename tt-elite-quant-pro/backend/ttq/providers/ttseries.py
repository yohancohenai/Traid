"""Official TT Elite Series results and schedule from the organiser's public site, www.tt-series.com.

Access policy (checked 2026-11-23):
- robots.txt disallows only /wp-admin/.
- The rules and integrity pages contain no clause restricting automated reading; results are published publicly
  (rule 13.4).
We still keep the load minimal: identified User-Agent, at most one request per `min_interval` seconds, and finished
tournaments are never re-fetched.

Page facts:
- Times are Europe/Warsaw local.
- A tournament is a round robin on one table, so matches are sequential.
- Night tournaments run past midnight: a row whose time is earlier than the tournament start belongs to the next day.
"""
from __future__ import annotations

import html as htmllib
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from ttq.core.config import get_settings
from ttq.providers.base import ProviderMatch, ProviderUnavailable, ResultsProvider

log = logging.getLogger(__name__)
WARSAW = ZoneInfo("Europe/Warsaw")
BASE = "https://www.tt-series.com"
UA = "TTEliteQuantPro/1.0 (personal non-commercial research)"
LAST_MATCH_MINUTES = 25  # conservative duration estimate for the final match of a tournament

_TAG = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return " ".join(htmllib.unescape(_TAG.sub(" ", s)).split())


def name_first_last(raw: str) -> str:
    """'Kurek, Pawel' -> 'Pawel Kurek'. Names without a comma are returned unchanged."""
    raw = " ".join(raw.split())
    if "," in raw:
        last, first = raw.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return raw


def local_to_utc(d: date, t: dtime) -> datetime:
    return datetime.combine(d, t, tzinfo=WARSAW).astimezone(timezone.utc)


@dataclass
class TournamentCard:
    tid: int
    venue: str
    local_start: datetime  # naive Warsaw local
    title: str


def parse_tournament_list(page: str) -> list[TournamentCard]:
    out = []
    for art in re.findall(r'<article class="event">(.*?)</article>', page, flags=re.S):
        tid = re.search(r"ttes_tournament=(\d+)", art)
        dt = re.search(r'<div class="date">\s*(\d{4}-\d{2}-\d{2})\s*·\s*(\d{1,2}:\d{2})', art)
        if not tid or not dt:
            continue
        chips = [_text(c) for c in re.findall(r'<span class="chip">(.*?)</span>', art, flags=re.S)]
        venue = next((c for c in chips if c and c.upper() == c and "TOURNAMENT" not in c.upper()), chips[-1] if chips else "")
        title = _text((re.search(r"<h3>(.*?)</h3>", art, flags=re.S) or [None, ""])[1])
        out.append(TournamentCard(int(tid.group(1)), venue,
                                  datetime.strptime(f"{dt.group(1)} {dt.group(2)}", "%Y-%m-%d %H:%M"), title))
    return out


def has_next_page(page: str) -> bool:
    return bool(re.search(r'ttes_mod_page=\d+"[^>]*rel="next"', page))


_SCORE = re.compile(r"^\s*(\d)\s*:\s*(\d)\s*$")
_GAME = re.compile(r"(\d{1,2})\s*:\s*(\d{1,2})")


def classify_result(cell_html: str) -> tuple[str, int | None, int | None, list[tuple[int, int]], str]:
    """Return (status, sets_p1, sets_p2, game_points, raw_text) for one result cell."""
    muted = re.search(r'<div class="ttes-muted">(.*?)</div>', cell_html, flags=re.S)
    games_txt = _text(muted.group(1)) if muted else ""
    main_txt = _text(re.sub(r'<div class="ttes-muted">.*?</div>', "", cell_html, flags=re.S))
    raw = f"{main_txt} {games_txt}".strip()
    low = raw.lower()
    if main_txt in ("–", "-", "—", ""):
        return "SCHEDULED", None, None, [], raw
    if re.search(r"\bw\.?o\b|walk", low):
        m = re.search(r"(\d)\s*:\s*(\d)", main_txt)
        return "WALKOVER", (int(m.group(1)) if m else None), (int(m.group(2)) if m else None), [], raw
    if re.search(r"przerw|krecz|ret", low):
        return "RETIRED", None, None, [(int(a), int(b)) for a, b in _GAME.findall(games_txt)], raw
    if re.search(r"anul|odwo|cancel", low):
        return "CANCELLED", None, None, [], raw
    m = _SCORE.match(main_txt)
    if m:
        return "FINISHED", int(m.group(1)), int(m.group(2)), [(int(a), int(b)) for a, b in _GAME.findall(games_txt)], raw
    log.warning("unrecognised tt-series result cell; treating as SCHEDULED", extra={"event": raw[:80]})
    return "SCHEDULED", None, None, [], raw


def parse_tournament(page: str, tid: int) -> list[ProviderMatch]:
    """Parse one tournament page. Returns [] if the page has no tournament (e.g. unknown id)."""
    head = re.search(r"<h2>\s*(.*?)\s*–\s*Turniej\s*·\s*(\d{1,2}:\d{2})\s*</h2>\s*<p class=\"ttes-muted\">\s*(\d{4}-\d{2}-\d{2})",
                     page, flags=re.S)
    if not head:
        return []
    venue = _text(head.group(1))
    start_t = datetime.strptime(head.group(2), "%H:%M").time()
    start_d = datetime.strptime(head.group(3), "%Y-%m-%d").date()
    rows = re.findall(r"<tr>\s*<td>(\d+)</td>\s*<td>(\d{1,2}:\d{2})</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>",
                      page, flags=re.S)
    parsed = []
    for nr, hhmm, p1_html, res_html, p2_html in rows:
        t = datetime.strptime(hhmm, "%H:%M").time()
        d = start_d + timedelta(days=1) if t < start_t else start_d  # night tournaments cross midnight
        p1id = re.search(r"ttes_player=(\d+)", p1_html)
        p2id = re.search(r"ttes_player=(\d+)", p2_html)
        status, s1, s2, games, raw = classify_result(res_html)
        parsed.append((int(nr), local_to_utc(d, t), name_first_last(_text(p1_html)), p1id.group(1) if p1id else None,
                       name_first_last(_text(p2_html)), p2id.group(1) if p2id else None, status, s1, s2, games))
    parsed.sort(key=lambda r: r[1])
    out = []
    tname = f"TT Elite Series {venue} {start_d.isoformat()} {head.group(2)}"
    for i, (nr, at, n1, r1, n2, r2, status, s1, s2, games) in enumerate(parsed):
        finished_at = None
        if status in ("FINISHED", "RETIRED", "WALKOVER"):
            nxt = parsed[i + 1][1] if i + 1 < len(parsed) else None
            finished_at = nxt if nxt and nxt > at else at + timedelta(minutes=LAST_MATCH_MINUTES)
        out.append(ProviderMatch(
            source_ref=f"tts-{tid}-{nr}", p1_name=n1, p2_name=n2, p1_ref=r1, p2_ref=r2, scheduled_at=at,
            status=status, tournament_ref=f"tts-{tid}", tournament_name=tname, tournament_level="standard",
            finished_at=finished_at, sets_p1=s1, sets_p2=s2, set_points=games, best_of=5))
    return out


class RateLimiter:
    """Process-wide minimum spacing between requests to the site."""

    def __init__(self, min_interval: float, clock=time.monotonic, sleep=time.sleep):
        self.min_interval, self.clock, self.sleep = min_interval, clock, sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = self.clock()
            if self._last is not None:
                gap = self.min_interval - (now - self._last)
                if gap > 0:
                    self.sleep(gap)
                    now = self.clock()
            self._last = now


_LIMITER: RateLimiter | None = None


def limiter() -> RateLimiter:
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = RateLimiter(get_settings().ttseries_min_interval_seconds)
    return _LIMITER


class TTSeriesResultsProvider(ResultsProvider):
    key = "ttseries"
    name = "TT Elite Series official (tt-series.com)"
    is_demo = False
    verified = True  # official organiser results

    def __init__(self, client: httpx.Client | None = None, rate: RateLimiter | None = None, skip_refs: set[str] | None = None):
        self.client = client or httpx.Client(timeout=30, headers={"User-Agent": UA}, follow_redirects=True)
        self.rate = rate or limiter()
        self.skip_refs = skip_refs or set()
        self.requests = 0

    def get(self, path: str) -> str:
        last_err = None
        for attempt in range(3):
            self.rate.wait()
            self.requests += 1
            try:
                r = self.client.get(f"{BASE}{path}")
                if r.status_code == 200:
                    return r.text
                if r.status_code in (403, 404, 410, 429):
                    raise ProviderUnavailable(f"tt-series.com returned HTTP {r.status_code} for {path}")
                last_err = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last_err = str(e)
            time.sleep(2 ** attempt)
        raise ProviderUnavailable(f"tt-series.com unreachable for {path}: {last_err}")

    def list_tournaments(self, max_pages: int = 2) -> list[TournamentCard]:
        cards = []
        for p in range(1, max_pages + 1):
            page = self.get("/tournaments/" + (f"?ttes_mod_page={p}" if p > 1 else ""))
            cards += parse_tournament_list(page)
            if not has_next_page(page):
                break
        return cards

    def fetch_tournament(self, tid: int) -> tuple[list[ProviderMatch], str]:
        page = self.get(f"/tournaments/?ttes_tournament={tid}")
        return parse_tournament(page, tid), page

    def fetch_matches(self, since: datetime, until: datetime):
        lo = since.astimezone(WARSAW).replace(tzinfo=None) - timedelta(hours=12)
        hi = until.astimezone(WARSAW).replace(tzinfo=None)
        cards = [c for c in self.list_tournaments() if lo <= c.local_start <= hi and f"tts-{c.tid}" not in self.skip_refs]
        matches = []
        for c in cards:
            ms, _ = self.fetch_tournament(c.tid)
            matches += ms
        return matches, {"tournaments": [c.tid for c in cards], "requests": self.requests,
                         "skipped_complete": len(self.skip_refs)}
