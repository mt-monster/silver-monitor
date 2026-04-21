"""分析计算模块：波动率、价差、聚合缓存。

提供滚动历史波动率（HV）计算和全量 API 响应缓存重建。
"""

import math
import time
from datetime import datetime, timezone
from typing import Any

from backend.config import CST, OZ_TO_G, OZ_TO_KG
from backend.models import CombinedApiResponse
from backend.state import state
from backend.utils import get_conv, get_conv_gold


def compute_rolling_hv(history_list: list[dict[str, Any]], window: int = 20) -> list[dict[str, Any]]:
    """计算滚动历史波动率（Historical Volatility）。

    公式：
        log_return = ln(price[t] / price[t-1])
        mean = mean(log_returns)
        variance = sum((ret - mean)^2) / (n - 1)
        HV = sqrt(variance) * sqrt(252) * 100  （年化，百分比）

    Args:
        history_list: 价格历史序列，每个元素为 {"t": 毫秒时间戳, "y": 价格}
        window: 滚动窗口大小，默认 20

    Returns:
        滚动 HV 序列，每个元素为 {"t": 时间戳, "y": HV值}
    """
    if len(history_list) < window + 1:
        return []

    prices = [entry["y"] for entry in history_list]
    result = []
    for i in range(window, len(prices)):
        window_prices = prices[i - window : i + 1]
        log_returns = [
            math.log(window_prices[j + 1] / window_prices[j])
            for j in range(len(window_prices) - 1)
            if window_prices[j + 1] > 0 and window_prices[j] > 0
        ]
        if len(log_returns) < 5:
            continue
        mean_r = sum(log_returns) / len(log_returns)
        var = sum((ret - mean_r) ** 2 for ret in log_returns) / (len(log_returns) - 1)
        hv = math.sqrt(max(0, var)) * math.sqrt(252) * 100
        result.append({"t": int(history_list[i]["t"]), "y": round(hv, 3)})
    return result


def _build_spread_data(
    domestic: dict | None,
    international: dict | None,
    conv_fn,
    oz_factor: float,
) -> dict[str, Any]:
    """计算内外盘价差数据（沪银-COMEX银 或 沪金-COMEX金）。

    Args:
        domestic: 国内品种数据（如沪银）
        international: 国际品种数据（如 COMEX 银）
        conv_fn: 汇率换算函数
        oz_factor: 盎司换算因子（OZ_TO_KG 或 OZ_TO_G）

    Returns:
        价差数据字典，含 ratio/cnySpread/status/deviation 等字段
    """
    if not domestic or not international:
        return {}
    if "error" in domestic or "error" in international:
        return {}
    if domestic.get("price", 0) <= 0 or international.get("price", 0) <= 0:
        return {}

    usd_cny = state.usd_cny_cache.get("rate", 7.26)
    # 优先使用品种特定的换算后价格（银: priceCny, 金: priceCnyG）
    intl_in_cny = (
        international.get("priceCny")
        or international.get("priceCnyG")
        or (international["price"] * conv_fn())
    )
    ratio = domestic["price"] / intl_in_cny if intl_in_cny > 0 else 0.0
    cny_spread = domestic["price"] - intl_in_cny

    if ratio > 1.06:
        status = "溢价偏高"
    elif ratio > 1.03:
        status = "轻度溢价"
    elif ratio > 0.98:
        status = "基本均衡"
    else:
        status = "折价"

    return {
        "ratio": round(ratio, 4),
        "cnySpread": round(cny_spread, 1),
        "comexInCNY": round(intl_in_cny, 1),
        "usdCNY": round(usd_cny, 4),
        "convFactor": round(usd_cny * oz_factor, 2),
        "status": status,
        "deviation": round((ratio - 1.0) * 100, 2),
    }


def rebuild_all_cache() -> CombinedApiResponse:
    """重建聚合 API 响应缓存，整合所有品种数据、信号、价差和波动率。

    返回的数据结构对应 `/api/all` 接口的完整响应。
    """
    with state.cache_lock:
        huyin = state.silver_cache.get("data")
        comex = state.comex_silver_cache.get("data")
        hujin = state.gold_cache.get("data")
        comex_gold = state.comex_gold_cache.get("data")
        btc = state.btc_cache.get("data")
        signals = {
            inst_id: dict(sig)
            for inst_id, sig in state.instrument_signals.items()
            if sig
        }

    active_sources = []
    for src in [comex, huyin, hujin, comex_gold, btc]:
        if src and "error" not in src:
            active_sources.append(src.get("source", "?"))

    # 银价差（沪银 vs COMEX银）
    spread_data = _build_spread_data(huyin, comex, get_conv, OZ_TO_KG)
    # 金价差（沪金 vs COMEX金）
    gold_spread_data = _build_spread_data(hujin, comex_gold, get_conv_gold, OZ_TO_G)

    # 滚动波动率
    hv_series = {"hu": [], "comex": [], "hujin": [], "comex_gold": []}
    for key, cache_data in [("hu", huyin), ("comex", comex), ("hujin", hujin), ("comex_gold", comex_gold)]:
        if cache_data and cache_data.get("history") and len(cache_data["history"]) > 20:
            hv_series[key] = compute_rolling_hv(cache_data["history"], window=20)

    # 金/银比
    gold_silver_ratio = None
    if comex_gold and comex_gold.get("price", 0) > 0 and comex and comex.get("price", 0) > 0:
        gold_silver_ratio = round(comex_gold["price"] / comex["price"], 2)

    all_data: CombinedApiResponse = {
        "comex": comex if comex else {"error": "comex_no_data"},
        "huyin": huyin if huyin else {"error": "hujin_no_data"},
        "comexGold": comex_gold if comex_gold else {"error": "comex_gold_no_data"},
        "hujin": hujin if hujin else {"error": "hujin_no_data"},
        "btc": btc if btc else {"error": "btc_no_data"},
        "signals": signals,
        "spread": spread_data,
        "goldSpread": gold_spread_data,
        "goldSilverRatio": gold_silver_ratio,
        "hvSeries": hv_series,
        "timestamp": int(time.time() * 1000),
        "datetime_utc": datetime.now(timezone.utc).isoformat(),
        "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "activeSources": active_sources,
    }

    with state.cache_lock:
        state.combined_cache["data"] = all_data
        state.combined_cache["ts"] = time.time()

    return all_data
