"""Failing tests that pin down correctness bugs found in the real-money ledger review.

Each test asserts the CORRECT behaviour, so it fails against the current code.
"""
import threading
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from ttq.core import db as dbmod
from ttq.core.timeutil import utcnow
from ttq.models import BankrollTransaction, Bet, Recommendation
from ttq.services import bets as B
from ttq.services.app_settings import set_setting
from ttq.services.performance import summary
from ttq.services.scanner import quote_status, scan
from ttq.services.settlement import grade, resolve_review, settle_open_bets
from ttq.api.serialize import rec_out


def mk(f, **kw):
    a, b = f.player(), f.player()
    return f.match(a, b, **kw)


def finish(m, a, b, verified=True):
    m.status, m.sets_p1, m.sets_p2, m.result_verified = "FINISHED", a, b, verified
    m.winner_id = m.player1_id if a > b else m.player2_id


def balance(db, is_demo=False):
    return float(db.scalar(select(func.coalesce(func.sum(BankrollTransaction.amount), 0))
                           .where(BankrollTransaction.is_demo == is_demo)))


# --------------------------------------------------------------------------- settlement crash on line-less markets
def test_grade_set_handicap_without_line_does_not_raise(f, db):
    """settlement.py:33 (and :44 for point_handicap) formats `{line:+}` with line=None -> TypeError (calc uses `line or 0`, message does not).
    BetIn allows market=set_handicap with line=None."""
    m = mk(f)
    finish(m, 3, 1)
    res, conf, _ = grade(m, "set_handicap", "p1", None)
    assert res is None and conf == "LOW"   # no line recorded -> manual review, never a guess


def test_one_bad_bet_does_not_block_settlement_of_all_other_bets(f, db):
    """settle_open_bets has no per-bet guard: a single set_handicap bet with line=None raises TypeError and the
    whole settle job aborts, so every other (perfectly gradable) bet stays unsettled."""
    m = mk(f)
    good = B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10,
                         accepted_american=150)["bet"]["id"]
    with pytest.raises(B.BetError):   # entry now requires a line for handicap/total markets
        B.confirm_bet(db, actor="t", match_id=m.id, market="set_handicap", selection="p1", stake=10,
                      accepted_american=150, line=None)
    bad = B.confirm_bet(db, actor="t", match_id=m.id, market="set_handicap", selection="p1", stake=10,
                        accepted_american=150, line=-1.5)["bet"]["id"]
    db.get(Bet, bad).line = None      # e.g. a legacy row or a correction that cleared the line
    finish(m, 3, 1)
    settle_open_bets(db)  # raises TypeError today
    assert db.get(Bet, good).status == "WON"


def test_total_points_without_line_does_not_raise(f, db):
    """settlement.py:40 `tot - line` with line=None -> TypeError (same crash, total_points market)."""
    a, b = f.player(), f.player()
    m = f.match(a, b, status="FINISHED", sets=(3, 0), points=[(11, 5), (11, 7), (11, 9)])
    db.expire(m)  # reload m.sets from the DB
    res, conf, _ = grade(m, "total_points", "over", None)
    assert res is None or conf == "LOW"  # cannot grade a totals bet without a line; must not crash


# --------------------------------------------------------------------------- concurrent double settlement
def _committed_bet_on_finished_match(f, db, verified=True):
    m = mk(f)
    bid = B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10,
                        accepted_american=150)["bet"]["id"]
    finish(m, 3, 1, verified=verified)
    db.commit()
    return bid


def _race(fn_a, fn_b):
    """Run fn_a in session A and flush (holds the bet row lock), start fn_b in session B in a thread (it reads the
    pre-settlement state and blocks on the row lock), then commit A and let B finish and commit."""
    s1, s2 = dbmod.SessionLocal(), dbmod.SessionLocal()
    err = []
    try:
        fn_a(s1)
        s1.flush()

        def other():
            try:
                fn_b(s2)
                s2.commit()
            except Exception as e:  # noqa
                err.append(e)
                s2.rollback()

        t = threading.Thread(target=other)
        t.start()
        t.join(1.0)   # let B read and block on the lock
        s1.commit()
        t.join(15)
        assert not t.is_alive()
    finally:
        s1.close(); s2.close()
    return err


def test_concurrent_settle_jobs_do_not_double_credit(f, db):
    """jobs.py claims jobs are 'safe to run concurrently with the API', and POST /api/jobs/settle can run while the
    worker's settle job runs. settle_open_bets reads PLACED bets without row locks / status re-check, so two runs
    both credit the RETURN."""
    bid = _committed_bet_on_finished_match(f, db)
    _race(lambda s: settle_open_bets(s), lambda s: settle_open_bets(s))
    db.expire_all()
    returns = db.scalar(select(func.count()).select_from(BankrollTransaction)
                        .where(BankrollTransaction.bet_id == bid, BankrollTransaction.kind == "RETURN"))
    assert returns == 1
    assert balance(db) == pytest.approx(15.0)   # -10 stake + 25 return


