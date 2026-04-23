import json
import logging
from datetime import timedelta, timezone
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "monitor.config.json"

DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 8765},
    "polling": {"fast_seconds": 1, "slow_seconds": 60},
    "alerts": {
        "tick_jump_threshold": 0.15,
        "tick_jump_thresholds": {
            "hu": 0.15, "comex": 0.10, "hujin": 0.12,
            "comex_gold": 0.10, "btc": 0.30,
        },
        "max_history": 200,
    },
    "frontend": {"default_api_host": "127.0.0.1", "fallback_port": 8765, "poll_ms": 1000, "alert_poll_ms": 2000, "bar_window_ms": 30000},
    "storage": {
        "tick_retention_days": 7,
    },
    "momentum": {
        "short_p": 5,
        "long_p": 20,
        "spread_entry": 0.10,
        "spread_strong": 0.35,
        "slope_entry": 0.02,
    },
    "research": {
        "huyin_sample_max": 2000,
        "min_sample_interval_ms": 0,
        "monte_carlo_min_returns": 15,
        "monte_carlo_max_paths": 50000,
        "monte_carlo_default_paths": 3000,
        "monte_carlo_histogram_bins": 20,
        "path_preview_count": 40,
        "path_steps": 28,
    },
}


def load_runtime_config():
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        user_config = json.load(file)

    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for section, values in user_config.items():
        if isinstance(values, dict) and section in merged:
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


RUNTIME_CONFIG = load_runtime_config()


def reload_runtime_config() -> dict:
    """Hot-reload config from disk (called by /api/config/reload)."""
    global RUNTIME_CONFIG
    RUNTIME_CONFIG = load_runtime_config()
    return RUNTIME_CONFIG


if "momentum" not in RUNTIME_CONFIG or not isinstance(RUNTIME_CONFIG.get("momentum"), dict):
    RUNTIME_CONFIG["momentum"] = dict(DEFAULT_CONFIG["momentum"])
if "research" not in RUNTIME_CONFIG or not isinstance(RUNTIME_CONFIG.get("research"), dict):
    RUNTIME_CONFIG["research"] = dict(DEFAULT_CONFIG["research"])
SERVER_HOST = RUNTIME_CONFIG["server"]["host"]
PORT = int(RUNTIME_CONFIG["server"]["port"])
FAST_POLL = int(RUNTIME_CONFIG["polling"]["fast_seconds"])
SLOW_POLL = int(RUNTIME_CONFIG["polling"]["slow_seconds"])
DEFAULT_TICK_JUMP_THRESHOLD = float(RUNTIME_CONFIG["alerts"]["tick_jump_threshold"])
DEFAULT_TICK_JUMP_THRESHOLDS: dict = RUNTIME_CONFIG["alerts"].get("tick_jump_thresholds", {})
DEFAULT_ALERT_MAX_HISTORY = int(RUNTIME_CONFIG["alerts"]["max_history"])
TICK_RETENTION_DAYS = int(RUNTIME_CONFIG.get("storage", {}).get("tick_retention_days", 7))
FRONTEND_DEFAULT_API_HOST = RUNTIME_CONFIG["frontend"]["default_api_host"]
FRONTEND_FALLBACK_PORT = int(RUNTIME_CONFIG["frontend"]["fallback_port"])
FRONTEND_POLL_MS = int(RUNTIME_CONFIG["frontend"]["poll_ms"])
FRONTEND_ALERT_POLL_MS = int(RUNTIME_CONFIG["frontend"]["alert_poll_ms"])

OZ_TO_KG = 32.1507
OZ_TO_G = 31.1035

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# File handler — always works, even without a console
_fh = logging.FileHandler(LOG_DIR / "server.log", encoding="utf-8")
_fh.setFormatter(_fmt)
_fh.setLevel(logging.INFO)

# Console handler — may fail if no tty, so wrapped in try
_ch: logging.Handler | None = None
try:
    _ch = logging.StreamHandler()
    _ch.setFormatter(_fmt)
    _ch.setLevel(logging.INFO)
except Exception:
    pass

logging.basicConfig(level=logging.INFO, handlers=[h for h in (_fh, _ch) if h])
log = logging.getLogger("silver_monitor")

CST = timezone(timedelta(hours=8))
