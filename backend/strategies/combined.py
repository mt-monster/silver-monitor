"""组合信号策略：动量 + 反转 + MTF 趋势过滤 的融合决策。

改进后的核心规则：
1. MTF 趋势过滤：反转策略不做逆势单
2. 加权融合（替代简单二选一）：
   - 动量信号强度 × 动量权重 + 反转信号强度 × 反转权重 = 组合得分
   - 同向叠加 → 增强信号；反向冲突 → 取绝对值大的一方，但降级为非 strong
   - MTF 强趋势时自动提升动量权重，横盘时权重相等
3. 不再 require_strong_to_trade，允许 buy/sell 信号开仓
4. 保留信号级 cooldown（在 pollers 层处理）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.strategies.mtf import apply_mtf_to_reversal


@dataclass
class CombinedSignalParams:
    """组合信号参数。"""
    # MTF 开关
    enable_mtf: bool = True
    # 组合开关
    require_strong_to_trade: bool = False   # False: 允许 buy/sell 信号开仓
    conflict_preference: str = "momentum"   # "momentum" | "reversal" | "neutral"
    # 加权融合
    enable_weighted_fusion: bool = True
    momentum_weight: float = 0.6
    reversal_weight: float = 0.4
    mtf_trend_momentum_boost: float = 0.2   # 强趋势时动量权重的额外加成
    # 仓位缩放
    min_position_pct: float = 0.0
    max_position_pct: float = 1.0
    # 信号降级：当 MTF 趋势与动量方向矛盾时，是否降级动量信号
    downgrade_momentum_against_trend: bool = False


# 信号方向判定辅助函数
_SIGNAL_DIRECTIONS = {
    "strong_buy": "long",
    "buy": "long",
    "neutral": "flat",
    "sell": "short",
    "strong_sell": "short",
}

_SIGNAL_SCORES = {
    "strong_buy": 1.0,
    "buy": 0.5,
    "neutral": 0.0,
    "sell": -0.5,
    "strong_sell": -1.0,
}


def _direction(sig: str) -> str:
    return _SIGNAL_DIRECTIONS.get(sig, "flat")


def _is_strong(sig: str) -> bool:
    return sig in ("strong_buy", "strong_sell")


def _is_active(sig: str) -> bool:
    return sig in ("buy", "strong_buy", "sell", "strong_sell")


def _signal_score(sig: str, strength: float = 50.0) -> float:
    """将信号转换为方向强度分数 (-1.0 ~ 1.0)。

    不使用 strength 做二次缩放，因为 buy/strong_buy 本身已经是信号强度的层级表达。
    反转策略暂无 strength 字段，统一用 base score 保证两策略权重对等。
    """
    return _SIGNAL_SCORES.get(sig, 0.0)


def _score_to_signal(score: float) -> str:
    """将组合得分转换为信号。

    阈值设计目标：
    - 单一策略 buy (0.5) × 默认权重 0.6 = 0.3 ≥ 0.12 → buy 通过
    - 单一策略 strong_buy (1.0) × 0.6 = 0.6 ≥ 0.4 → strong_buy 通过
    - 双策略冲突（buy + sell）时，得分接近 0 → neutral，避免低质量冲突单
    """
    if score >= 0.4:
        return "strong_buy"
    elif score >= 0.12:
        return "buy"
    elif score <= -0.4:
        return "strong_sell"
    elif score <= -0.12:
        return "sell"
    return "neutral"


def calc_combined_signal(
    momentum_sig: dict[str, Any] | None,
    reversal_sig: dict[str, Any] | None,
    mtf_trend: str = "sideways",
    params: CombinedSignalParams | None = None,
) -> dict[str, Any]:
    """计算组合信号（加权融合版）。

    Args:
        momentum_sig: calc_momentum 返回值
        reversal_sig: calc_reversal 返回值（已或未经过 MTF 过滤）
        mtf_trend: MTF 大局方向
        params: 组合参数

    Returns:
        {
            "signal": str,
            "source": str,
            "direction": str,
            "positionPct": float,
            "strength": float,
            "momentum": dict,
            "reversal": dict,
            "mtfTrend": str,
            "reason": str,
            "combinedScore": float,
        }
    """
    p = params or CombinedSignalParams()

    mom = momentum_sig or {"signal": "neutral", "strength": 0}
    rev = reversal_sig or {"signal": "neutral", "strength": 0}

    mom_sig = mom.get("signal", "neutral")
    rev_sig = rev.get("signal", "neutral")
    mom_str = mom.get("strength", 0) or 0
    rev_str = rev.get("strength", 0) or 0

    # ── Step 1: MTF 过滤反转信号 ──────────────────────────────
    if p.enable_mtf:
        rev = apply_mtf_to_reversal(rev, mtf_trend)
        rev_sig = rev.get("signal", "neutral")
        rev_str = rev.get("strength", 0) or 0

    # ── Step 2: 动量信号 MTF 降级（可选）───────────────────────
    if p.enable_mtf and p.downgrade_momentum_against_trend:
        mom_dir = _direction(mom_sig)
        if mtf_trend == "down" and mom_dir == "long" and _is_active(mom_sig):
            mom_sig = "neutral"
            mom_str = 0
        elif mtf_trend == "up" and mom_dir == "short" and _is_active(mom_sig):
            mom_sig = "neutral"
            mom_str = 0

    # ── Step 3: 加权融合 ──────────────────────────────────────
    mom_score = _signal_score(mom_sig, mom_str)
    rev_score = _signal_score(rev_sig, rev_str)

    # 根据 MTF 趋势动态调整权重
    mom_w = p.momentum_weight
    rev_w = p.reversal_weight
    if p.enable_mtf and mtf_trend in ("up", "down"):
        mom_w = min(0.9, mom_w + p.mtf_trend_momentum_boost)
        rev_w = 1.0 - mom_w
    elif p.enable_mtf and mtf_trend == "sideways":
        mom_w = 0.5
        rev_w = 0.5

    combined_score = mom_score * mom_w + rev_score * rev_w

    # 确定最终信号
    final_sig = _score_to_signal(combined_score)

    # 确定 source 和 reason
    if not _is_active(mom_sig) and not _is_active(rev_sig):
        source = "none"
        reason = "双策略均观望"
    elif _is_active(mom_sig) and not _is_active(rev_sig):
        source = "momentum"
        reason = "动量信号独占"
    elif not _is_active(mom_sig) and _is_active(rev_sig):
        source = "reversal"
        reason = "反转信号独占"
    else:
        # 两策略都有信号
        mom_dir = _direction(mom_sig)
        rev_dir = _direction(rev_sig)
        if mom_dir == rev_dir:
            source = "combined"
            if _is_strong(mom_sig) and _is_strong(rev_sig):
                reason = f"双策略强{mom_dir}共振"
            elif _is_strong(mom_sig):
                reason = "动量强信号+反转同向确认"
            elif _is_strong(rev_sig):
                reason = "反转强信号+动量同向确认"
            else:
                reason = "双策略同向非强"
        else:
            # 方向冲突
            source = "combined"
            if abs(mom_score) >= abs(rev_score):
                reason = f"策略冲突，动量占优({combined_score:+.2f})"
            else:
                reason = f"策略冲突，反转占优({combined_score:+.2f})"

    # require_strong_to_trade 过滤（如果启用）
    if p.require_strong_to_trade and not _is_strong(final_sig):
        final_sig = "neutral"
        source = "none"
        reason += "，未达强信号门槛"

    # ── Step 4: 仓位权重计算 ──────────────────────────────────
    base_strength = abs(combined_score) * 100
    position_pct = min(p.max_position_pct, base_strength / 100)
    position_pct = max(p.min_position_pct, position_pct)

    # MTF confidence 加成/减成
    if mtf_trend == "up" and _direction(final_sig) == "long":
        position_pct = min(p.max_position_pct, position_pct * 1.2)
    elif mtf_trend == "down" and _direction(final_sig) == "short":
        position_pct = min(p.max_position_pct, position_pct * 1.2)
    elif mtf_trend == "sideways" and _direction(final_sig) != "flat":
        position_pct = min(p.max_position_pct, position_pct * 0.8)

    return {
        "signal": final_sig,
        "source": source,
        "direction": _direction(final_sig),
        "positionPct": round(position_pct * 100, 2),
        "strength": round(base_strength, 2),
        "momentum": mom,
        "reversal": rev,
        "mtfTrend": mtf_trend,
        "reason": reason,
        "combinedScore": round(combined_score, 4),
        "momentumScore": round(mom_score, 4),
        "reversalScore": round(rev_score, 4),
        "momentumWeight": round(mom_w, 2),
        "reversalWeight": round(rev_w, 2),
    }


def combined_params_from_body(body: dict) -> CombinedSignalParams:
    """从请求体解析组合信号参数。"""
    p = body.get("combined_params") or {}
    return CombinedSignalParams(
        enable_mtf=bool(p.get("enable_mtf", True)),
        require_strong_to_trade=bool(p.get("require_strong_to_trade", False)),
        conflict_preference=str(p.get("conflict_preference", "momentum")),
        enable_weighted_fusion=bool(p.get("enable_weighted_fusion", True)),
        momentum_weight=float(p.get("momentum_weight", 0.6)),
        reversal_weight=float(p.get("reversal_weight", 0.4)),
        mtf_trend_momentum_boost=float(p.get("mtf_trend_momentum_boost", 0.2)),
        min_position_pct=float(p.get("min_position_pct", 0.0)),
        max_position_pct=float(p.get("max_position_pct", 1.0)),
        downgrade_momentum_against_trend=bool(p.get("downgrade_momentum_against_trend", False)),
    )
