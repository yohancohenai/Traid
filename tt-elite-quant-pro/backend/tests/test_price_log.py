from datetime import timedelta

from ttq.core.timeutil import utcnow
from ttq.services import price_log
from ttq.services.price_log import apply_reply, parse_reply, poll_replies
from ttq.services.summary import grade, log_picks


def test_parse_reply_formats():
    assert parse_reply("+110") == {"action": "price", "american": 110}
    assert parse_reply("-105") == {"action": "price", "american": -105}
    assert parse_reply("−120") == {"action": "price", "american": -120}
    assert parse_reply("bet +110") == {"action": "bet", "american": 110}
    assert parse_reply("took -105") == {"action": "bet", "american": -105}
    assert parse_reply("1.95")["american"] == -105
    assert parse_reply("skip")["action"] == "skip"
    assert parse_reply("hello") is None and parse_reply("50") is None


def _pick(f, db, winner_p1=True, sent_ago=timedelta(days=1)):
    a, b = f.player(), f.player()
    m = f.match(a, b, at=utcnow() - timedelta(hours=20))
    m.status, m.winner_id = "FINISHED", (m.player1_id if winner_p1 else m.player2_id)
    db.flush()
    log_picks(db, [{"match_id": m.id, "side": "p1", "p": 0.6, "min_american": 105, "tg_msg": 500 + m.id,
                    "pick_name": "Kamil Rudomina"}], now=utcnow() - sent_ago)
    return m


def test_reply_logged_and_graded_at_real_price(f, db):
    m = _pick(f, db)
    msg = apply_reply(db, 500 + m.id, "bet +120")
    assert msg.startswith("Bet logged: Kamil Rudomina at +120 (minimum +105), at or above")
    r = grade(db, utcnow() - timedelta(days=7), utcnow())
    assert (r["hr_logged"], r["hr_beat_min"], r["bets_w"], r["bets_l"]) == (1, 1, 1, 0)
    assert r["bets_units"] == 1.2


def test_below_minimum_flagged_and_unknown_message(f, db):
    m = _pick(f, db)
    assert "below the minimum" in apply_reply(db, 500 + m.id, "-130")
    assert "isn't one of my picks" in apply_reply(db, 999999, "+110")


def test_poll_only_owner_chat_and_advances_offset(f, db, monkeypatch):
    m = _pick(f, db)
    s = price_log.get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "x", raising=False)
    monkeypatch.setattr(s, "telegram_chat_id", "42", raising=False)
    sent = []
    def fake_tg(method, **p):
        if method == "getUpdates":
            return [{"update_id": 7, "message": {"message_id": 1, "chat": {"id": 42}, "text": "+115",
                                                 "reply_to_message": {"message_id": 500 + m.id}}},
                    {"update_id": 8, "message": {"message_id": 2, "chat": {"id": 99}, "text": "+999",
                                                 "reply_to_message": {"message_id": 500 + m.id}}}]
        sent.append(p["text"])
    monkeypatch.setattr(price_log, "_tg", fake_tg)
    r = poll_replies(db)
    assert r["logged"] == 1 and len(sent) == 1 and "+115" in sent[0]
    assert db.get(price_log.AppSetting, "tg_update_offset").value["offset"] == 9
