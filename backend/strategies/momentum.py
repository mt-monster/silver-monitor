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
    rsi_period: int = 14  # 0 = disabled
    bb_buy_kill: float = 0.3   # buy 信号在 %B 低于此值时被压制为 neutral
    bb_sell_kill: float = 0.7  # sell 信号在 %B 高于此值时被压制为 neutral
    min_volatility_pct: float = 0.0  # 最小价格波动率(%)。>0 时若近期 CV 低于此值，方向信号降级为 neutral


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


def rsi_series(values: list[float], period: int = 14) -> list[float | None]:
    """RSI via Wilder's smoothed moving average."""
    n = len(values)
    if n < period + 1:
        return [None] * n
    out: list[float | None] = [None] * n
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss < 1e-12:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, n):
        diff = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(diff, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-diff, 0.0)) / period
        if avg_loss < 1e-12:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


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


def bollinger_series(values: list[float], period: int, mult: float) -> list[dict | None]:
    """Rolling Bollinger Band for all bars, returns list aligned with values."""
    n = len(values)
    out: list[dict | None] = [None] * n
    if n < period or period < 2:
        return out
    for i in range(period - 1, n):
        window = values[i - period + 1: i + 1]
        sma = sum(window) / period
        var = sum((x - sma) ** 2 for x in window) / period
        std = math.sqrt(var)
        upper = sma + mult * std
        lower = sma - mult * std
        bw = upper - lower
        pct_b = (values[i] - lower) / bw if bw > 1e-12 else 0.5
        bandwidth = bw / sma * 100 if sma > 0 else 0.0
        out[i] = {"percentB": pct_b, "bandwidth": bandwidth}
    return out


def _fuse_with_bb(base_signal: str, pct_b: float, bw_expanding: bool,
                  buy_kill: float = 0.3, sell_kill: float = 0.7) -> str:
    """
    用 Bollinger %B 位置和带宽变化修正 EMA 动量信号。

    buy_kill / sell_kill 可按品种配置，降低阈值可减少压制、提升灵敏度。

    规则：
    - buy  + %B < buy_kill    → neutral     位置与方向矛盾
    - buy  + %B > 0.5 + 扩张  → strong_buy  趋势/位置/波动率三确认
    - strong_buy + %B > 1.0   → buy         过度延伸
    - sell + %B > sell_kill    → neutral     位置与方向矛盾
    - sell + %B < 0.5 + 扩张  → strong_sell 三确认
    - strong_sell + %B < 0.0  → sell        超卖反弹风险
    """
    sig = base_signal
    if sig == "buy":
        if pct_b < buy_kill:
            sig = "neutral"
        elif pct_b > 0.5 and bw_expanding:
            sig = "strong_buy"
    elif sig == "strong_buy":
        if pct_b > 1.0:
            sig = "buy"
    elif sig == "sell":
        if pct_b > sell_kill:
            sig = "neutral"
        elif pct_b < 0.5 and bw_expanding:
            sig = "strong_sell"
    elif sig == "strong_sell":
        if pct_b < 0.0:
            sig = "sell"
    return sig


def _fuse_with_rsi(base_signal: str, rsi: float) -> str:
    """RSI 超买/超卖修正信号。"""
    sig = base_signal
    if sig == "buy" and rsi > 70:
        sig = "neutral"
    elif sig == "sell" and rsi < 30:
        sig = "neutral"
    return sig


def _apply_signal_cooldown(signal: str, last_active: str, cooldown: int, cooldown_bars: int) -> tuple[str, int, bool]:
    """
    实时信号 cooldown 逻辑：方向翻转后 N 个 bar 内压制信号为 neutral。

    规则：
    - 趋势持续（buy→buy, buy→strong_buy）：信号正常输出，cooldown 自然衰减
    - 趋势反转（buy→sell）：cooldown 期间被压制为 neutral
    - 趋势减弱（buy→neutral）：正常输出 neutral
    - 新方向信号（neutral→buy/sell）触发 cooldown

    返回: (处理后的信号, 新的 cooldown 值, 是否更新了 last_active)
    """
    def _direction(s: str) -> str:
        if s in ("buy", "strong_buy"):
            return "long"
        if s in ("sell", "strong_sell"):
            return "short"
        return "flat"

    sig_dir = _direction(signal)
    last_dir = _direction(last_active)

    new_cooldown = max(0, cooldown - 1)
    updated_last = False

    # cooldown 期间，只允许同向信号通过；反向信号被压制为 neutral
    if cooldown > 0 and sig_dir != last_dir and sig_dir != "flat":
        return "neutral", new_cooldown, updated_last

    # 新的活跃方向信号触发 cooldown（包括 flat→long/short，以及 long↔short）
    if sig_dir != "flat" and sig_dir != last_dir:
        new_cooldown = cooldown_bars

    if sig_dir != "flat":
        updated_last = True

    return signal, new_cooldown, updated_last


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
            signal = _fuse_with_bb(signal, bb_now["percentB"], bw_expanding,
                                   buy_kill=p.bb_buy_kill, sell_kill=p.bb_sell_kill)
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

    # RSI 融合
    rsi_val: float | None = None
    if p.rsi_period > 0 and len(vals) >= p.rsi_period + 1:
        rsi_all = rsi_series(vals, p.rsi_period)
        rsi_val = rsi_all[-1]
        if rsi_val is not None:
            signal = _fuse_with_rsi(signal, rsi_val)

    # 波动率过滤：横盘/噪声环境时抑制方向性信号
    # 自适应阈值：根据近期 CV 动态调整，低波动时逐步放开
    volatility_pct: float | None = None
    adaptive_vol_threshold: float | None = None
    if p.min_volatility_pct > 0.0 and len(vals) >= max(p.bb_period, p.short_p):
        lookback = max(p.bb_period, p.short_p)
        recent = vals[-lookback:]
        avg = sum(recent) / len(recent)
        if avg > 0:
            variance = sum((x - avg) ** 2 for x in recent) / len(recent)
            cv = math.sqrt(variance) / avg * 100.0
            volatility_pct = cv
            # 自适应阈值逻辑
            if cv < 0.005:
                adaptive_vol_threshold = 0.0  # 超超低波动：完全放开
            elif cv < 0.015:
                adaptive_vol_threshold = cv * 0.3  # 超低波动：极宽松
            elif cv < 0.03:
                adaptive_vol_threshold = cv * 0.6  # 低波动：宽松
            else:
                adaptive_vol_threshold = p.min_volatility_pct  # 正常波动：使用配置值
            if cv < adaptive_vol_threshold and signal in ("buy", "strong_buy", "sell", "strong_sell"):
                signal = "neutral"

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
    if rsi_val is not None:
        result["rsi"] = rsi_val
    if volatility_pct is not None:
        result["volatilityPct"] = round(volatility_pct, 4)
    if adaptive_vol_threshold is not None:
        result["adaptiveVolThreshold"] = round(adaptive_vol_threshold, 4)
    return result