def test_double_submitted_manual_settlement_does_not_double_credit(f, db):
    """resolve_review checks status == SETTLEMENT_REVIEW on a plain (unlocked) read; a double-click on
    'settle WON' credits the return twice."""
    bid = _committed_bet_on_finished_match(f, db, verified=False)
    settle_open_bets(db); db.commit()
    assert db.get(Bet, bid).status == "SETTLEMENT_REVIEW"
    err = _race(lambda s: resolve_review(s, bid, "WON", "t"), lambda s: resolve_review(s, bid, "WON", "t"))
    db.expire_all()
    assert balance(db) == pytest.approx(15.0), f"second request error: {err}"


# --------------------------------------------------------------------------- duplicate-bet protection gaps
def test_bet_ref_added_by_correction_still_blocks_duplicate_slip(f, db):
    """correct_bet lets the user set bet_ref but never updates dedupe_key (still the 'h:' hash), so re-entering the
    same Hard Rock slip later with that bet_ref is accepted as a new bet: stake debited twice."""
    m = mk(f)
    bid = B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10,
                        accepted_american=150)["bet"]["id"]
    B.correct_bet(db, bid, {"bet_ref": "HR-777"}, "add slip ref", "t")
    with pytest.raises(B.BetError) as e:
        # allow_duplicate only means 'this is a separate bet on the same selection'; the slip ref must still dedupe
        B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10,
                      accepted_american=150, bet_ref="HR-777", allow_duplicate=True)
    assert e.value.code == 409


def test_bet_cannot_be_linked_to_recommendation_of_other_match(f, db):
    """confirm_bet never checks that recommendation_id belongs to the same match/selection/market. The unrelated
    recommendation is flipped to user_action=PLACED (and drops out of ledger B) while the bet links to it."""
    m1, m2 = mk(f), mk(f)
    pr = f.prediction(m1)
    rec = Recommendation(match_id=m1.id, prediction_id=pr.id, market="match_winner", selection="p2",
                         bookmaker_key="hardrock", decimal_odds=2.0, model_prob=0.6, prob_low=0.55, prob_high=0.65,
                         status="QUALIFIES", data_quality="HIGH")
    db.add(rec); db.flush()
    with pytest.raises(B.BetError):
        B.confirm_bet(db, actor="t", match_id=m2.id, market="match_winner", selection="p1", stake=10,
                      accepted_american=150, recommendation_id=rec.id)


# --------------------------------------------------------------------------- stale quote shown as QUALIFIES
def test_rec_out_respects_configured_quote_age_filter(f, db):
    """scan uses min(filters.max_quote_age_seconds, settings) but rec_out's read-time freshness check
    (serialize.py:74 -> quote_out, serialize.py:37 default max_age=settings 600s) ignores the stricter user filter, so a quote that
    is stale under the user's 60s filter is still served as status=QUALIFIES."""
    set_setting(db, "filters", {"min_player_matches": 0, "max_quote_age_seconds": 60})
    a, b = f.player(), f.player()
    m = f.match(a, b)
    f.prediction(m, p1=0.62, lo=0.59, hi=0.65)
    f.quote(m, "p1", -105, age_s=10)
    f.quote(m, "p2", -115, age_s=10)
    now = utcnow()
    scan(db, now=now)
    rec = db.scalar(select(Recommendation).where(Recommendation.selection == "p1", Recommendation.is_current.is_(True)))
    assert rec.status == "QUALIFIES"
    # 5 minutes later, nothing re-scanned: the quote is 5+ minutes old, well past the 60s filter
    from ttq.models import OddsQuote
    q = db.get(OddsQuote, rec.quote_id)
    q.captured_at = q.quoted_at = now - timedelta(seconds=310)
    db.flush()
    out = rec_out(db, rec)
    assert out["status"] != "QUALIFIES"


def test_quote_with_old_provider_timestamp_is_not_verified(f, db):
    """quote_status/observed_at only look at captured_at/last_confirmed_at (our fetch time) and ignore quoted_at
    (the provider's own timestamp). A feed serving a cached price last quoted 2h ago is VERIFIED, and ingest_odds
    keeps refreshing last_confirmed_at on it, so it can reach QUALIFIES."""
    m = mk(f)
    q = f.quote(m, "p1", -105, age_s=5)
    q.quoted_at = utcnow() - timedelta(hours=2)
    assert quote_status(q, m, 600) == "STALE"


# --------------------------------------------------------------------------- performance summary consistency
def test_summary_returned_and_wagered_are_on_same_basis(f, db):
    """performance.summary: total_wagered excludes VOID stakes but total_returned includes the VOID refund, so a
    single voided $10 bet shows '$10 returned on $0 wagered' (returned - wagered != net_pl)."""
    m = mk(f)
    B.confirm_bet(db, actor="t", match_id=m.id, market="match_winner", selection="p1", stake=10, accepted_american=150)
    m.status = "CANCELLED"
    settle_open_bets(db)
    b = db.query(Bet).one()
    resolve_review(db, b.id, "VOID", "t")
    s = summary(db, False)
    assert s["net_pl"] == 0 and s["bankroll"] == 0
    assert s["total_returned"] - s["total_wagered"] == pytest.approx(s["net_pl"])
