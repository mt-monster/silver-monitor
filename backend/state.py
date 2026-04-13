import threading
from dataclasses import dataclass, field


def _cache():
    return {"data": None, "ts": 0}


def _rate_cache():
    return {"rate": 6.83, "ts": 0}


def _alert_stats():
    return {
        "hu": {"surge": 0, "drop": 0, "maxJump": 0},
        "comex": {"surge": 0, "drop": 0, "maxJump": 0},
        "hujin": {"surge": 0, "drop": 0, "maxJump": 0},
        "comex_gold": {"surge": 0, "drop": 0, "maxJump": 0},
    }


@dataclass
class AppState:
    cache_lock: threading.Lock = field(default_factory=threading.Lock)
    alerts_lock: threading.Lock = field(default_factory=threading.Lock)

    comex_silver_cache: dict = field(default_factory=_cache)
    silver_cache: dict = field(default_factory=_cache)
    comex_gold_cache: dict = field(default_factory=_cache)
    gold_cache: dict = field(default_factory=_cache)
    combined_cache: dict = field(default_factory=_cache)
    usd_cny_cache: dict = field(default_factory=_rate_cache)

    tick_jump_threshold: float = 1.0
    alert_max_history: int = 200

    silver_tick_ring: list = field(default_factory=list)
    comex_silver_tick_ring: list = field(default_factory=list)
    gold_tick_ring: list = field(default_factory=list)
    comex_gold_tick_ring: list = field(default_factory=list)
    alert_history: list = field(default_factory=list)
    alert_stats: dict = field(default_factory=_alert_stats)


state = AppState()
