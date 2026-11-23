"""Runtime-editable settings persisted in app_settings."""
from __future__ import annotations

import copy
from sqlalchemy.orm import Session

from ttq.core.timeutil import utcnow
from ttq.models import AppSetting

DEFAULTS: dict[str, dict] = {
    # Research filters. Defaults chosen conservatively; `select_filters` in backtest picks them on the TUNE/CALIB
    # period, never the untouched test period.
    "filters": {
        "min_ev": 0.03,              # estimated EV per unit
        "max_ev": 0.25,              # larger edges are far more likely a bad price / data error -> WATCH
        "min_ev_low": 0.0,           # EV at the lower end of the probability interval
        "min_edge": 0.02,            # model prob - no-vig market prob
        "min_data_quality": "MEDIUM",
        "max_quote_age_seconds": 600,
        "min_player_matches": 15,
        "max_model_disagreement": 0.08,
        "min_decimal_odds": 1.25,
        "max_decimal_odds": 4.0,
        "uncertainty_scale": 0.5,
        "watch_min_ev": 0.0,
        "selected_by": "default",
    },
    "risk": {
        "bankroll_start": 0.0,
        "max_stake": 50.0,
        "max_event_exposure": 75.0,
        "max_daily_exposure": 200.0,
        "daily_loss_limit": 150.0,
        "kelly_fraction": 0.25,
        "fixed_stake": 10.0,
        "fixed_pct": 0.01,
    },
    "alerts": {
        "email": True, "telegram": True, "browser": True,  # external channels send only when configured in .env
        "min_interval_seconds": 120, "price_change_threshold": 0.05, "divergence_threshold": 0.12,
        "stale_provider_minutes": 30,
        "price_targets": True, "price_targets_max": 8, "price_targets_window_minutes": 75,
    },
    "display": {"timezone": "America/New_York", "data_mode": "ALL"},
    "monitoring": {"drift_window": 300, "drift_logloss_tolerance": 0.02, "retrain_min_new_matches": 500,
                   "promotion_min_logloss_gain": 0.002},
}

QUALITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def filters_key(is_demo: bool) -> str:
    """Research filters are kept per data mode so tuning on DEMO data never changes LIVE thresholds."""
    return "filters_demo" if is_demo else "filters"


def get_filters(db: Session, is_demo: bool) -> dict:
    return get_setting(db, filters_key(is_demo))


def _defaults(key):
    return DEFAULTS.get("filters" if key == "filters_demo" else key, {})


def get_setting(db: Session, key: str) -> dict:
    row = db.get(AppSetting, key)
    out = copy.deepcopy(_defaults(key))
    if row:
        out.update(row.value)
    return out


def set_setting(db: Session, key: str, value: dict) -> dict:
    cur = get_setting(db, key)
    unknown = set(value) - set(_defaults(key))
    if _defaults(key) and unknown:
        raise ValueError(f"unknown setting fields: {sorted(unknown)}")
    cur.update(value)
    row = db.get(AppSetting, key)
    if row:
        row.value = cur
        row.updated_at = utcnow()
    else:
        db.add(AppSetting(key=key, value=cur))
    db.flush()
    return cur
