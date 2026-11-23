from datetime import timedelta

import pandas as pd

from ttq.core.timeutil import utcnow
from ttq.models import ModelVersion, Prediction


def test_health_and_auth(client):
    from fastapi.testclient import TestClient
    from ttq.main import app
    assert TestClient(app).get("/api/health").json()["db"] == "ok"
    assert TestClient(app).get("/api/overview").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    assert client.get("/api/overview").status_code == 200


def test_backtest_uses_only_quotes_available_at_decision_time(f, db):
    from ttq.services.backtest import _load
    a, b = f.player(), f.player()
    t = utcnow() - timedelta(days=1)
    m = f.match(a, b, at=t, status="FINISHED", sets=(3, 0))
    db.add(Prediction(match_id=m.id, as_of=t, p1_win=0.6, p1_ci_low=0.55, p1_ci_high=0.65, is_backtest=True))
    from ttq.models import OddsQuote
    for cap, dec in ((t - timedelta(hours=5), 2.5), (t - timedelta(minutes=10), 1.2)):  # late quote is after the cutoff
        for sel in ("p1", "p2"):
            db.add(OddsQuote(match_id=m.id, bookmaker_key="hardrock", market="match_winner", selection=sel, american=150,
                             decimal_odds=dec, captured_at=cap, source_key="t"))
    db.flush()
    df = _load(db, False, decision_minutes=30, delay_minutes=2)
    assert df.iloc[0]["dec_hardrock_p1"] == 2.5


def test_settings_validation(client):
    assert client.put("/api/settings/filters", json={"bogus": 1}).status_code == 422
    assert client.put("/api/settings/filters", json={"min_ev": 0.05}).json()["min_ev"] == 0.05
