"""均值回归反转策略（RSI 超买超卖 + Bollinger %B 极值 + EMA 偏离度）。

核心思想：当价格大幅偏离均值且技术指标显示动量耗竭时，赌价格向均值回归。
与动量策略互补——动量追趋势，反转捕拐点。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.strategies.momentum import (
    bollinger_at,
    bollinger_series,
    ema_series,
    rsi_series,
)


@dataclass
class ReversalParams:
    # RSI
    rsi_period: int = 14
    rsi_oversold: float = 30.0       # RSI 低于此视为超卖
    rsi_overbought: float = 70.0     # RSI 高于此视为超买
    rsi_extreme_low: float = 20.0    # 极端超卖 → 强信号
    rsi_extreme_high: float = 80.0   # 极端超买 → 强信号

    # Bollinger Band
    bb_period: int = 20
    bb_mult: float = 2.0
    pctb_low: float = 0.05           # %B 低于此 → 超卖位置
    pctb_high: float = 0.95          # %B 高于此 → 超买位置
    pctb_extreme_low: float = -0.05  # 跌出下轨 → 极端超卖
    pctb_extreme_high: float = 1.05  # 突破上轨 → 极端超买

    # EMA 偏离
    ema_period: int = 20
    deviation_entry: float = 1.5     # 偏离度 (%) 触发入场
    deviation_strong: float = 2.5    # 偏离度 (%) 触发强信号

    # 信号融合权重
    rsi_weight: float = 0.4
    bb_weight: float = 0.35
    deviation_weight: float = 0.25

    # 确认 & 冷却
    min_score: float = 0.5           # 综合得分达到此值才发出信号
    strong_score: float = 0.8        # 强信号分数线
    cooldown_bars: int = 2


def calc_reversal(vals: list[float], params: ReversalParams | None = None) -> dict[str, Any] | None:
    """
    输入收盘价序列，返回反转信号。
    返回字段与 calc_momentum 同语义：signal, strength, spreadPct 等。
    样本不足返回 None。
    """
    p = params or ReversalParams()
    min_len = max(p.rsi_period + 1, p.bb_period, p.ema_period) + 2
    if not vals or len(vals) < min_len:
        return None

    # ── RSI 分数 ───────────────────────────────────────────────
    rsi_all = rsi_series(vals, p.rsi_period)
    rsi_val = rsi_all[-1]
    rsi_score = 0.0  # -1 ~ +1，正=看多反转，负=看空反转
    if rsi_val is not None:
        if rsi_val <= p.rsi_extreme_low:
            rsi_score = 1.0
        elif rsi_val <= p.rsi_oversold:
            rsi_score = (p.rsi_oversold - rsi_val) / (p.rsi_oversold - p.rsi_extreme_low)
        elif rsi_val >= p.rsi_extreme_high:
            rsi_score = -1.0
        elif rsi_val >= p.rsi_overbought:
            rsi_score = -(rsi_val - p.rsi_overbought) / (p.rsi_extreme_high - p.rsi_overbought)

    # ── Bollinger %B 分数 ──────────────────────────────────────
    bb_now = bollinger_at(vals, p.bb_period, p.bb_mult)
    bb_score = 0.0
    bb_info: dict[str, Any] | None = None
    if bb_now:
        pctb = bb_now["percentB"]
        if pctb <= p.pctb_extreme_low:
            bb_score = 1.0
        elif pctb <= p.pctb_low:
            bb_score = (p.pctb_low - pctb) / (p.pctb_low - p.pctb_extreme_low)
        elif pctb >= p.pctb_extreme_high:
            bb_score = -1.0
        elif pctb >= p.pctb_high:
            bb_score = -(pctb - p.pctb_high) / (p.pctb_extreme_high - p.pctb_high)

        bb_prev = bollinger_at(vals[:-1], p.bb_period, p.bb_mult) if len(vals) > p.bb_period else None
        bb_info = {
            "upper": bb_now["upper"],
            "middle": bb_now["middle"],
            "lower": bb_now["lower"],
            "percentB": bb_now["percentB"],
            "bandwidth": bb_now["bandwidth"],
            "bwExpanding": bb_prev is not None and bb_now["bandwidth"] > bb_prev["bandwidth"],
        }

    # ── EMA 偏离度分数 ────────────────────────────────────────
    ema = ema_series(vals, p.ema_period)
    ema_val = ema[-1]
    price = vals[-1]
    deviation_pct = 0.0
    dev_score = 0.0
    if ema_val and ema_val > 0:
        deviation_pct = ((price - ema_val) / ema_val) * 100
        abs_dev = abs(deviation_pct)
        if abs_dev >= p.deviation_strong:
            raw = 1.0
        elif abs_dev >= p.deviation_entry:
            raw = (abs_dev - p.deviation_entry) / (p.deviation_strong - p.deviation_entry)
        else:
            raw = 0.0
        # 价格低于 EMA → 看多反转（正分），高于 EMA → 看空反转（负分）
        dev_score = raw if deviation_pct < 0 else -raw

    # ── 综合评分 ──────────────────────────────────────────────
    total_score = (
        rsi_score * p.rsi_weight
        + bb_score * p.bb_weight
        + dev_score * p.deviation_weight
    )

    abs_score = abs(total_score)
    if abs_score >= p.strong_score:
        signal = "strong_buy" if total_score > 0 else "strong_sell"
    elif abs_score >= p.min_score:
        signal = "buy" if total_score > 0 else "sell"
    else:
        signal = "neutral"

    strength = min(100.0, abs_score * 100)

    result: dict[str, Any] = {
        "signal": signal,
        "score": round(total_score, 4),
        "rsiScore": round(rsi_score, 4),
        "bbScore": round(bb_score, 4),
        "devScore": round(dev_score, 4),
        "deviationPct": round(deviation_pct, 4),
        "strength": round(strength, 2),
        "ema": round(ema_val, 4) if ema_val else None,
        "rsi": round(rsi_val, 2) if rsi_val is not None else None,
    }
    if bb_info:
        result["bb"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in bb_info.items()}
    return result
