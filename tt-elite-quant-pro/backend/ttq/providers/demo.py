"""DEMO provider: a deterministic synthetic TT-Elite-like world. Every record it produces is flagged DEMO.

It exists so the full pipeline (ingest -> ratings -> predictions -> EV -> bets -> settlement) can be exercised
without licensed data. Nothing produced here is real, and the UI labels it DEMO everywhere.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone

import numpy as np

from ttq.odds.math import decimal_to_american
from ttq.providers.base import OddsProvider, ProviderMatch, ProviderQuote, ResultsProvider

FIRST = ["Łukasz", "Paweł", "Michał", "Krzysztof", "Tomasz", "Piotr", "Marcin", "Jakub", "Grzegorz", "Wojciech",
         "Mateusz", "Kamil", "Rafał", "Dawid", "Szymon", "Bartłomiej", "Adrian", "Przemysław", "Sebastian", "Damian",
         "Andrzej", "Janusz", "Jan", "Zbigniew", "Maciej", "Artur", "Radosław", "Mirosław", "Daniel", "Patryk"]
LAST = ["Kowalski", "Wiśniewski", "Wójcik", "Kowalczyk", "Kamiński", "Lewandowski", "Zieliński", "Szymański",
        "Woźniak", "Dąbrowski", "Kozłowski", "Jankowski", "Mazur", "Kwiatkowski", "Krawczyk", "Piotrowski",
        "Grabowski", "Nowakowski", "Pawłowski", "Michalski", "Nowicki", "Adamczyk", "Dudek", "Zając", "Wieczorek",
        "Jabłoński", "Król", "Majewski", "Olszewski", "Jaworski", "Malinowski", "Stępień", "Górski", "Rutkowski",
        "Sikora", "Baran", "Ostrowski", "Michałowski", "Pietrzak", "Wróbel"]

N_PLAYERS = 96
HISTORY_DAYS = 300
FUTURE_DAYS = 2
SLOT_MIN = 30


def _rng(*parts) -> np.random.Generator:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "little"))


class DemoWorld:
    """Deterministic given (seed, anchor). anchor = midnight UTC of the world's 'day 0'."""

    def __init__(self, seed: int = 7, anchor: datetime | None = None):
        self.seed = seed
        if anchor is None:
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            anchor = today - timedelta(days=HISTORY_DAYS)
        self.anchor = anchor
        r = _rng(seed, "players")
        names = set()
        self.players = []
        while len(self.players) < N_PLAYERS:
            n = f"{r.choice(FIRST)} {r.choice(LAST)}"
            if n in names:
                continue
            names.add(n)
            self.players.append({"ref": f"demo-p{len(self.players)+1}", "name": n,
                                 "skill0": float(r.normal(0, 0.42)), "debut_day": int(r.integers(0, HISTORY_DAYS // 2)) if len(self.players) > 70 else 0})
        self._skill_cache: dict[int, np.ndarray] = {}
        self.matches = self._generate()

    def skill(self, i: int, day: int) -> float:
        if i not in self._skill_cache:
            r = _rng(self.seed, "walk", i)
            steps = r.normal(0, 0.03, HISTORY_DAYS + FUTURE_DAYS + 5)
            self._skill_cache[i] = self.players[i]["skill0"] + np.cumsum(steps)
        return float(self._skill_cache[i][day])

    def _generate(self):
        out = []
        for day in range(HISTORY_DAYS + FUTURE_DAYS + 1):
            r = _rng(self.seed, "day", day)
            active = [i for i, p in enumerate(self.players) if p["debut_day"] <= day]
            n_groups = 6
            chosen = r.choice(active, size=n_groups * 5, replace=False)
            for g in range(n_groups):
                grp = [int(x) for x in chosen[g * 5:(g + 1) * 5]]
                tref = f"demo-t{day}-{g}"
                level = "major" if (day % 7 == 6 and g == 0) else "standard"
                pairs = [(grp[i], grp[j]) for i in range(5) for j in range(i + 1, 5)]
                r.shuffle(pairs)
                start = self.anchor + timedelta(days=day, hours=8 + 2 * g)
                for k, (a, b) in enumerate(pairs):
                    sched = start + timedelta(minutes=SLOT_MIN * k * 0.6)
                    sched = sched.replace(second=0, microsecond=0)
                    out.append(self._sim_match(day, g, k, a, b, sched, tref, level))
        return out

    def _sim_match(self, day, g, k, a, b, sched, tref, level):
        r = _rng(self.seed, "match", day, g, k)
        d = self.skill(a, day) - self.skill(b, day) + r.normal(0, 0.15)  # daily form noise
        p_match_true = 1 / (1 + math.exp(-d))
        # point prob consistent with match prob (approx mapping)
        p_point = 0.5 + 0.075 * d / (1 + 0.15 * abs(d))
        sets, pts = [0, 0], []
        while max(sets) < 3:
            x = y = 0
            while not ((x >= 11 or y >= 11) and abs(x - y) >= 2):
                if r.random() < p_point:
                    x += 1
                else:
                    y += 1
            pts.append((x, y))
            sets[0 if x > y else 1] += 1
        dur = sum(x + y for x, y in pts) * 0.45 + 4  # minutes
        rare = r.random()
        status = "FINISHED"
        if rare < 0.004:
            status = "RETIRED"
        elif rare < 0.007:
            status = "CANCELLED"
        has_points = r.random() > 0.2
        mid = f"demo-m{day}-{g}-{k}"
        return {"ref": mid, "a": a, "b": b, "sched": sched, "finish": sched + timedelta(minutes=dur), "tref": tref,
                "level": level, "sets": sets, "pts": pts if has_points else [], "status": status,
                "p_true": p_match_true, "day": day, "group": g}

    def _pm(self, m, now) -> ProviderMatch:
        A, B = self.players[m["a"]], self.players[m["b"]]
        base = dict(source_ref=m["ref"], p1_name=A["name"], p2_name=B["name"], p1_ref=A["ref"], p2_ref=B["ref"],
                    scheduled_at=m["sched"], tournament_ref=m["tref"],
                    tournament_name=f"DEMO TT Elite-like Series D{m['day']} G{m['group']+1}",
                    tournament_level=m["level"])
        if m["status"] == "CANCELLED":
            if now >= m["sched"] - timedelta(minutes=30):
                return ProviderMatch(status="CANCELLED", **base)
            return ProviderMatch(status="SCHEDULED", **base)
        if now < m["sched"]:
            return ProviderMatch(status="SCHEDULED", **base)
        if now < m["finish"]:
            # live: reveal completed sets and progress of the current set
            frac = (now - m["sched"]) / (m["finish"] - m["sched"])
            total_pts = sum(x + y for x, y in m["pts"]) or 1
            target = frac * total_pts
            sets = [0, 0]; cur = (0, 0); acc = 0
            raw_pts = m["pts"] or [(11, 0)]
            for x, y in raw_pts:
                if acc + x + y <= target:
                    acc += x + y; sets[0 if x > y else 1] += 1
                else:
                    need = int(target - acc)
                    cx = round(x * need / (x + y)); cur = (cx, need - cx)
                    break
            return ProviderMatch(status="LIVE", live_state={"sets": sets, "points": list(cur),
                                                            "observed_at": now.isoformat()}, **base)
        if m["status"] == "RETIRED":
            pts = m["pts"][:max(1, len(m["pts"]) - 1)]
            s1 = sum(1 for x, y in pts if x > y); s2 = len(pts) - s1
            return ProviderMatch(status="RETIRED", finished_at=m["finish"], sets_p1=s1, sets_p2=s2,
                                 set_points=pts, **base)
        return ProviderMatch(status="FINISHED", finished_at=m["finish"], sets_p1=m["sets"][0], sets_p2=m["sets"][1],
                             set_points=list(m["pts"]), **base)

    def matches_between(self, since, until, now):
        return [self._pm(m, now) for m in self.matches if since <= m["sched"] <= until]


_WORLD: DemoWorld | None = None


def get_world(anchor: datetime | None = None) -> DemoWorld:
    global _WORLD
    if _WORLD is None or (anchor is not None and _WORLD.anchor != anchor):
        _WORLD = DemoWorld(anchor=anchor)
    return _WORLD


class DemoResultsProvider(ResultsProvider):
    key = "demo_results"
    name = "DEMO synthetic results"
    is_demo = True
    verified = True

    def __init__(self, world: DemoWorld | None = None, clock=None):
        self.world = world or get_world()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch_matches(self, since, until):
        now = self.clock()
        ms = self.world.matches_between(since, until, now)
        return ms, {"demo": True, "count": len(ms), "since": since.isoformat(), "until": until.isoformat()}


def _book_quotes(m, book, margin, noise, now, r, kind):
    lt = math.log(m["p_true"] / (1 - m["p_true"])) + r.normal(0, noise)
    p = 1 / (1 + math.exp(-lt))
    # apply margin with power-like skew
    k = 1.0
    ps = [p, 1 - p]
    tot = 1 + margin
    imp = [x * tot for x in ps]
    out = []
    for sel, ip in zip(("p1", "p2"), imp):
        dec = round(max(1.01, 1 / min(ip, 0.995)), 2)
        out.append((sel, dec))
    return out


class DemoOddsProvider(OddsProvider):
    """Synthetic Hard Rock / DraftKings-like quotes. Opening line ~18h before start (noisier), current line
    sharper as start approaches. Captured 'now'; becomes STALE after the freshness window like any quote."""
    key = "demo_odds"
    name = "DEMO synthetic odds"
    is_demo = True
    verified = True
    bookmakers = ("hardrock", "draftkings")
    BOOKS = {"hardrock": (0.065, 1.0), "draftkings": (0.055, 0.9)}

    def __init__(self, world: DemoWorld | None = None, clock=None):
        self.world = world or get_world()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def quotes_for(self, m, at: datetime, opening=False) -> list[ProviderQuote]:
        A, B = self.world.players[m["a"]], self.world.players[m["b"]]
        hours_out = max((m["sched"] - at).total_seconds() / 3600, 0)
        noise = 0.38 if opening else 0.16 + 0.012 * min(hours_out, 18)
        res = []
        for book, (margin, nm) in self.BOOKS.items():
            r = _rng(self.world.seed, "odds", m["ref"], book, "open" if opening else int(at.timestamp() // 1800))
            for sel, dec in _book_quotes(m, book, margin, noise * nm, at, r, "open" if opening else "cur"):
                res.append(ProviderQuote(event_ref=m["ref"], match_source_ref=m["ref"], p1_name=A["name"],
                                         p2_name=B["name"], commence_time=m["sched"], bookmaker_key=book,
                                         market="match_winner", selection=sel, decimal_odds=dec,
                                         american=decimal_to_american(dec), quoted_at=at,
                                         settlement_rules="DEMO: match must be completed; retirement voids."))
        return res

    def fetch_odds(self, now):
        horizon = now + timedelta(hours=36)
        out = []
        for m in self.world.matches:
            if now < m["sched"] <= horizon and m["status"] != "CANCELLED":
                out.extend(self.quotes_for(m, now))
        return out, {"demo": True, "count": len(out), "at": now.isoformat()}
