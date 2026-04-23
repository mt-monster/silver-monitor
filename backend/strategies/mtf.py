"""多时间框架趋势判断（Multi-Timeframe Trend Filter）。

使用品种 price_buffers（30s bar）聚合为 5min/15min K 线，计算大局方向，
用于过滤逆势交易信号。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.strategies.momentum import ema_series


@dataclass
class MTFConfig:
    """MTF 参数配置。"""
    fast_period_bars: int = 10      # 5min = 10 × 30s bar
    slow_period_bars: int = 30      # 15min = 30 × 30s bar
    sideways_threshold_pct: float = 0.03  # EMA 差值小于此比例视为横盘


# 全局默认配置
DEFAULT_MTF_CONFIG = MTFConfig()


def aggregate_to_ohlc(bars: list[float], n: int) -> list[dict[str, float]]:
    """将细粒度 bar 聚合为 OHLC（每 n 根聚合为 1 根）。
    
    Args:
        bars: 价格序列（如 30s bar 的收盘价）
        n: 每几根聚合为 1 根（如 10 表示 5min）
    
    Returns:
        [{open, high, low, close}, ...]
    """
    out: list[dict[str, float]] = []
    for i in range(0, len(bars), n):
        chunk = bars[i:i + n]
        if not chunk:
            continue
        out.append({
            "open": chunk[0],
            "high": max(chunk),
            "low": min(chunk),
            "close": chunk[-1],
        })
    return out


def calc_trend_direction(closes: list[float], config: MTFConfig | None = None) -> dict[str, Any]:
    """基于 EMA 交叉判断大局趋势方向。
    
    逻辑：
    - fast EMA（5min 等效） vs slow EMA（15min 等效）
    - fast > slow 且价差 > threshold → up（偏多）
    - fast < slow 且价差 > threshold → down（偏空）
    - 否则 → sideways（横盘）
    
    Args:
        closes: 较长周期的价格序列（如 30s bar 收盘价，至少 40 根）
        config: MTF 参数
    
    Returns:
        {"trend": "up"|"down"|"sideways", "fastEma": float, "slowEma": float,
         "spreadPct": float, "confidence": 0~1}
    """
    cfg = config or DEFAULT_MTF_CONFIG
    min_len = cfg.slow_period_bars + 5
    if len(closes) < min_len:
        return {"trend": "sideways", "fastEma": None, "slowEma": None,
                "spreadPct": 0.0, "confidence": 0.0, "note": "insufficient_data"}

    ema_fast = ema_series(closes, cfg.fast_period_bars)
    ema_slow = ema_series(closes, cfg.slow_period_bars)

    fast = ema_fast[-1]
    slow = ema_slow[-1]
    if fast is None or slow is None or slow == 0:
        return {"trend": "sideways", "fastEma": fast, "slowEma": slow,
                "spreadPct": 0.0, "confidence": 0.0}

    spread_pct = ((fast - slow) / slow) * 100
    abs_spread = abs(spread_pct)

    # 置信度：0（刚好阈值）→ 1（spread 达到阈值3倍）
    confidence = min(1.0, abs_spread / max(cfg.sideways_threshold_pct * 3, 1e-9))

    if abs_spread <= cfg.sideways_threshold_pct:
        trend = "sideways"
    elif spread_pct > 0:
        trend = "up"
    else:
        trend = "down"

    return {
        "trend": trend,
        "fastEma": fast,
        "slowEma": slow,
        "spreadPct": round(spread_pct, 4),
        "confidence": round(confidence, 2),
    }


def calc_mtf_from_buffer(buf_30s: list[float], config: MTFConfig | None = None) -> dict[str, Any]:
    """从 30s 价格缓冲计算 MTF 趋势（兼容现有 instrument_price_buffers）。
    
    额外聚合 5min/15min OHLC 供展示。
    """
    cfg = config or DEFAULT_MTF_CONFIG
    trend_result = calc_trend_direction(buf_30s, cfg)

    # 聚合 OHLC 用于展示
    bars_5m = aggregate_to_ohlc(buf_30s, cfg.fast_period_bars)
    bars_15m = aggregate_to_ohlc(buf_30s, cfg.slow_period_bars)

    trend_result["bars5m"] = len(bars_5m)
    trend_result["bars15m"] = len(bars_15m)
    if bars_5m:
        trend_result["last5mClose"] = round(bars_5m[-1]["close"], 4)
    if bars_15m:
        trend_result["last15mClose"] = round(bars_15m[-1]["close"], 4)

    return trend_result


def apply_mtf_to_reversal(reversal_sig: dict[str, Any] | None, mtf_trend: str) -> dict[str, Any] | None:
    """将 MTF 趋势过滤应用到反转信号：不做逆势单。
    
    过滤规则：
    - mtf_trend == "down" 且 reversal 为 buy/strong_buy → 压制为 neutral（大局跌时不抄底）
    - mtf_trend == "up"   且 reversal 为 sell/strong_sell → 压制为 neutral（大局涨时不摸顶）
    - 其他情况保持原信号
    
    Args:
        reversal_sig: calc_reversal 的返回值
        mtf_trend: "up" | "down" | "sideways"
    
    Returns:
        过滤后的信号字典（含 mtfFiltered 标记）
    """
    if not reversal_sig or not reversal_sig.get("signal"):
        return reversal_sig

    sig = reversal_sig["signal"]
    filtered = False
    new_sig = sig

    if mtf_trend == "down" and sig in ("buy", "strong_buy"):
        new_sig = "neutral"
        filtered = True
    elif mtf_trend == "up" and sig in ("sell", "strong_sell"):
        new_sig = "neutral"
        filtered = True

    result = dict(reversal_sig)
    result["signal"] = new_sig
    result["mtfTrend"] = mtf_trend
    if filtered:
        result["mtfFiltered"] = True
        result["originalSignal"] = sig
    return result
