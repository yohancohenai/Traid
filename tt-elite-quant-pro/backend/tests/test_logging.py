import json
import logging

from ttq.core.logging import JsonFormatter, setup_logging

FAKE_TOKEN = "123456789:FAKEfakeFAKEfakeFAKEfake0000"   # not a real token


def test_telegram_token_is_masked_in_logs():
    rec = logging.LogRecord("x", logging.ERROR, __file__, 1,
                            f"POST https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage failed", None, None)
    out = json.loads(JsonFormatter().format(rec))["msg"]
    assert "FAKEfake" not in out and "bot123456789:***" in out


def test_httpx_request_logging_is_quiet():
    saved = logging.getLogger().handlers[:]
    try:
        setup_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        logging.getLogger().handlers[:] = saved
