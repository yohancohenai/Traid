import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("TTQ_DATABASE_URL", os.environ.get("TTQ_TEST_DATABASE_URL", "postgresql+psycopg://ttq:ttq@localhost:5432/ttq_test"))
os.environ["TTQ_ENABLE_DEMO"] = "false"
os.environ["TTQ_ARTIFACTS_DIR"] = "/tmp/ttq_test_artifacts"

import pytest
from sqlalchemy import text

from ttq.core.config import get_settings
get_settings.cache_clear()
from ttq.core import db as dbmod
from ttq.core.db import Base
import ttq.models as M
from ttq.core.timeutil import utcnow


@pytest.fixture(scope="session")
def engine():
    eng = dbmod.reset_engine(os.environ["TTQ_DATABASE_URL"])
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng


@pytest.fixture()
def db(engine):
    with engine.begin() as c:
        c.execute(text("TRUNCATE " + ", ".join(t.name for t in reversed(Base.metadata.sorted_tables)) + " RESTART IDENTITY CASCADE"))
    s = dbmod.SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient
    from ttq.main import app
    c = TestClient(app)
    tok = c.post("/api/auth/login", json={"username": "admin", "password": "change-me"}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


class Factory:
    def __init__(self, db):
        self.db = db
        self.n = 0

    def player(self, name=None, demo=False):
        self.n += 1
        from ttq.identity.names import normalize_name
        name = name or f"Player {chr(65 + self.n % 26)}{self.n}"
        p = M.Player(canonical_name=name, normalized_name=normalize_name(name), is_demo=demo)
        self.db.add(p); self.db.flush()
        return p

    def match(self, p1, p2, at=None, status="SCHEDULED", sets=None, demo=False, verified=True, points=None):
        self.n += 1
        at = at or utcnow() + timedelta(hours=3)
        m = M.Match(source_key="test", source_ref=f"m{self.n}", player1_id=p1.id, player2_id=p2.id, scheduled_at=at,
                    status=status, is_demo=demo, result_sources=[])
        if sets:
            m.sets_p1, m.sets_p2 = sets
            m.winner_id = p1.id if sets[0] > sets[1] else p2.id
            m.finished_at = at + timedelta(minutes=40)
            m.result_verified = verified
        self.db.add(m); self.db.flush()
        for i, (a, b) in enumerate(points or [], 1):
            self.db.add(M.MatchSet(match_id=m.id, set_no=i, p1_points=a, p2_points=b))
        self.db.flush()
        return m

    def quote(self, m, sel, american, book="hardrock", age_s=10, market="match_winner", line=None, closing=False, demo=False):
        from ttq.odds.math import american_to_decimal
        q = M.OddsQuote(match_id=m.id, bookmaker_key=book, market=market, selection=sel, line=line, american=american,
                        decimal_odds=american_to_decimal(american), captured_at=utcnow() - timedelta(seconds=age_s),
                        quoted_at=utcnow() - timedelta(seconds=age_s), source_key="test", is_closing=closing, is_demo=demo)
        self.db.add(q); self.db.flush()
        return q

    def prediction(self, m, p1=0.6, lo=0.55, hi=0.65, dq="HIGH", demo=False):
        pr = M.Prediction(match_id=m.id, as_of=utcnow(), p1_win=p1, p1_ci_low=lo, p1_ci_high=hi,
                          component_probs={"a": p1, "b": p1 + 0.01}, features={"_n1": 50, "_n2": 50, "elo_diff": 80},
                          data_quality=dq, is_demo=demo)
        self.db.add(pr); self.db.flush()
        return pr


@pytest.fixture()
def f(db):
    return Factory(db)
