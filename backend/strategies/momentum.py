"""动量信号（EMA 短/长张口 + 短 EMA 一步斜率），与前端 momentum.js 对齐。"""

from __future__ import annotations

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


def calc_momentum(vals: list[float], params: MomentumParams | None = None) -> dict[str, Any] | None:
    """
    输入收盘价序列（与 JS 中 series 的 y 一致）。
    返回与 momentum.js calcMomentum 相同语义的字段；样本不足时返回 None。
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

    signal = "neutral"
    if last_s > last_l and spread_pct > p.spread_entry and slope_pct > p.slope_entry:
        signal = "strong_buy" if spread_pct > p.spread_strong else "buy"
    elif last_s < last_l and spread_pct < -p.spread_entry and slope_pct < -p.slope_entry:
        signal = "strong_sell" if spread_pct < -p.spread_strong else "sell"

    strength = min(100.0, abs(spread_pct) * p.strength_multiplier)

    return {
        "signal": signal,
        "spreadPct": spread_pct,
        "slopePct": slope_pct,
        "shortEMA": last_s,
        "longEMA": last_l,
        "strength": strength,
    }
