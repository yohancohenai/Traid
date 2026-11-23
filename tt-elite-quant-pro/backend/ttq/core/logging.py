import json, logging, sys
from ttq.core.timeutil import utcnow


class JsonFormatter(logging.Formatter):
    def format(self, record):
        d = {"ts": utcnow().isoformat(), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
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
