"""自适应波动率阈值模块。

基于近 N 根 bar 收益率的滚动变异系数（CV）动态调整策略阈值，
使策略在不同波动率环境下保持合理的信号频率。
"""

from __future__ import annotations

import math
from typing import Optional


def calc_cv(prices: list[float], window: int = 20) -> float:
    """计算最近 window 根 bar 收益率的变异系数（CV）。

    Returns:
        CV 值，若数据不足返回 0.0
    """
    if len(prices) < window + 1:
        return 0.0
    returns = []
    for i in range(len(prices) - window, len(prices)):
        prev = prices[i - 1]
        if prev and prev != 0:
            returns.append((prices[i] - prev) / prev)
    if len(returns) < 5:
        return 0.0
    mean_r = sum(returns) / len(returns)
    if len(returns) > 1:
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0
    else:
        std_r = 0.0
    cv = std_r / abs(mean_r) if mean_r != 0 else std_r * 100
    return cv if math.isfinite(cv) else 0.0


def adapt_threshold(
    base: float,
    prices: list[float],
    cv_factor: float = 0.5,
    min_mul: float = 0.5,
    max_mul: float = 2.0,
    short_window: int = 20,
    long_window: int = 60,
) -> float:
    """基于滚动 CV 比率动态调整阈值。

    公式: adjusted = base * (1 + cv_factor * (short_cv / long_cv - 1))
    限制在 [base * min_mul, base * max_mul] 范围内。

    Args:
        base: 基础阈值
        prices: 价格序列
        cv_factor: CV 敏感度系数，越大调整越激进
        min_mul: 最小调整倍数
        max_mul: 最大调整倍数
        short_window: 短期 CV 窗口
        long_window: 长期 CV 窗口（基准）

    Returns:
        调整后的阈值
    """
    if len(prices) < long_window + 1:
        return base

    short_cv = calc_cv(prices, short_window)
    long_cv = calc_cv(prices, long_window)

    if long_cv <= 0 or short_cv <= 0:
        return base

    ratio = short_cv / long_cv
    adjusted = base * (1 + cv_factor * (ratio - 1))
    return round(max(base * min_mul, min(base * max_mul, adjusted)), 6)


def adapt_min_score(
    base: float,
    prices: list[float],
    cv_factor: float = 0.3,
    min_score: float = 0.3,
    max_score: float = 0.9,
    short_window: int = 20,
    long_window: int = 60,
) -> float:
    """基于滚动 CV 动态调整反转策略的 min_score。

    高波动期提高门槛（过滤噪音），低波动期降低门槛（捕捉微弱信号）。
    """
    if len(prices) < long_window + 1:
        return base

    short_cv = calc_cv(prices, short_window)
    long_cv = calc_cv(prices, long_window)

    if long_cv <= 0 or short_cv <= 0:
        return base

    ratio = short_cv / long_cv
    # 波动率高于基准时提高门槛，低于时降低
    adjusted = base * (1 + cv_factor * (ratio - 1))
    return round(max(min_score, min(max_score, adjusted)), 4)
