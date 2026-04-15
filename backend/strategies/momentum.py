"""动量信号（EMA 短/长张口 + 短 EMA 一步斜率 + Bollinger 带融合），与前端 momentum.js 对齐。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MomentumParams:
    short_p: int = 5
    long_p: int = 20
    spread_entry: float = 0.10
    spread_strong: float = 0.35
    slope_entry: float = 0.02
    strength_multiplier: float = 120.0
    cooldown_bars: int = 0
    bb_period: int = 20
    bb_mult: float = 2.0


def ema_series(values: list[float], period: int) -> list[float]:
    """EMA with SMA seed: uses average of first `period` values as initial seed to reduce cold-start bias."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    n = len(values)
    if n >= period:
        seed = sum(values[:period]) / period
        out: list[float | None] = [None] * (period - 1) + [seed]
        for i in range(period, n):
            out.append(values[i] * k + out[i - 1] * (1 - k))
        return out  # type: ignore[return-value]
    out_simple = [values[0]]
    for i in range(1, n):
        out_simple.append(values[i] * k + out_simple[i - 1] * (1 - k))
    return out_simple


def bollinger_at(values: list[float], period: int, mult: float) -> dict[str, Any] | None:
    """计算最后一根 bar 的 Bollinger Band 指标。"""
    n = len(values)
    if n < period or period < 2:
        return None
    window = values[n - period:]
    sma = sum(window) / period
    var = sum((x - sma) ** 2 for x in window) / period
    std = math.sqrt(var)
    upper = sma + mult * std
    lower = sma - mult * std
    price = values[-1]
    band_width = upper - lower
    pct_b = (price - lower) / band_width if band_width > 1e-12 else 0.5
    bandwidth = band_width / sma * 100 if sma > 0 else 0.0
    return {
        "upper": upper,
        "middle": sma,
        "lower": lower,
        "percentB": pct_b,
        "bandwidth": bandwidth,
    }


def _fuse_with_bb(base_signal: str, pct_b: float, bw_expanding: bool) -> str:
    """
    用 Bollinger %B 位置和带宽变化修正 EMA 动量信号。

    规则：
    - buy  + %B < 0.3        → neutral     位置与方向矛盾
    - buy  + %B > 0.5 + 扩张  → strong_buy  趋势/位置/波动率三确认
    - strong_buy + %B > 1.0   → buy         过度延伸
    - sell + %B > 0.7         → neutral     位置与方向矛盾
    - sell + %B < 0.5 + 扩张  → strong_sell 三确认
    - strong_sell + %B < 0.0  → sell        超卖反弹风险
    """
    sig = base_signal
    if sig == "buy":
        if pct_b < 0.3:
            sig = "neutral"
        elif pct_b > 0.5 and bw_expanding:
            sig = "strong_buy"
    elif sig == "strong_buy":
        if pct_b > 1.0:
            sig = "buy"
    elif sig == "sell":
        if pct_b > 0.7:
            sig = "neutral"
        elif pct_b < 0.5 and bw_expanding:
            sig = "strong_sell"
    elif sig == "strong_sell":
        if pct_b < 0.0:
            sig = "sell"
    return sig


def calc_momentum(vals: list[float], params: MomentumParams | None = None) -> dict[str, Any] | None:
    """
    输入收盘价序列（与 JS 中 series 的 y 一致）。
    返回与 momentum.js calcMomentum 相同语义的字段；样本不足时返回 None。
    当 bb_period > 0 时自动计算 Bollinger 带并融合信号。
    """
    p = params or MomentumParams()
    min_len = p.long_p + 2
    if not vals or len(vals) < min_len:
        return None

    ema_s = ema_series(vals, p.short_p)
    ema_l = ema_series(vals, p.long_p)
    last_s = ema_s[-1]
    last_l = ema_l[-1]
    prev_s = ema_s[-2]
    if last_s is None or last_l is None or prev_s is None:
        return None
    spread_pct = ((last_s - last_l) / last_l) * 100 if last_l != 0 else 0.0
    slope_pct = ((last_s - prev_s) / prev_s) * 100 if prev_s != 0 else 0.0

    # EMA 基础信号
    signal = "neutral"
    if last_s > last_l and spread_pct > p.spread_entry and slope_pct > p.slope_entry:
        signal = "strong_buy" if spread_pct > p.spread_strong else "buy"
    elif last_s < last_l and spread_pct < -p.spread_entry and slope_pct < -p.slope_entry:
        signal = "strong_sell" if spread_pct < -p.spread_strong else "sell"

    # Bollinger 带融合
    bb_info: dict[str, Any] | None = None
    squeeze = False
    if p.bb_period > 0 and len(vals) >= p.bb_period:
        bb_now = bollinger_at(vals, p.bb_period, p.bb_mult)
        bb_prev = bollinger_at(vals[:-1], p.bb_period, p.bb_mult) if len(vals) > p.bb_period else None
        if bb_now:
            bw_expanding = bb_prev is not None and bb_now["bandwidth"] > bb_prev["bandwidth"]
            signal = _fuse_with_bb(signal, bb_now["percentB"], bw_expanding)
            # Squeeze: 当前带宽 ≤ 近 bb_period 根 bar 最小带宽
            if len(vals) >= p.bb_period * 2:
                bws: list[float] = []
                for j in range(p.bb_period):
                    end = len(vals) - j
                    if end >= p.bb_period:
                        bb_j = bollinger_at(vals[:end], p.bb_period, p.bb_mult)
                        if bb_j:
                            bws.append(bb_j["bandwidth"])
                if bws and bb_now["bandwidth"] <= min(bws):
                    squeeze = True
            bb_info = {
                "upper": bb_now["upper"],
                "middle": bb_now["middle"],
                "lower": bb_now["lower"],
                "percentB": bb_now["percentB"],
                "bandwidth": bb_now["bandwidth"],
                "bwExpanding": bw_expanding,
                "squeeze": squeeze,
            }

    strength = min(100.0, abs(spread_pct) * p.strength_multiplier)

    result: dict[str, Any] = {
        "signal": signal,
        "spreadPct": spread_pct,
        "slopePct": slope_pct,
        "shortEMA": last_s,
        "longEMA": last_l,
        "strength": strength,
    }
    if bb_info:
        result["bb"] = bb_info
    return result
