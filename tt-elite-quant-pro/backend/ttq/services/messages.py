"""Human-facing alert texts (Telegram / email / browser)."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ttq.core.config import get_settings
from ttq.core.timeutil import as_utc
from ttq.models import Match, ModelVersion, Prediction, Recommendation
from ttq.services.app_settings import get_filters, get_setting

TZ_ABBR = {"America/New_York": "ET", "America/Chicago": "CT", "America/Denver": "MT", "America/Phoenix": "MT",
           "America/Los_Angeles": "PT"}


def recommendation_text(db: Session, r: Recommendation) -> tuple[str, str]:
    """('New Bet Recommendation', body) in the user's preferred layout."""
    m: Match = db.get(Match, r.match_id)
    pred: Prediction | None = db.get(Prediction, r.prediction_id)
    mv: ModelVersion | None = db.get(ModelVersion, pred.model_version_id) if pred and pred.model_version_id else None
    F = get_filters(db, r.is_demo)
    alerts = get_setting(db, "alerts")
    tzname = get_setting(db, "display").get("timezone") or get_settings().user_timezone
    when = as_utc(m.scheduled_at).astimezone(ZoneInfo(tzname))
    side = "HOME" if r.selection == "p1" else "AWAY"
    pick = m.player1.canonical_name if r.selection == "p1" else m.player2.canonical_name
    model = f"{mv.name}_{mv.version}" if mv else "model"
    trained = f" ({mv.trained_at:%Y-%m-%d})" if mv and mv.trained_at else ""
    ruleset_date = (F.get("selected_by") or "default").replace("calib-period grid ", "calib ")
    hour = when.strftime("%I:%M %p").lstrip("0")
    body = "\n".join([
        f"{m.player1.canonical_name} vs {m.player2.canonical_name}",
        f"Pick: {pick} ({side})",
        f"Odds: {r.decimal_odds:.2f} ({'+' if r.decimal_odds >= 2 else ''}{_american(r.decimal_odds)}) | "
        f"Prob: {r.model_prob:.1%} | EV: {r.ev:.1%}",
        f"Units: {float(alerts.get('units_per_bet', 1.0)):.1f}",
        f"Match: {when:%b} {when.day}, {hour} {TZ_ABBR.get(tzname, when.strftime('%Z'))}",
        f"Model: {model}{trained}",
        f"Ruleset: EV>={F['min_ev']:.0%}, edge>={F['min_edge']:.0%}, EV@low>={F['min_ev_low']:.0%} ({ruleset_date})",
        "Hard Rock price verified from your upload; re-check it in the app. Estimated EV is not a guarantee.",
    ])
    return ("[DEMO] " if r.is_demo else "") + "New Bet Recommendation", body


def _american(dec: float) -> int:
    from ttq.odds.math import decimal_to_american
    return decimal_to_american(dec)
