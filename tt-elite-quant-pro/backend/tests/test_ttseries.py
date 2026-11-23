"""tt-series.com provider: parsing on real saved pages, timezone handling, ingest, politeness."""
from datetime import date, datetime, time, timezone
from pathlib import Path

import httpx
import pytest

from ttq.models import Match, Player, Tournament
from ttq.providers.ttseries import (RateLimiter, TTSeriesResultsProvider, classify_result, has_next_page, local_to_utc,
                                    name_first_last, parse_tournament, parse_tournament_list)
from ttq.services.ingest import upsert_match, validate_result

F = Path(__file__).parent / "fixtures" / "ttseries"


def page(name):
    return (F / name).read_text(encoding="utf-8")


def test_list_page():
    cards = parse_tournament_list(page("list.html"))
    assert len(cards) >= 20
    assert {c.venue for c in cards} <= {"OSP", "OSP2", "HSC", "HSC2", "POCZESNA", "BLACHOWNIA"}
    assert all(c.tid > 0 for c in cards)
    assert has_next_page(page("list.html"))


def test_finished_tournament():
    ms = parse_tournament(page("finished_50.html"), 50)
    assert len(ms) == 15 and all(m.status == "FINISHED" for m in ms)
    for m in ms:
        assert validate_result(m)[0], m             # sets add up, games valid (11, win by 2, deuce)
        assert m.p1_ref and m.p2_ref and m.p1_ref != m.p2_ref
        assert "," not in m.p1_name                 # "Surname, First" -> "First Surname"
        assert m.finished_at > m.scheduled_at
    assert ms[0].source_ref == "tts-50-1" and ms[0].tournament_ref == "tts-50"
    assert ms[0].scheduled_at == datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)   # 11:00 Warsaw (CET)


def test_night_tournament_rolls_past_midnight_and_is_scheduled():
    ms = parse_tournament(page("inprogress.html"), 424)
    assert len(ms) == 10 and all(m.status == "SCHEDULED" and m.sets_p1 is None for m in ms)
    assert ms[0].scheduled_at == datetime(2026, 11, 24, 22, 5, tzinfo=timezone.utc)   # 23:05 local
    assert ms[-1].scheduled_at == datetime(2026, 11, 25, 1, 35, tzinfo=timezone.utc)  # 02:35 local next day
    assert [m.scheduled_at for m in ms] == sorted(m.scheduled_at for m in ms)


def test_unknown_page_returns_nothing():
    assert parse_tournament("<html><body>Nothing here</body></html>", 99999) == []


def test_dst_conversion():
    assert local_to_utc(date(2026, 7, 1), time(12, 0)) == datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)   # CEST
    assert local_to_utc(date(2026, 1, 1), time(12, 0)) == datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)   # CET


def test_names_and_result_cells():
    assert name_first_last("Kurek, Pawel") == "Pawel Kurek"
    assert name_first_last("Wiśniewski, Łukasz") == "Łukasz Wiśniewski"
    assert classify_result('3:1<div class="ttes-muted">9:11, 11:8, 11:6, 11:6</div>')[:3] == ("FINISHED", 3, 1)
    assert classify_result("–")[0] == "SCHEDULED"
    assert classify_result("WO 3:0")[0] == "WALKOVER"
    assert classify_result("Przerwany")[0] == "RETIRED"
    assert classify_result("Anulowany")[0] == "CANCELLED"
    assert classify_result("???")[0] == "SCHEDULED"   # unknown: never guessed as a result


def test_ingest_verified_idempotent_and_stable_players(db):
    p = TTSeriesResultsProvider(client=httpx.Client(), rate=RateLimiter(0))
    ms = parse_tournament(page("finished_50.html"), 50)
    for m in ms:
        upsert_match(db, m, p)
    db.flush()
    assert db.query(Match).count() == 15
    assert all(m.result_verified and m.status == "FINISHED" and len(m.sets) == m.sets_p1 + m.sets_p2 for m in db.query(Match))
    n_players = db.query(Player).count()
    assert n_players <= 6
    for m in ms:   # re-ingest: no duplicates, verified finals untouched
        upsert_match(db, m, p)
    assert db.query(Match).count() == 15 and db.query(Player).count() == n_players
    assert db.query(Tournament).filter_by(source_ref="tts-50").count() == 1


def test_complete_tournaments_are_skipped(db):
    from ttq.services.jobs import complete_tournament_refs
    p = TTSeriesResultsProvider(client=httpx.Client(), rate=RateLimiter(0))
    for m in parse_tournament(page("finished_50.html"), 50):
        upsert_match(db, m, p)
    for m in parse_tournament(page("inprogress.html"), 424):
        upsert_match(db, m, p)
    db.flush()
    assert complete_tournament_refs(db, "ttseries") == {"tts-50"}


def test_fetch_uses_list_window_and_skips_complete(monkeypatch):
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if "ttes_tournament" in str(req.url):
            return httpx.Response(200, text=page("inprogress.html"))
        return httpx.Response(200, text=page("list.html").replace('rel="next"', ''))

    p = TTSeriesResultsProvider(client=httpx.Client(transport=httpx.MockTransport(handler)), rate=RateLimiter(0))
    cards = parse_tournament_list(page("list.html"))
    p.skip_refs = {f"tts-{cards[0].tid}"}
    since = datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc)
    ms, raw = p.fetch_matches(since, datetime(2026, 11, 26, tzinfo=timezone.utc))
    assert cards[0].tid not in raw["tournaments"]
    assert len(calls) == 1 + len(raw["tournaments"])
    assert all("User-Agent" for _ in calls)


def test_rate_limiter_spacing():
    t = [0.0]
    slept = []
    rl = RateLimiter(5, clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    rl.wait(); t[0] += 1; rl.wait(); rl.wait()
    assert slept == [4, 5]


def test_http_errors_raise_unavailable():
    from ttq.providers.base import ProviderUnavailable
    p = TTSeriesResultsProvider(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
                                rate=RateLimiter(0))
    with pytest.raises(ProviderUnavailable):
        p.get("/tournaments/")


def test_ensure_source_survives_concurrent_create(engine):
    """Worker and backfill both create the 'ttseries' source at startup: the loser must not crash."""
    from sqlalchemy import text
    from ttq.core import db as dbmod
    from ttq.models import DataSource
    from ttq.services.ingest import ensure_source
    with engine.begin() as c:
        c.execute(text("TRUNCATE data_sources RESTART IDENTITY CASCADE"))
    a, b = dbmod.SessionLocal(), dbmod.SessionLocal()
    try:
        assert b.query(DataSource).count() == 0          # b's view: source does not exist yet
        ensure_source(a, "ttseries", "x", "results", False)
        a.commit()                                       # a wins the race
        real_scalar, calls = b.scalar, []

        def stale_first_lookup(*args, **kw):   # b looked before a committed (the real race)
            calls.append(1)
            return None if len(calls) == 1 else real_scalar(*args, **kw)
        b.scalar = stale_first_lookup
        s = ensure_source(b, "ttseries", "x", "results", False)   # b inserts -> conflict -> re-reads
        assert len(calls) == 2
        b.commit()
        assert s.key == "ttseries" and b.query(DataSource).count() == 1
    finally:
        a.close(); b.close()
