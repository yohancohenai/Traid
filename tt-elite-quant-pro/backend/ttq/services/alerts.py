"""Alerts with de-duplication and per-channel rate limiting. Alerts never contain wagering instructions to a
sportsbook and never present stale prices as executable."""
from __future__ import annotations

import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ttq.core.config import get_settings
from ttq.core.timeutil import utcnow
from ttq.models import Alert
from ttq.services.app_settings import get_setting

log = logging.getLogger(__name__)


def _send_email(title, body):
    s = get_settings()
    if not (s.smtp_host and s.alert_email_to and s.alert_email_from):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = f"[TTQ] {title}", s.alert_email_from, s.alert_email_to
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as sm:
        sm.starttls()
        if s.smtp_user:
            sm.login(s.smtp_user, s.smtp_password or "")
        sm.send_message(msg)
    return True


def _send_telegram(title, body):
    s = get_settings()
    if not (s.telegram_bot_token and s.telegram_chat_id):
        return False
    httpx.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
               json={"chat_id": s.telegram_chat_id, "text": f"{title}\n{body}"}, timeout=15).raise_for_status()
    return True


def send_test_alert() -> dict:
    """Send a test message on every configured external channel, ignoring rate limits. Returns per-channel status."""
    out = {}
    title, body = "TT Elite Quant Pro: test alert ✅", "If you can read this, alerts reach you. No action needed."
    for ch, fn in (("telegram", _send_telegram), ("email", _send_email)):
        try:
            out[ch] = "sent" if fn(title, body) else "not configured"
        except httpx.HTTPStatusError as e:
            out[ch] = f"failed: HTTP {e.response.status_code} {e.response.text[:200]}"
        except Exception as e:  # noqa
            out[ch] = f"failed: {e.__class__.__name__}: {e}"
    return out


def raise_alert(db: Session, kind: str, title: str, body: str, dedupe_key: str, severity: str = "INFO",
                is_demo: bool = False, rate_limited: bool = True) -> Alert | None:
    if db.scalar(select(Alert).where(Alert.dedupe_key == dedupe_key)):
        return None
    cfg = get_setting(db, "alerts")
    recent = db.scalar(select(Alert).where(Alert.kind == kind, Alert.created_at >= utcnow() - timedelta(seconds=cfg["min_interval_seconds"]))
                       .order_by(Alert.created_at.desc()).limit(1))
    channels = ["browser"] if cfg["browser"] else []
    if (not recent or not rate_limited) and not is_demo:  # external channels are rate limited and never fire for DEMO data
        try:
            if cfg["email"] and _send_email(title, body):
                channels.append("email")
        except Exception:  # noqa
            log.exception("email alert failed")
        try:
            if cfg["telegram"] and _send_telegram(title, body):
                channels.append("telegram")
        except Exception:  # noqa
            log.exception("telegram alert failed")
    a = Alert(kind=kind, title=("[DEMO] " if is_demo and not title.startswith("[DEMO]") else "") + title, body=body, dedupe_key=dedupe_key,
              severity=severity, channels_sent=channels, is_demo=is_demo)
    try:
        with db.begin_nested():
            db.add(a)
    except IntegrityError:
        return None
    return a
