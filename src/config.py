import copy
import os
from datetime import time

import yaml

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.yaml")

DEFAULTS = {
    "update": {"schedule_time": "02:00", "retry_delays_minutes": [15, 30, 60]},
    "maintenance_window": {"start": "01:00", "end": "04:00"},
    "health_check": {"rollback_window_minutes": 5},
    "quality_gate": {"min_accuracy": 0.80, "min_grounding": 0.90},
}


def parse_hhmm(value):
    try:
        hours, minutes = str(value).split(":")
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        raise ValueError(f"Invalid time '{value}', expected HH:MM")


def _merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def validate(cfg):
    delays = cfg["update"]["retry_delays_minutes"]
    if not isinstance(delays, list) or not delays or not all(isinstance(d, int) and d > 0 for d in delays):
        raise ValueError("retry_delays_minutes must be a non-empty list of positive whole numbers")
    parse_hhmm(cfg["update"]["schedule_time"])
    parse_hhmm(cfg["maintenance_window"]["start"])
    parse_hhmm(cfg["maintenance_window"]["end"])
    window = cfg["health_check"]["rollback_window_minutes"]
    if not isinstance(window, (int, float)) or window <= 0:
        raise ValueError("rollback_window_minutes must be a positive number")
    for name in ("min_accuracy", "min_grounding"):
        value = cfg["quality_gate"][name]
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1")


def load_config(path=CONFIG_PATH):
    """Defaults first, then the values in config.yaml on top. Bad values raise ValueError."""
    cfg = copy.deepcopy(DEFAULTS)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            _merge(cfg, yaml.safe_load(f) or {})
    validate(cfg)
    return cfg