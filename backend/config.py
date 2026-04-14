import json
import logging
from datetime import timedelta, timezone
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "monitor.config.json"

DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 8765},
    "polling": {"fast_seconds": 3, "slow_seconds": 60},
    "alerts": {"tick_jump_threshold": 1.0, "max_history": 200},
    "frontend": {"default_api_host": "127.0.0.1", "fallback_port": 8765, "poll_ms": 1000, "alert_poll_ms": 2000},
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
if "momentum" not in RUNTIME_CONFIG or not isinstance(RUNTIME_CONFIG.get("momentum"), dict):
    RUNTIME_CONFIG["momentum"] = dict(DEFAULT_CONFIG["momentum"])
if "research" not in RUNTIME_CONFIG or not isinstance(RUNTIME_CONFIG.get("research"), dict):
    RUNTIME_CONFIG["research"] = dict(DEFAULT_CONFIG["research"])
SERVER_HOST = RUNTIME_CONFIG["server"]["host"]
PORT = int(RUNTIME_CONFIG["server"]["port"])
FAST_POLL = int(RUNTIME_CONFIG["polling"]["fast_seconds"])
SLOW_POLL = int(RUNTIME_CONFIG["polling"]["slow_seconds"])
DEFAULT_TICK_JUMP_THRESHOLD = float(RUNTIME_CONFIG["alerts"]["tick_jump_threshold"])
DEFAULT_ALERT_MAX_HISTORY = int(RUNTIME_CONFIG["alerts"]["max_history"])
FRONTEND_DEFAULT_API_HOST = RUNTIME_CONFIG["frontend"]["default_api_host"]
FRONTEND_FALLBACK_PORT = int(RUNTIME_CONFIG["frontend"]["fallback_port"])
FRONTEND_POLL_MS = int(RUNTIME_CONFIG["frontend"]["poll_ms"])
FRONTEND_ALERT_POLL_MS = int(RUNTIME_CONFIG["frontend"]["alert_poll_ms"])

OZ_TO_KG = 32.1507
OZ_TO_G = 31.1035

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("silver_monitor")

CST = timezone(timedelta(hours=8))

HAS_AKSHARE = False
ak = None
try:
    import akshare as ak  # type: ignore

    HAS_AKSHARE = True
    log.info("akshare loaded OK")
except ImportError:
    log.warning("akshare not installed! Run: pip install akshare")
