"""Hard Rock price log: the user replies in Telegram to a pick message with the price they see.

Replies understood (to the pick message itself):
  +110 / -105 / 110 / 1.95     the Hard Rock price you see for the picked player (not bet)
  bet +110 / took -105         you placed the bet at that price
  skip / no / gone             you skipped it or the line wasn't offered
Each bot run reads new replies (Telegram getUpdates), stores them in the picks log, and answers with a confirmation.
The weekly scorecard then grades your bets at your real prices and shows how often Hard Rock beat the minimum.
"""
from __future__ import annotations

import logging
import re

import httpx
from sqlalchemy.orm import Session

from ttq.core.config import get_settings
from ttq.core.timeutil import utcnow
from ttq.models import AppSetting
from ttq.odds.math import decimal_to_american

log = logging.getLogger(__name__)

HELP = ("To log a Hard Rock price, reply to the pick message with:\n"
        "+110  (price you see)\nbet +110  (you placed it)\nskip  (not offered / skipped)\n"
        "or a screenshot of the Hard Rock match (add the caption 'bet' if you placed it).\n"
        "To find misplaced lines: send a screenshot of the Hard Rock table tennis list (not as a reply).")

_SKIP = {"skip", "no", "gone", "pass", "not offered", "none", "n/a"}
_BET = re.compile(r"^(bet|took|placed|in)\b", re.I)
_NUM = re.compile(r"([+\-−]?\d+(?:\.\d+)?)")


def parse_reply(text: str) -> dict | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in _SKIP or t.startswith("skip"):
        return {"action": "skip", "american": None}
    m = _NUM.search(t)
    if not m:
        return None
    raw = m.group(1).replace("−", "-")
    try:
        v = float(raw)
    except ValueError:
        return None
    if "." in raw and 1.01 <= v <= 50:                       # decimal odds like 1.95
        am = decimal_to_american(v)
    elif raw.startswith(("+", "-")) or abs(v) >= 100:
        am = int(v)
        if -100 < am < 100:
            return None
        if am == -100:
            am = 100
    else:
        return None
    return {"action": "bet" if _BET.match(t) else "price", "american": am}


def _row(db: Session, key: str):
    return db.get(AppSetting, key)


