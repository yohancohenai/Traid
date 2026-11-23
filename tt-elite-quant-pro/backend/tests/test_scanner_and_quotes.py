from datetime import timedelta

from ttq.core.timeutil import utcnow
from ttq.models import Bet, Recommendation
from ttq.services.app_settings import set_setting
from ttq.services.scanner import is_executable, quote_status, scan


def _setup(f, db, p1=0.62, hr=(-105, -115), age=10):
    a, b = f.player(), f.player()
    m = f.match(a, b)
    f.prediction(m, p1=p1, lo=p1 - 0.03, hi=p1 + 0.03)
    q1 = f.quote(m, "p1", hr[0], age_s=age)
    q2 = f.quote(m, "p2", hr[1], age_s=age)
    return m, q1, q2


def test_draftkings_never_executable_in_florida():
    assert is_executable("hardrock", "US-FL")
    assert not is_executable("draftkings", "US-FL")
    assert not is_executable("draftkings")


def test_stale_quote_cannot_be_verified(f, db):
    m, q1, _ = _setup(f, db, age=3600)
    assert quote_status(q1, m, 600) == "STALE"
    m2, q2, _ = _setup(f, db, age=5)
    assert quote_status(q2, m2, 600) == "VERIFIED"
    q2.availability = "SUSPENDED"
    assert quote_status(q2, m2, 600) == "STALE"
    assert quote_status(None, m2, 600) == "UNAVAILABLE"
    m2.scheduled_at = utcnow() - timedelta(minutes=1)
    q2.availability = "OPEN"
    assert quote_status(q2, m2, 600) == "STALE"   # started matches are never verified


def test_qualifies_only_with_fresh_quote_and_never_auto_places(f, db):
    set_setting(db, "filters", {"min_player_matches": 0})
    _setup(f, db, p1=0.62)
    res = scan(db)
    recs = db.query(Recommendation).all()
    p1 = [r for r in recs if r.selection == "p1"][0]
    assert p1.status == "QUALIFIES" and p1.quote_status == "VERIFIED"
    assert db.query(Bet).count() == 0     # recommendations are never bets
    _setup(f, db, p1=0.62, age=3600)
    scan(db)
    stale = [r for r in db.query(Recommendation).all() if r.quote_status == "STALE"]
    assert stale and all(r.status != "QUALIFIES" for r in stale)


def test_no_bet_when_no_edge(f, db, client):
    _setup(f, db, p1=0.50, hr=(-110, -110))
    db.commit()
    scan(db); db.commit()
    r = client.get("/api/opportunities").json()
    assert r["qualifying"] == 0 and r["message"] == "NO QUALIFYING BETS FOUND."


def test_manual_quotes_have_source_and_timestamp(f, db, client):
    a, b = f.player(), f.player()
    m = f.match(a, b)
    db.commit()
    r = client.post("/api/odds/manual", json=[{"match_id": m.id, "selection": "p1", "american": -120},
                                               {"match_id": m.id, "selection": "p2", "american": 100}])
    assert r.status_code == 200, r.text
    for q in r.json()["stored"]:
        assert q["source"] == "manual" and q["captured_at"] and q["freshness"] == "VERIFIED"
    assert client.post("/api/odds/manual", json=[{"match_id": m.id, "selection": "p1", "american": 50}]).status_code == 422


def test_draftkings_quote_marked_reference_only(f, db, client):
    m, *_ = _setup(f, db)
    f.quote(m, "p1", -110, book="draftkings")
    db.commit()
    r = client.get(f"/api/odds/{m.id}").json()
    assert r["books"]["draftkings"]["executable_in_fl"] is False
    assert all(q["executable"] is False for q in r["books"]["draftkings"]["quotes"].values())


def test_demo_and_live_are_separated(f, db, client):
    a, b = f.player(demo=True), f.player(demo=True)
    f.match(a, b, demo=True)
    db.commit()
    assert client.get("/api/matches?demo=false").json() == []
    assert len(client.get("/api/matches?demo=true").json()) == 1
    assert all(x["is_demo"] for x in client.get("/api/matches?demo=true").json())


def test_unchanged_price_refreshes_freshness_without_duplicate_rows(f, db):
    from ttq.models import OddsQuote
    from ttq.providers.base import OddsProvider, ProviderQuote
    from ttq.services.ingest import ingest_odds
    a, b = f.player(), f.player()
    m = f.match(a, b)

    class P(OddsProvider):
        key, name, verified = "t", "t", True
        price = -110

        def fetch_odds(self, now):
            return [ProviderQuote(event_ref="e", match_source_ref=m.source_ref, p1_name="", p2_name="", commence_time=m.scheduled_at,
                                  bookmaker_key="hardrock", market="match_winner", selection="p1", american=self.price)], {}

    p = P()
    ingest_odds(db, p, utcnow() - timedelta(minutes=20))
    ingest_odds(db, p, utcnow())
    qs = db.query(OddsQuote).all()
    assert len(qs) == 1 and quote_status(qs[0], m, 600) == "VERIFIED"
    p.price = -120
    ingest_odds(db, p, utcnow())
    assert db.query(OddsQuote).count() == 2
