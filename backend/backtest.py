"""动量策略 long-only 回测与历史加载。"""

from __future__ import annotations

import math
from typing import Any, Callable

from backend.config import HAS_AKSHARE, RUNTIME_CONFIG
from backend.sources import (
    fetch_comex_gold_history,
    fetch_comex_history,
    fetch_hujin_history,
    fetch_huyin_history,
)
from backend.state import state
from backend.strategies.momentum import MomentumParams, calc_momentum

_HISTORY_FETCHERS: dict[str, tuple[str, Callable[[], list | None], Any]] = {
    "huyin": ("60m", fetch_huyin_history, state.silver_cache),
    "comex": ("1d", fetch_comex_history, state.comex_silver_cache),
    "hujin": ("60m", fetch_hujin_history, state.gold_cache),
    "comex_gold": ("1d", fetch_comex_gold_history, state.comex_gold_cache),
}


def normalize_bars(raw: list[dict]) -> list[dict]:
    out = []
    for row in raw:
        try:
            out.append({"t": int(row["t"]), "y": float(row["y"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def load_history(symbol: str) -> tuple[list[dict], str, str | None]:
    """
    返回 (bars, interval_label, error_code)。
    error_code: None 成功；akshare_not_available；unknown_symbol；no_history
    """
    key = symbol.lower().strip()
    if key not in _HISTORY_FETCHERS:
        return [], "", "unknown_symbol"
    interval, fetcher, cache = _HISTORY_FETCHERS[key]

    if not HAS_AKSHARE:
        return [], interval, "akshare_not_available"

    with state.cache_lock:
        data = cache.get("data") or {}
        hist = data.get("history")
        if isinstance(hist, list) and len(hist) >= 50:
            bars = normalize_bars(hist)
            if len(bars) >= 50:
                return bars, interval, None

    raw = fetcher()
    if not raw:
        return [], interval, "no_history"
    bars = normalize_bars(raw)
    if not bars:
        return [], interval, "no_history"
    return bars, interval, None


def run_momentum_long_only_backtest(bars: list[dict], params: MomentumParams) -> dict[str, Any]:
    min_len = params.long_p + 2
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    cash = 1.0
    shares = 0.0
    position_long = False

    for i in range(len(bars)):
        t, price = bars[i]["t"], bars[i]["y"]
        eq_before = cash + shares * price

        if i + 1 < min_len:
            equity_curve.append({"t": t, "equity": round(eq_before, 6), "price": price})
            continue

        vals = [float(b["y"]) for b in bars[: i + 1]]
        info = calc_momentum(vals, params)
        if info is None:
            equity_curve.append({"t": t, "equity": round(eq_before, 6), "price": price})
            continue

        sig = info["signal"]
        target_long = sig in ("strong_buy", "buy")

        if target_long and not position_long and cash > 0 and price > 0:
            shares = cash / price
            cash = 0.0
            position_long = True
            trades.append({"action": "buy", "t": t, "price": round(price, 6), "signal": sig})
        elif not target_long and position_long and shares > 0 and price > 0:
            cash = shares * price
            trades.append({"action": "sell", "t": t, "price": round(price, 6), "signal": sig})
            shares = 0.0
            position_long = False

        eq = cash + shares * price
        equity_curve.append({"t": t, "equity": round(eq, 6), "price": price})

    metrics = _compute_metrics(equity_curve, trades, bars)
    return {"equity": equity_curve, "trades": trades, "metrics": metrics}


def _compute_metrics(
    equity_curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    bars: list[dict],
) -> dict[str, Any]:
    if not equity_curve:
        return {}

    e0 = equity_curve[0]["equity"]
    e1 = equity_curve[-1]["equity"]
    total_return_pct = ((e1 / e0) - 1.0) * 100 if e0 > 0 else 0.0

    peak = 0.0
    max_dd = 0.0
    for row in equity_curve:
        e = row["equity"]
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)

    last_buy: float | None = None
    completed = 0
    wins = 0
    for tr in trades:
        if tr["action"] == "buy":
            last_buy = float(tr["price"])
        elif tr["action"] == "sell" and last_buy is not None:
            completed += 1
            if float(tr["price"]) > last_buy:
                wins += 1
            last_buy = None

    t0 = equity_curve[0]["t"]
    t1 = equity_curve[-1]["t"]
    span_ms = max(1, int(t1) - int(t0))
    span_years = span_ms / (1000.0 * 86400 * 365.25)
    ann: float | None = None
    if span_years > 0 and total_return_pct > -100:
        ann = ((1 + total_return_pct / 100.0) ** (1.0 / span_years) - 1.0) * 100

    sharpe = _annualized_sharpe(equity_curve, span_years)

    return {
        "totalReturnPct": round(total_return_pct, 4),
        "maxDrawdownPct": round(max_dd * 100, 4),
        "sellCount": sum(1 for tr in trades if tr["action"] == "sell"),
        "roundTripCount": completed,
        "winRatePct": round(wins / completed * 100, 2) if completed > 0 else None,
        "annualizedReturnPct": round(ann, 4) if ann is not None else None,
        "sharpeRatio": round(sharpe, 4) if sharpe is not None else None,
        "bars": len(bars),
        "note": "不计手续费与滑点；年化按首尾时间线性外推；夏普基于权益逐期收益、无风险利率=0 年化，仅供参考。",
    }


def _annualized_sharpe(equity_curve: list[dict[str, Any]], span_years: float) -> float | None:
    """
    年化夏普：均值(简单收益率)/样本标准差 * sqrt(期内期数/span_years)，无风险利率按 0。
    收益率按相邻两点的权益比值计算；样本不足或方差为 0 时返回 None。
    """
    if span_years <= 0 or len(equity_curve) < 3:
        return None
    eqs = [float(row["equity"]) for row in equity_curve]
    rets: list[float] = []
    for i in range(1, len(eqs)):
        prev = eqs[i - 1]
        if prev <= 0:
            continue
        rets.append(eqs[i] / prev - 1.0)
    n = len(rets)
    if n < 2:
        return None
    mean_r = sum(rets) / n
    var = sum((r - mean_r) ** 2 for r in rets) / (n - 1)
    if var <= 0:
        return None
    std_r = math.sqrt(var)
    if std_r <= 1e-12:
        return None
    periods_per_year = n / span_years
    if periods_per_year <= 0:
        return None
    return (mean_r / std_r) * math.sqrt(periods_per_year)


def momentum_params_from_body(body: dict) -> MomentumParams:
    base = RUNTIME_CONFIG.get("momentum") or {}
    p = body.get("params") or {}
    return MomentumParams(
        short_p=int(p.get("short_p", base.get("short_p", 5))),
        long_p=int(p.get("long_p", base.get("long_p", 20))),
        spread_entry=float(p.get("spread_entry", base.get("spread_entry", 0.10))),
        spread_strong=float(p.get("spread_strong", base.get("spread_strong", 0.35))),
        slope_entry=float(p.get("slope_entry", base.get("slope_entry", 0.02))),
    )
