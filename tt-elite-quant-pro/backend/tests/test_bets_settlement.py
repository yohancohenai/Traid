from datetime import timedelta

import pytest

from ttq.core.timeutil import utcnow
from ttq.models import BankrollTransaction, Bet, BetRevision, PaperTrade
from ttq.services import bets as B
from ttq.services.app_settings import set_setting
from ttq.services.performance import summary
from ttq.services.settlement import grade, settle_open_bets, resolve_review


def mk(f, db, **kw):
    a, b = f.player(), f.player()
    return f.match(a, b, **kw)


def test_stores_actual_accepted_odds_and_stake(f, db):
    m = mk(f, db)
    r = B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=25.0, accepted_american=-110)
    b = db.get(Bet, r["bet"]["id"])
    assert b.status == "PLACED" and float(b.stake) == 25.0 and b.accepted_american == -110
    assert float(b.accepted_decimal) == pytest.approx(1.9091, abs=1e-4)
    assert float(b.potential_payout) == pytest.approx(47.73, abs=0.01)
    assert float(b.potential_profit) == pytest.approx(22.73, abs=0.01)
    assert db.query(BankrollTransaction).filter_by(kind="STAKE").one().amount == pytest.approx(-25)


def test_duplicate_prevention(f, db):
    m = mk(f, db)
    B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10, accepted_american=120, bet_ref="HR-1")
    with pytest.raises(B.BetError) as e:
        B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10, accepted_american=120, bet_ref="HR-1")
    assert e.value.code == 409
    with pytest.raises(B.BetError):  # same selection within 10 min without explicit allow_duplicate
        B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10, accepted_american=120)
    B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10, accepted_american=120, allow_duplicate=True)
    assert db.query(Bet).count() == 2


def test_draftkings_bet_rejected(f, db):
    m = mk(f, db)
    with pytest.raises(B.BetError):
        B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10, accepted_american=120, bookmaker_key="draftkings")


def test_risk_limits_require_override(f, db):
    set_setting(db, "risk", {"max_stake": 20})
    m = mk(f, db)
    with pytest.raises(B.BetError) as e:
        B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=30, accepted_american=120)
    assert e.value.detail["needs_override"]
    B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=30, accepted_american=120, override_risk=True)


@pytest.mark.parametrize("sets,sel,expected,net", [((3, 1), "p1", "WON", 15.0), ((1, 3), "p1", "LOST", -10.0)])
def test_win_loss_settlement_and_bankroll(f, db, sets, sel, expected, net):
    m = mk(f, db)
    B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection=sel, stake=10, accepted_american=150)
    m.status, m.sets_p1, m.sets_p2, m.result_verified = "FINISHED", *sets, True
    m.winner_id = m.player1_id if sets[0] > sets[1] else m.player2_id
    settle_open_bets(db)
    b = db.query(Bet).one()
    assert b.status == expected and float(b.net_profit) == net
    s = summary(db, False)
    assert s["net_pl"] == net and s["bankroll"] == pytest.approx(net)


def test_unverified_result_goes_to_review_then_manual(f, db):
    m = mk(f, db)
    B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10, accepted_american=150)
    m.status, m.sets_p1, m.sets_p2, m.result_verified = "FINISHED", 3, 0, False
    settle_open_bets(db)
    b = db.query(Bet).one()
    assert b.status == "SETTLEMENT_REVIEW" and b.net_profit is None
    resolve_review(db, b.id, "WON", "t")
    assert b.status == "WON" and float(b.net_profit) == 15.0


def test_void_and_push_rules(f, db):
    m = mk(f, db)
    m.status = "CANCELLED"
    assert grade(m, "match_winner", "p1", None)[0] == "VOID"
    m.status = "RETIRED"
    r = grade(m, "match_winner", "p1", None)
    assert r[0] == "VOID" and r[1] == "LOW"      # retirements require review
    m.status, m.sets_p1, m.sets_p2, m.result_verified = "FINISHED", 3, 2, True
    assert grade(m, "set_handicap", "p1", -1.0)[0] == "PUSH"
    assert grade(m, "set_handicap", "p1", -1.5)[0] == "LOST"
    assert grade(m, "correct_score", "3-2", None)[0] == "WON"
    assert grade(m, "total_points", "over", 70.5)[0] is None   # no point data -> cannot grade


def test_void_returns_stake(f, db):
    m = mk(f, db)
    B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10, accepted_american=150)
    b = db.query(Bet).one()
    m.status = "CANCELLED"
    settle_open_bets(db)
    assert b.status == "SETTLEMENT_REVIEW"
    resolve_review(db, b.id, "VOID", "t")
    assert float(b.net_profit) == 0 and summary(db, False)["bankroll"] == pytest.approx(0)


def test_corrections_preserve_audit_history(f, db):
    m = mk(f, db)
    r = B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10, accepted_american=150)
    B.correct_bet(db, r["bet"]["id"], {"stake": 12, "accepted_american": 140}, "typo in stake", "t")
    rev = db.query(BetRevision).one()
    assert rev.before["stake"] == 10 and rev.after["stake"] == 12 and rev.reason == "typo in stake"
    assert summary(db, False)["bankroll"] == pytest.approx(-12)
    with pytest.raises(B.BetError):
        B.correct_bet(db, r["bet"]["id"], {"stake": 5}, "", "t")


def test_bet_api_roundtrip(f, db, client):
    m = mk(f, db)
    db.commit()
    r = client.post("/api/bets", json={"match_id": m.id, "selection": "p2", "stake": 20, "accepted_american": -125, "client_request_id": "abc"})
    assert r.status_code == 201, r.text
    assert client.post("/api/bets", json={"match_id": m.id, "selection": "p2", "stake": 20, "accepted_american": -125, "client_request_id": "abc"}).status_code == 409
    assert client.post("/api/bets", json={"match_id": m.id, "selection": "p2", "stake": -5, "accepted_american": -125}).status_code == 422
    bets = client.get("/api/bets").json()
    assert len(bets) == 1 and bets[0]["stake"] == 20 and bets[0]["american"] == -125
    assert "id,placed_at" in client.get("/api/bankroll/export.csv").text


def test_paper_trades_separate_from_real_bets(f, db):
    db.add(PaperTrade(match_id=mk(f, db).id, decided_at=utcnow(), selection="p1", decimal_odds=2.0, model_prob=0.6, ev=0.2))
    db.flush()
    assert summary(db, False)["total_bets"] == 0
