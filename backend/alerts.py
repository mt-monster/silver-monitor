import time
from datetime import datetime

from backend.config import CST, log
from backend.state import state


def check_tick_jump(market, price, source="unknown"):
    ring_map = {
        "hu": ("silver_tick_ring", "沪银", "元/kg"),
        "comex": ("comex_silver_tick_ring", "COMEX银", "元/kg"),
        "hujin": ("gold_tick_ring", "沪金", "元/克"),
        "comex_gold": ("comex_gold_tick_ring", "COMEX金", "$/oz"),
        "btc": ("btc_tick_ring", "BTC", "$/BTC"),
    }
    ring_attr, market_name, unit = ring_map.get(market, ("silver_tick_ring", market, ""))
    tick_ring = list(getattr(state, ring_attr))

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

    change_pct = (last["price"] - first["price"]) / first["price"] * 100
    one_tick_pct = 0
    if len(tick_ring) >= 2:
        prev = tick_ring[-2]["price"]
        if prev > 0:
            one_tick_pct = (last["price"] - prev) / prev * 100

    if abs(change_pct) < state.tick_jump_threshold:
        return None

    direction = "急涨" if change_pct > 0 else "急跌"
    severity = "HIGH" if abs(change_pct) >= 3.0 else "MEDIUM" if abs(change_pct) >= 2.0 else "LOW"
    alert = {
        "id": f"alert_{market}_{now_ms}",
        "market": market,
        "marketName": market_name,
        "type": f"{market_name}_3TICK_JUMP",
        "direction": direction,
        "threshold": state.tick_jump_threshold,
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
