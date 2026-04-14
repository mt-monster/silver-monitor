"""沪银研究用价格样本追加（与跳价告警环独立）。"""

from backend.config import RUNTIME_CONFIG
from backend.state import state


def append_huyin_research_sample(ts_ms: int, price: float) -> None:
    """
    在快轮询成功写入沪银价后调用。可选 min_sample_interval_ms：与上一条同价且间隔过短则跳过，减轻异常重复点。
    """
    if price <= 0 or ts_ms <= 0:
        return
    cfg = RUNTIME_CONFIG.get("research") or {}
    max_n = max(10, int(cfg.get("huyin_sample_max", 2000)))
    min_gap = max(0, int(cfg.get("min_sample_interval_ms", 0)))

    with state.cache_lock:
        samples = state.huyin_research_samples
        if samples and min_gap > 0:
            last = samples[-1]
            if last["price"] == price and (ts_ms - last["ts"]) < min_gap:
                return
        samples.append({"ts": int(ts_ms), "price": float(price)})
        overflow = len(samples) - max_n
        if overflow > 0:
            del samples[0:overflow]
