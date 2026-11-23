"""Price-target digests and the test-alert command."""
from datetime import timedelta

import httpx
import pytest

from ttq.core.timeutil import utcnow
from ttq.models import Alert
from ttq.odds.math import american_to_decimal
from ttq.services.app_settings import get_filters, set_setting
from ttq.services.targets import build_digest, price_targets_job, round_up_american, side_target

F = {"min_ev": 0.03, "min_ev_low": 0.0, "min_decimal_odds": 1.25, "max_decimal_odds": 4.0, "max_ev": 0.25}


def test_side_target_math_and_conservative_rounding():
    t = side_target(0.62, 0.57, F)
    assert t == pytest.approx(max(1.03 / 0.62, 1 / 0.57, 1.25))          # 1.7544, from the uncertainty bound
    am = round_up_american(t)
    assert am == -130 and american_to_decimal(am) >= t                    # never below what is needed
    assert side_target(0.2, 0.15, F) is None                              # would need > 4.0 decimal
    assert side_target(0.62, 0.30, {**F, "max_ev": 0.05}) is None          # beyond the plausibility cap
    for d in (1.05, 1.5, 1.9901, 2.0, 2.351, 3.7):
        assert american_to_decimal(round_up_american(d)) >= d - 1e-9


def _confident_match(f, db, minutes=40, p1=0.66, dq="HIGH", demo=False):
    a, b = f.player("Pawel Kurek", demo=demo), f.player("Grzegorz Wichowski", demo=demo)
    m = f.match(a, b, at=utcnow() + timedelta(minutes=minutes), demo=demo)
    f.prediction(m, p1=p1, lo=p1 - 0.04, hi=p1 + 0.04, dq=dq, demo=demo)
    return m


def test_digest_selects_window_quality_and_never_repeats(f, db):
    set_setting(db, "filters", {"min_player_matches": 0})
    m = _confident_match(f, db, 40)
    _confident_match(f, db, 200)                   # outside the 75-minute window
    _confident_match(f, db, 30, dq="LOW")          # fails data-quality filter
    d = build_digest(db)
    assert d and d["match_ids"] == [m.id]
    assert "Kurek 66%" in d["text"] and "or better" in d["text"] and "not guarantees" in d["text"]
    assert build_digest(db) is None                # already sent


def test_digest_respects_max_demo_and_toggle(f, db):
    set_setting(db, "filters", {"min_player_matches": 0})
    set_setting(db, "alerts", {"price_targets_max": 2})
    for i in range(4):
        _confident_match(f, db, 20 + i)
    _confident_match(f, db, 30, demo=True)
    d = build_digest(db)
    assert len(d["match_ids"]) == 2
    set_setting(db, "alerts", {"price_targets": False})
    assert build_digest(db) is None


def test_job_raises_one_alert_and_sends_telegram(f, db, monkeypatch):
    set_setting(db, "filters", {"min_player_matches": 0})
    _confident_match(f, db, 40)
    sent = []
    monkeypatch.setattr("ttq.services.alerts._send_telegram", lambda t, b: sent.append((t, b)) or True)
    monkeypatch.setattr("ttq.services.alerts._send_email", lambda t, b: False)
    r = price_targets_job(db)
    assert r["sent"] == 1 and "telegram" in r["channels"]
    assert len(sent) == 1 and "only at" in sent[0][1]
    assert db.query(Alert).filter_by(kind="price_targets").count() == 1


def test_test_alert_reports_status(monkeypatch):
    from ttq.services import alerts
    monkeypatch.setattr(alerts, "_send_email", lambda t, b: False)
    monkeypatch.setattr(alerts, "_send_telegram", lambda t, b: True)
    assert alerts.send_test_alert() == {"telegram": "sent", "email": "not configured"}

    def bad(t, b):
        req = httpx.Request("POST", "https://api.telegram.org/botX/sendMessage")
        raise httpx.HTTPStatusError("x", request=req, response=httpx.Response(401, text='{"description":"Unauthorized"}', request=req))
    monkeypatch.setattr(alerts, "_send_telegram", bad)
    res = alerts.send_test_alert()
    assert res["telegram"].startswith("failed: HTTP 401") and "botX" not in res["telegram"]   # never echoes the token


def test_bet_recommendation_message_format(f, db):
    from ttq.models import ModelVersion, Recommendation
    from ttq.services.messages import recommendation_text
    a, b = f.player("Mateusz Baran"), f.player("Miroslaw Lewczuk")
    from datetime import datetime, timezone
    m = f.match(a, b, at=datetime(2026, 11, 24, 0, 10, tzinfo=timezone.utc))      # 19:10 ET on Nov 23
    mv = ModelVersion(name="dyn_elo", kind="RatingOnly", version="20261123162333", status="CHAMPION",
                      trained_at=datetime(2026, 11, 23, 16, 23, tzinfo=timezone.utc))
    db.add(mv); db.flush()
    pr = f.prediction(m, p1=0.588); pr.model_version_id = mv.id
    r = Recommendation(match_id=m.id, prediction_id=pr.id, market="match_winner", selection="p1", bookmaker_key="hardrock",
                       decimal_odds=2.0, model_prob=0.588, prob_low=0.55, prob_high=0.62, ev=0.176, status="QUALIFIES",
                       data_quality="HIGH")
    db.add(r); db.flush()
    title, body = recommendation_text(db, r)
    assert title == "New Bet Recommendation"
    lines = body.splitlines()
    assert lines[0] == "Mateusz Baran vs Miroslaw Lewczuk"
    assert lines[1] == "Pick: Mateusz Baran (HOME)"
    assert lines[2] == "Odds: 2.00 (+100) | Prob: 58.8% | EV: 17.6%"
    assert lines[3] == "Units: 1.0"
    assert lines[4] == "Match: Nov 23, 7:10 PM ET"
    assert lines[5] == "Model: dyn_elo_20261123162333 (2026-11-23)"
    assert lines[6].startswith("Ruleset: EV>=3%")


def test_every_qualifying_bet_reaches_telegram(f, db, monkeypatch):
    from ttq.services.alerts import raise_alert
    sent = []
    monkeypatch.setattr("ttq.services.alerts._send_telegram", lambda t, b: sent.append(t) or True)
    monkeypatch.setattr("ttq.services.alerts._send_email", lambda t, b: False)
    raise_alert(db, "opportunity", "New Bet Recommendation", "a", "opp:1", rate_limited=False)
    raise_alert(db, "opportunity", "New Bet Recommendation", "b", "opp:2", rate_limited=False)   # seconds later
    raise_alert(db, "opportunity", "New Bet Recommendation", "a", "opp:1", rate_limited=False)   # duplicate
    assert len(sent) == 2
    raise_alert(db, "provider_stale", "x", "y", "stale:1")
    raise_alert(db, "provider_stale", "x", "y", "stale:2")                                       # rate-limited kind
    assert len(sent) == 3
