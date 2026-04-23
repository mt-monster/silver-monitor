"""组合信号策略：动量 + 反转 + MTF 趋势过滤 的融合决策。

核心规则：
1. MTF 趋势过滤：反转策略不做逆势单
2. 组合开关：
   - 两策略都 neutral → neutral（空仓观望）
   - 至少一个产生 strong 信号 → 开仓
   - 只有一个非 neutral → 取该信号
   - 冲突时（一个 buy 一个 sell）→ 优先反转策略（短周期更稳健）
3. 仓位权重：基于 signal strength 和 trend confidence 动态调整
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
    require_strong_to_trade: bool = True   # True: 仅 strong 信号才开仓
    conflict_preference: str = "reversal"  # "reversal" | "momentum" | "neutral"
    # 仓位缩放
    min_position_pct: float = 0.0          # 最低仓位比例
    max_position_pct: float = 1.0          # 最高仓位比例
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


def _direction(sig: str) -> str:
    return _SIGNAL_DIRECTIONS.get(sig, "flat")


def _is_strong(sig: str) -> bool:
    return sig in ("strong_buy", "strong_sell")


def _is_active(sig: str) -> bool:
    return sig in ("buy", "strong_buy", "sell", "strong_sell")


def calc_combined_signal(
    momentum_sig: dict[str, Any] | None,
    reversal_sig: dict[str, Any] | None,
    mtf_trend: str = "sideways",
    params: CombinedSignalParams | None = None,
) -> dict[str, Any]:
    """计算组合信号。
    
    Args:
        momentum_sig: calc_momentum 返回值
        reversal_sig: calc_reversal 返回值（已或未经过 MTF 过滤）
        mtf_trend: MTF 大局方向
        params: 组合参数
    
    Returns:
        {
            "signal": str,              # 最终信号
            "source": str,              # "momentum" | "reversal" | "combined" | "none"
            "direction": str,           # "long" | "short" | "flat"
            "positionPct": float,       # 建议仓位 0~100
            "strength": float,          # 0~100
            "momentum": dict,           # 原始动量信号
            "reversal": dict,           # 原始/过滤后反转信号
            "mtfTrend": str,
            "reason": str,              # 决策理由
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

    # ── Step 3: 组合开关逻辑 ──────────────────────────────────
    final_sig = "neutral"
    source = "none"
    reason = ""

    mom_dir = _direction(mom_sig)
    rev_dir = _direction(rev_sig)

    # 情况 A：两策略都 neutral → 空仓观望
    if not _is_active(mom_sig) and not _is_active(rev_sig):
        final_sig = "neutral"
        source = "none"
        reason = "双策略均观望"

    # 情况 B：仅动量有信号
    elif _is_active(mom_sig) and not _is_active(rev_sig):
        if not p.require_strong_to_trade or _is_strong(mom_sig):
            final_sig = mom_sig
            source = "momentum"
            reason = "动量信号独占"
        else:
            final_sig = "neutral"
            source = "none"
            reason = "动量信号非强，未达开仓门槛"

    # 情况 C：仅反转有信号
    elif not _is_active(mom_sig) and _is_active(rev_sig):
        if not p.require_strong_to_trade or _is_strong(rev_sig):
            final_sig = rev_sig
            source = "reversal"
            reason = "反转信号独占"
        else:
            final_sig = "neutral"
            source = "none"
            reason = "反转信号非强，未达开仓门槛"

    # 情况 D：两策略都有信号
    else:
        # 方向一致
        if mom_dir == rev_dir:
            # 都 strong → 叠加信号（取更强的那个）
            if _is_strong(mom_sig) and _is_strong(rev_sig):
                final_sig = mom_sig if mom_str >= rev_str else rev_sig
                source = "combined"
                reason = f"双策略强{mom_dir}共振"
            # 只有一个 strong
            elif _is_strong(mom_sig):
                final_sig = mom_sig
                source = "combined"
                reason = "动量强信号+反转同向确认"
            elif _is_strong(rev_sig):
                final_sig = rev_sig
                source = "combined"
                reason = "反转强信号+动量同向确认"
            else:
                # 都非 strong
                if p.require_strong_to_trade:
                    final_sig = "neutral"
                    source = "none"
                    reason = "双策略同向但均未达强信号门槛"
                else:
                    final_sig = rev_sig  # 优先反转
                    source = "reversal"
                    reason = "双策略同向非强，优先反转"
        # 方向冲突
        else:
            if p.conflict_preference == "reversal":
                final_sig = rev_sig if (not p.require_strong_to_trade or _is_strong(rev_sig)) else "neutral"
                source = "reversal" if final_sig != "neutral" else "none"
                reason = "策略冲突，优先反转" if final_sig != "neutral" else "策略冲突，反转非强，空仓"
            elif p.conflict_preference == "momentum":
                final_sig = mom_sig if (not p.require_strong_to_trade or _is_strong(mom_sig)) else "neutral"
                source = "momentum" if final_sig != "neutral" else "none"
                reason = "策略冲突，优先动量" if final_sig != "neutral" else "策略冲突，动量非强，空仓"
            else:
                final_sig = "neutral"
                source = "none"
                reason = "策略冲突，按规则空仓"

    # ── Step 4: 仓位权重计算 ──────────────────────────────────
    base_strength = 0.0
    if source == "momentum":
        base_strength = mom_str
    elif source == "reversal":
        base_strength = rev_str
    elif source == "combined":
        base_strength = max(mom_str, rev_str)

    # MTF confidence 加成/减成
    mtf_confidence = 0.5  # default
    if isinstance(mom, dict) and "mtfConfidence" in mom:
        mtf_confidence = mom["mtfConfidence"]
    elif isinstance(rev, dict) and "mtfConfidence" in rev:
        mtf_confidence = rev["mtfConfidence"]

    # 趋势一致时仓位更高
    final_dir = _direction(final_sig)
    if mtf_trend == "up" and final_dir == "long":
        position_pct = min(p.max_position_pct, base_strength / 100 * 1.2)
    elif mtf_trend == "down" and final_dir == "short":
        position_pct = min(p.max_position_pct, base_strength / 100 * 1.2)
    elif mtf_trend == "sideways" and final_dir != "flat":
        position_pct = min(p.max_position_pct, base_strength / 100 * 0.8)
    else:
        position_pct = min(p.max_position_pct, base_strength / 100)

    position_pct = max(p.min_position_pct, position_pct)

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
    }


def combined_params_from_body(body: dict) -> CombinedSignalParams:
    """从请求体解析组合信号参数。"""
    p = body.get("combined_params") or {}
    return CombinedSignalParams(
        enable_mtf=bool(p.get("enable_mtf", True)),
        require_strong_to_trade=bool(p.get("require_strong_to_trade", True)),
        conflict_preference=str(p.get("conflict_preference", "reversal")),
        min_position_pct=float(p.get("min_position_pct", 0.0)),
        max_position_pct=float(p.get("max_position_pct", 1.0)),
        downgrade_momentum_against_trend=bool(p.get("downgrade_momentum_against_trend", False)),
    )
