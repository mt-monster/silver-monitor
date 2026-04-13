import math
import time
from datetime import datetime, timezone

from backend.config import CST, OZ_TO_G, OZ_TO_KG
from backend.state import state
from backend.utils import get_conv, get_conv_gold


def compute_rolling_hv(history_list, window=20):
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


def rebuild_all_cache():
    with state.cache_lock:
        huyin = state.silver_cache.get("data")
        comex = state.comex_silver_cache.get("data")
        hujin = state.gold_cache.get("data")
        comex_gold = state.comex_gold_cache.get("data")

    spread_data = {}
    gold_spread_data = {}
    active_sources = []
    hv_series = {"hu": [], "comex": [], "hujin": [], "comex_gold": []}

    for src in [comex, huyin, hujin, comex_gold]:
        if src and "error" not in src:
            active_sources.append(src.get("source", "?"))

    if comex and "error" not in comex and comex.get("price", 0) > 0 and huyin and "error" not in huyin and huyin.get("price", 0) > 0:
        usd_cny = state.usd_cny_cache.get("rate", 7.26)
        comex_in_cny = comex.get("priceCny") or (comex["price"] * get_conv())
        ratio = huyin["price"] / comex_in_cny if comex_in_cny > 0 else 0
        cny_spread = huyin["price"] - comex_in_cny

        if ratio > 1.06:
            status = "溢价偏高"
        elif ratio > 1.03:
            status = "轻度溢价"
        elif ratio > 0.98:
            status = "基本均衡"
        else:
            status = "折价"

        spread_data = {
            "ratio": round(ratio, 4),
            "cnySpread": round(cny_spread, 1),
            "comexInCNY": round(comex_in_cny, 1),
            "usdCNY": round(usd_cny, 4),
            "convFactor": round(usd_cny * OZ_TO_KG, 2),
            "status": status,
            "deviation": round((ratio - 1.0) * 100, 2),
        }

    if (
        comex_gold
        and "error" not in comex_gold
        and comex_gold.get("price", 0) > 0
        and hujin
        and "error" not in hujin
        and hujin.get("price", 0) > 0
    ):
        usd_cny = state.usd_cny_cache.get("rate", 7.26)
        comex_gold_in_cny_g = comex_gold.get("priceCnyG") or (comex_gold["price"] * get_conv_gold())
        ratio_g = hujin["price"] / comex_gold_in_cny_g if comex_gold_in_cny_g > 0 else 0
        cny_spread_g = hujin["price"] - comex_gold_in_cny_g

        if ratio_g > 1.06:
            status_g = "溢价偏高"
        elif ratio_g > 1.03:
            status_g = "轻度溢价"
        elif ratio_g > 0.98:
            status_g = "基本均衡"
        else:
            status_g = "折价"

        gold_spread_data = {
            "ratio": round(ratio_g, 4),
            "cnySpread": round(cny_spread_g, 2),
            "comexInCNYG": round(comex_gold_in_cny_g, 2),
            "usdCNY": round(usd_cny, 4),
            "convFactor": round(usd_cny * OZ_TO_G, 2),
            "status": status_g,
            "deviation": round((ratio_g - 1.0) * 100, 2),
        }

    for key, cache_data in [("hu", huyin), ("comex", comex), ("hujin", hujin), ("comex_gold", comex_gold)]:
        if cache_data and cache_data.get("history") and len(cache_data["history"]) > 20:
            hv_series[key] = compute_rolling_hv(cache_data["history"], window=20)

    gold_silver_ratio = None
    if comex_gold and comex_gold.get("price", 0) > 0 and comex and comex.get("price", 0) > 0:
        gold_silver_ratio = round(comex_gold["price"] / comex["price"], 2)

    all_data = {
        "comex": comex if comex else {"error": "comex_no_data"},
        "huyin": huyin if huyin else {"error": "huyin_no_data"},
        "comexGold": comex_gold if comex_gold else {"error": "comex_gold_no_data"},
        "hujin": hujin if hujin else {"error": "hujin_no_data"},
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