def _save(db: Session, key: str, value) -> None:
    row = _row(db, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()


def _tg(method: str, **payload):
    s = get_settings()
    r = httpx.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/{method}", json=payload, timeout=20)
    r.raise_for_status()
    return r.json().get("result")


def apply_reply(db: Session, reply_to_id: int, text: str, now=None) -> str:
    """Record one reply against the pick it answers. Returns the confirmation text."""
    now = now or utcnow()
    row = _row(db, "picks_log")
    picks = dict(row.value) if row else {}
    hit = next(((k, v) for k, v in picks.items() if v.get("tg_msg") == reply_to_id), None)
    if not hit:
        return "That message isn't one of my picks, so I couldn't log it.\n" + HELP
    parsed = parse_reply(text)
    if not parsed:
        return "I couldn't read a price there.\n" + HELP
    key, pk = hit
    pk = dict(pk)
    pk.update({"hr_action": parsed["action"], "hr_price": parsed["american"], "hr_logged_at": now.isoformat()})
    picks[key] = pk
    _save(db, "picks_log", picks)
    name = pk.get("pick_name") or "the pick"
    if parsed["action"] == "skip":
        return f"Logged: skipped {name}."
    am, mn = parsed["american"], pk["min_american"]
    from ttq.odds.math import american_to_decimal
    ok = american_to_decimal(am) >= american_to_decimal(mn) - 1e-9
    verdict = "at or above the minimum ✅" if ok else "below the minimum, so not a bet by the rules ⚠️"
    what = "Bet logged" if parsed["action"] == "bet" else "Price logged"
    return f"{what}: {name} at {am:+d} (minimum {mn:+d}), {verdict}"


def price_from_screenshot(image: bytes, pick_name: str) -> int | None:
    """Read a Hard Rock screenshot and return the moneyline shown next to the picked player, or None."""
    from ttq.ocr.hardrock import name_score, ocr_rows, parse_rows
    rows, _ = ocr_rows(image)
    best = None
    for line in parse_rows(rows):
        if line.american is None:
            continue
        sc = name_score(line.name.replace(",", " "), pick_name)
        if sc >= 0.7 and (best is None or sc > best[0]):
            best = (sc, line.american)
    return best[1] if best else None


def _download_photo(msg: dict) -> bytes:
    s = get_settings()
    file_id = msg["photo"][-1]["file_id"]                  # largest size
    path = _tg("getFile", file_id=file_id)["file_path"]
    r = httpx.get(f"https://api.telegram.org/file/bot{s.telegram_bot_token}/{path}", timeout=30)
    r.raise_for_status()
    return r.content


def _photo_reply(db: Session, msg: dict, reply_to_id: int) -> str:
    row = _row(db, "picks_log")
    pk = next((v for v in (row.value if row else {}).values() if v.get("tg_msg") == reply_to_id), None)
    if not pk:
        return "That message isn't one of my picks, so I couldn't log it.\n" + HELP
    try:
        am = price_from_screenshot(_download_photo(msg), pk.get("pick_name") or "")
    except Exception as e:  # noqa
        log.warning("screenshot read failed: %s", e.__class__.__name__)
        am = None
    if am is None:
        return (f"I couldn't find {pk.get('pick_name') or 'the picked player'}'s price in that screenshot. "
                "Please type it instead, e.g. +110 or bet +110.")
    caption = (msg.get("caption") or "").strip()
    return "From your screenshot: " + apply_reply(db, reply_to_id, ("bet " if _BET.match(caption) else "") + f"{am:+d}")


def _scan_reply(db: Session, msg: dict) -> str:
    from ttq.services.hr_scan import scan_image, send_value_picks, summary_text
    try:
        res = scan_image(db, _download_photo(msg))
    except Exception as e:  # noqa
        log.warning("hard rock scan failed: %s", e.__class__.__name__)
        return "I couldn't read that screenshot. Try a clearer one of the Hard Rock table tennis list."
    send_value_picks(db, res)
    return summary_text(res)


def poll_replies(db: Session) -> dict:
    """Read new Telegram messages, log replies to picks, confirm each one. Safe to call every minute."""
    s = get_settings()
    if not (s.telegram_bot_token and s.telegram_chat_id):
        return {"status": "not configured"}
    off_row = _row(db, "tg_update_offset")
    offset = int(off_row.value.get("offset", 0)) if off_row else 0
    try:
        updates = _tg("getUpdates", offset=offset, timeout=0, allowed_updates=["message"]) or []
    except Exception as e:  # noqa
        log.warning("telegram getUpdates failed: %s", e.__class__.__name__)
        return {"status": "error"}
    logged = 0
    for u in updates:
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(s.telegram_chat_id):
            continue                                        # only the owner's chat counts
        text = msg.get("text") or ""
        rt = (msg.get("reply_to_message") or {}).get("message_id")
        if rt and msg.get("photo"):
            answer = _photo_reply(db, msg, rt)
            logged += "logged" in answer.lower() and "couldn" not in answer.lower()
        elif msg.get("photo"):              # a Hard Rock screenshot on its own: scan it for misplaced lines
            answer = _scan_reply(db, msg)
        elif rt:
            answer = apply_reply(db, rt, text)
            logged += answer.startswith(("Logged", "Bet logged", "Price logged"))
        elif parse_reply(text) or text.strip().lower() in ("help", "/help", "/start"):
            answer = "Please reply directly to the pick message (swipe left on it, or tap and hold → Reply).\n" + HELP
        else:
            continue
        try:
            _tg("sendMessage", chat_id=s.telegram_chat_id, text=answer, reply_to_message_id=msg.get("message_id"))
        except Exception as e:  # noqa
            log.warning("telegram confirm failed: %s", e.__class__.__name__)
    _save(db, "tg_update_offset", {"offset": offset})
    return {"status": "OK", "updates": len(updates), "logged": logged}
