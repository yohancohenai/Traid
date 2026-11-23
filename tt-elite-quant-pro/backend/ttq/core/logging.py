import json, logging, re, sys
from ttq.core.timeutil import utcnow

# Telegram bot tokens appear inside request URLs (".../bot123456:ABC.../sendMessage"); never let them reach logs.
_TOKEN_RE = re.compile(r"(bot\d{5,}):[A-Za-z0-9_-]{20,}")


def redact(text: str) -> str:
    return _TOKEN_RE.sub(r"\1:***", text)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        d = {"ts": utcnow().isoformat(), "level": record.levelname, "logger": record.name, "msg": redact(record.getMessage())}
        if record.exc_info:
            d["exc"] = redact(self.formatException(record.exc_info))
        for k in ("event", "provider", "match_id", "bet_id"):
            if hasattr(record, k):
                d[k] = getattr(record, k)
        return json.dumps(d)


def setup_logging(level=logging.INFO):
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    # httpx/httpcore log every request URL at INFO; that floods logs and would include the Telegram token.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
