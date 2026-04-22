import queue
import threading
from dataclasses import dataclass, field

from backend.config import DEFAULT_ALERT_MAX_HISTORY, DEFAULT_TICK_JUMP_THRESHOLD, DEFAULT_TICK_JUMP_THRESHOLDS


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
        "btc": {"surge": 0, "drop": 0, "maxJump": 0},
    }


@dataclass
class AppState:
    cache_lock: threading.Lock = field(default_factory=threading.Lock)
    alerts_lock: threading.Lock = field(default_factory=threading.Lock)

    comex_silver_cache: dict = field(default_factory=_cache)
    silver_cache: dict = field(default_factory=_cache)
    comex_gold_cache: dict = field(default_factory=_cache)
    gold_cache: dict = field(default_factory=_cache)
    btc_cache: dict = field(default_factory=_cache)
    combined_cache: dict = field(default_factory=_cache)
    usd_cny_cache: dict = field(default_factory=_rate_cache)

    tick_jump_threshold: float = DEFAULT_TICK_JUMP_THRESHOLD
    tick_jump_thresholds: dict = field(default_factory=lambda: dict(DEFAULT_TICK_JUMP_THRESHOLDS))
    alert_max_history: int = DEFAULT_ALERT_MAX_HISTORY

    huyin_research_samples: list = field(default_factory=list)

    silver_tick_ring: list = field(default_factory=list)
    comex_silver_tick_ring: list = field(default_factory=list)
    gold_tick_ring: list = field(default_factory=list)
    comex_gold_tick_ring: list = field(default_factory=list)
    btc_tick_ring: list = field(default_factory=list)
    alert_history: list = field(default_factory=list)
    alert_stats: dict = field(default_factory=_alert_stats)

    # 通用品种缓存: instrument_id → {"data": {...}, "ts": float}
    instrument_caches: dict = field(default_factory=dict)

    # 品种价格环形缓冲：instrument_id → list[float]（最近 200 个时间窗口 bar，用于计算信号）
    instrument_price_buffers: dict = field(default_factory=dict)

    # 各品种最后一个 bar 的时间戳（ms），用于时间窗口采样（BAR_WINDOW_MS）
    instrument_bar_timestamps: dict = field(default_factory=dict)

    # 预计算的动量信号：instrument_id → {"signal": str, "strength": float, ...} | None
    instrument_signals: dict = field(default_factory=dict)

    # 预计算的反转信号：instrument_id → {"signal": str, "score": float, "rsi": float, ...} | None
    instrument_reversal_signals: dict = field(default_factory=dict)

    # 动量策略 cooldown 状态
    instrument_momentum_cooldown: dict = field(default_factory=dict)  # iid -> int(剩余bar)
    instrument_momentum_last_active: dict = field(default_factory=dict)  # iid -> str(上次非neutral信号)

    # 反转策略 cooldown 状态
    instrument_reversal_cooldown: dict = field(default_factory=dict)
    instrument_reversal_last_active: dict = field(default_factory=dict)

    # SSE 客户端队列集合：set[queue.SimpleQueue]
    sse_queues: set = field(default_factory=set)
    sse_lock: threading.Lock = field(default_factory=threading.Lock)

    # 单调递增版本号，每次数据更新 +1，SSE 用于变更检测
    data_version: int = 0

    # 实时高频回测采样缓冲区: instrument_id -> [{"t": ms, "y": price}, ...]
    # 由 FastDataPoller 每秒写入，最多保留 300 个点（约5分钟）
    realtime_backtest_buffers: dict = field(default_factory=dict)

    # 数据源优先级配置（可通过 Admin API 动态切换）
    source_priority: dict = field(default_factory=lambda: {
        "ag0": ["ifind", "sina"],
        "xag": ["ifind", "infoway", "sina"],
        "au0": ["sina"],
        "xau": ["ifind", "infoway", "sina"],
        "btc": ["infoway_crypto"],
    })


state = AppState()
