"""Tick 异动告警检测模块。

维护每个品种的环形价格缓冲区（最近 5 个 tick），计算 3-tick 变化率。
当变化率超过品种特定阈值时生成告警事件，并按严重程度分级（LOW/MEDIUM/HIGH）。
"""

import time
from datetime import datetime

from backend.config import CST, log
from backend.state import state


def check_tick_jump(market: str, price: float, source: str = "unknown") -> dict | None:
    """检查单个 tick 价格是否发生异动，若超过阈值则生成告警事件。

    逻辑流程：
    1. 将当前价格写入对应品种的环形缓冲区（最多保留 5 个 tick）
    2. 计算第 1 个 tick 与第 3 个 tick 之间的变化率
    3. 若变化率绝对值超过阈值，则按 ratio = |change| / threshold 判定严重程度
    4. 将告警写入 state.alert_history 并更新 stats

    Args:
        market: 品种标识，如 "hu"/"comex"/"hujin"/"comex_gold"/"btc"
        price: 当前 tick 价格
        source: 数据来源标识，默认 "unknown"

    Returns:
        告警事件字典（含 severity/changePercent/direction 等字段），未触发时返回 None
    """
    # 品种 → (环形缓冲区属性名, 显示名称, 单位)
    ring_map = {
        "hu": ("silver_tick_ring", "沪银", "元/kg"),
        "comex": ("comex_silver_tick_ring", "COMEX银", "元/kg"),
        "hujin": ("gold_tick_ring", "沪金", "元/克"),
        "comex_gold": ("comex_gold_tick_ring", "COMEX金", "$/oz"),
        "btc": ("btc_tick_ring", "BTC", "$/BTC"),
    }
    ring_attr, market_name, unit = ring_map.get(market, ("silver_tick_ring", market, ""))
    tick_ring = list(getattr(state, ring_attr))

    # 获取该品种的独立阈值，优先 per-market，回退全局
    threshold = state.tick_jump_thresholds.get(market, state.tick_jump_threshold)

    now_ms = int(time.time() * 1000)
    now_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    tick_ring.append({"price": price, "ts": now_ms, "time": now_str, "source": source})
    while len(tick_ring) > 5:
        tick_ring.pop(0)

    setattr(state, ring_attr, tick_ring)

    if len(tick_ring) < 3:
        return None

    first = tick_ring[-3]
    last = tick_ring[-1]
    if first["price"] <= 0:
        return None

    # 3-tick 总变化率
    change_pct = (last["price"] - first["price"]) / first["price"] * 100
    # 最近 1-tick 变化率
    one_tick_pct = 0.0
    if len(tick_ring) >= 2:
        prev = tick_ring[-2]["price"]
        if prev > 0:
            one_tick_pct = (last["price"] - prev) / prev * 100

    if abs(change_pct) < threshold:
        return None

    direction = "急涨" if change_pct > 0 else "急跌"
    ratio = abs(change_pct) / threshold if threshold > 0 else 1.0
    # severity: ratio >= 3.0 → HIGH, >= 2.0 → MEDIUM, else LOW
    severity = "HIGH" if ratio >= 3.0 else "MEDIUM" if ratio >= 2.0 else "LOW"
    alert = {
        "id": f"alert_{market}_{now_ms}",
        "market": market,
        "marketName": market_name,
        "type": f"{market_name}_3TICK_JUMP",
        "direction": direction,
        "threshold": threshold,
        "changePercent": round(change_pct, 3),
        "changeAbs": round(last["price"] - first["price"], 3),
        "fromPrice": first["price"],
        "toPrice": last["price"],
        "fromTime": first["time"],
        "toTime": now_str,
        "oneTickPct": round(one_tick_pct, 3),
        "twoTickPct": round(change_pct, 3),
        "tickCount": len(tick_ring),
        "source": source,
        "timestamp": now_ms,
        "datetime": now_str,
        "severity": severity,
        "unit": unit,
    }

    with state.alerts_lock:
        state.alert_history.insert(0, alert)
        if len(state.alert_history) > state.alert_max_history:
            state.alert_history.pop()
        if direction == "急涨":
            state.alert_stats[market]["surge"] += 1
        else:
            state.alert_stats[market]["drop"] += 1
        state.alert_stats[market]["maxJump"] = max(state.alert_stats[market]["maxJump"], abs(change_pct))

    log.info(f"[ALERT] {market_name} 3-Tick {direction}: {change_pct:+.3f}% [{severity}]")
    return alert
