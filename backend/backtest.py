"""动量策略 long-only 回测与历史加载。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product
from typing import Any, Callable

from backend.config import RUNTIME_CONFIG
from backend.instruments import REGISTRY
from backend.sources import (
    fetch_comex_gold_history,
    fetch_comex_history,
    fetch_generic_domestic_history,
    fetch_generic_intl_history,
    fetch_hujin_history,
    fetch_huyin_history,
)
from backend.state import state
from backend.strategies.momentum import MomentumParams, _fuse_with_bb, _fuse_with_rsi, bollinger_series, calc_momentum, ema_series, rsi_series
from backend.strategies.reversal import ReversalParams, calc_reversal

@dataclass
class BacktestConfig:
    mode: str = "long_only"
    commission_rate: float = 0.0
    slippage_pct: float = 0.0


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
    error_code: None 成功；unknown_symbol；no_history
    优先使用专用 fetcher，回退到注册表通用获取。
    """
    key = symbol.lower().strip()

    # 1) 已有专用 fetcher（贵金属四个品种）
    if key in _HISTORY_FETCHERS:
        interval, fetcher, cache = _HISTORY_FETCHERS[key]
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
        return (bars, interval, None) if bars else ([], interval, "no_history")

    # 2) 注册表中的品种 → 通用 Sina 获取
    inst = REGISTRY.get(key)
    if inst is None:
        return [], "", "unknown_symbol"

    ak_symbol = inst.sina_code.replace("nf_", "").replace("hf_", "")
    if inst.is_intl:
        raw = fetch_generic_intl_history(ak_symbol, inst.decimals)
        interval = "1d"
    else:
        raw = fetch_generic_domestic_history(ak_symbol, inst.decimals)
        interval = "60m"
    if not raw:
        return [], interval, "no_history"
    bars = normalize_bars(raw)
    return (bars, interval, None) if bars else ([], interval, "no_history")


def run_momentum_long_only_backtest(bars: list[dict], params: MomentumParams, config: BacktestConfig | None = None) -> dict[str, Any]:
    cfg = config or BacktestConfig()
    cost_factor = max(0.0, 1.0 - cfg.commission_rate - cfg.slippage_pct)
    min_len = params.long_p + 2
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    cash = 1.0
    shares = 0.0
    position_long = False

    prices = [float(b["y"]) for b in bars]
    ema_s = ema_series(prices, params.short_p)
    ema_l = ema_series(prices, params.long_p)
    bb_data = bollinger_series(prices, params.bb_period, params.bb_mult) if params.bb_period > 0 else [None] * len(prices)
    rsi_data = rsi_series(prices, params.rsi_period) if params.rsi_period > 0 else [None] * len(prices)

    cooldown_remaining = 0

    for i in range(len(bars)):
        t, price = bars[i]["t"], bars[i]["y"]
        eq_before = cash + shares * price

        if i + 1 < min_len:
            equity_curve.append({"t": t, "equity": round(eq_before, 6), "price": price})
            continue

        last_s = ema_s[i]
        last_l = ema_l[i]
        prev_s = ema_s[i - 1]
        if last_s is None or last_l is None or prev_s is None:
            equity_curve.append({"t": t, "equity": round(eq_before, 6), "price": price})
            continue

        spread_pct = ((last_s - last_l) / last_l) * 100 if last_l != 0 else 0.0
        slope_pct = ((last_s - prev_s) / prev_s) * 100 if prev_s != 0 else 0.0

        sig = "neutral"
        if last_s > last_l and spread_pct > params.spread_entry and slope_pct > params.slope_entry:
            sig = "strong_buy" if spread_pct > params.spread_strong else "buy"
        elif last_s < last_l and spread_pct < -params.spread_entry and slope_pct < -params.slope_entry:
            sig = "strong_sell" if spread_pct < -params.spread_strong else "sell"

        # Bollinger 带融合
        bb_now = bb_data[i] if i < len(bb_data) else None
        bb_prev = bb_data[i - 1] if i > 0 and i - 1 < len(bb_data) else None
        if bb_now:
            bw_exp = bb_prev is not None and bb_now["bandwidth"] > bb_prev["bandwidth"]
            sig = _fuse_with_bb(sig, bb_now["percentB"], bw_exp)

        rsi_val = rsi_data[i] if i < len(rsi_data) else None
        if rsi_val is not None:
            sig = _fuse_with_rsi(sig, rsi_val)

        target_long = sig in ("strong_buy", "buy")

        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        elif target_long and not position_long and cash > 0 and price > 0:
            shares = cash * cost_factor / price
            cash = 0.0
            position_long = True
            cooldown_remaining = params.cooldown_bars
            trades.append({"action": "buy", "t": t, "price": round(price, 6), "signal": sig})
        elif not target_long and position_long and shares > 0 and price > 0:
            cash = shares * price * cost_factor
            trades.append({"action": "sell", "t": t, "price": round(price, 6), "signal": sig})
            shares = 0.0
            position_long = False
            cooldown_remaining = params.cooldown_bars

        eq = cash + shares * price
        equity_curve.append({"t": t, "equity": round(eq, 6), "price": price})

    metrics = _compute_metrics(equity_curve, trades, bars)
    if cfg.commission_rate > 0 or cfg.slippage_pct > 0:
        metrics["note"] = f"手续费{cfg.commission_rate*100:.3f}%/滑点{cfg.slippage_pct*100:.3f}%；" + metrics.get("note", "")
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

    last_entry: float | None = None
    last_side: str = ""
    completed = 0
    wins = 0
    for tr in trades:
        if tr["action"] in ("buy", "short"):
            last_entry = float(tr["price"])
            last_side = tr["action"]
        elif tr["action"] in ("sell", "cover") and last_entry is not None:
            completed += 1
            if last_side == "buy" and float(tr["price"]) > last_entry:
                wins += 1
            elif last_side == "short" and float(tr["price"]) < last_entry:
                wins += 1
            last_entry = None
            last_side = ""

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
        "sellCount": sum(1 for tr in trades if tr["action"] in ("sell", "cover")),
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


def momentum_params_for_symbol(symbol: str) -> MomentumParams:
    """从配置文件构建品种级别动量参数（无请求体覆盖）。"""
    return momentum_params_from_body({}, symbol)


def momentum_params_from_body(body: dict, symbol: str | None = None) -> MomentumParams:
    """
    从请求体和配置文件构建动量参数，支持品种级别配置。
    
    参数优先级：
    1. 请求体中的 params（最高优先级）
    2. 配置文件中的品种特定参数（如 momentum.huyin）
    3. 配置文件中的默认参数（momentum.default 或 momentum）
    """
    config = RUNTIME_CONFIG.get("momentum") or {}
    
    # 获取默认配置
    defaults = config.get("default") if isinstance(config.get("default"), dict) else config
    
    # 品种 ID 别名映射（instrument ID → config key）
    _aliases = {"ag0": "huyin", "xag": "comex", "au0": "hujin", "xau": "comex_gold"}
    resolved = _aliases.get(symbol, symbol) if symbol else symbol
    
    # 获取品种特定配置并合并
    symbol_config = {}
    if resolved and resolved in config and isinstance(config[resolved], dict):
        symbol_config = config[resolved]
    
    # 合并默认配置和品种配置
    merged = {**defaults, **symbol_config}
    
    # 请求体中的参数具有最高优先级
    p = body.get("params") or {}
    
    return MomentumParams(
        short_p=int(p.get("short_p", merged.get("short_p", 5))),
        long_p=int(p.get("long_p", merged.get("long_p", 20))),
        spread_entry=float(p.get("spread_entry", merged.get("spread_entry", 0.10))),
        spread_strong=float(p.get("spread_strong", merged.get("spread_strong", 0.35))),
        slope_entry=float(p.get("slope_entry", merged.get("slope_entry", 0.02))),
        strength_multiplier=float(p.get("strength_multiplier", merged.get("strength_multiplier", 120.0))),
        cooldown_bars=int(p.get("cooldown_bars", merged.get("cooldown_bars", 0))),
        bb_period=int(p.get("bb_period", merged.get("bb_period", 20))),
        bb_mult=float(p.get("bb_mult", merged.get("bb_mult", 2.0))),
        rsi_period=int(p.get("rsi_period", merged.get("rsi_period", 14))),
        bb_buy_kill=float(p.get("bb_buy_kill", merged.get("bb_buy_kill", 0.3))),
        bb_sell_kill=float(p.get("bb_sell_kill", merged.get("bb_sell_kill", 0.7))),
    )


def backtest_config_from_body(body: dict) -> BacktestConfig:
    return BacktestConfig(
        mode=str(body.get("mode", "long_only")).strip().lower(),
        commission_rate=float(body.get("commission_rate", 0.0)),
        slippage_pct=float(body.get("slippage_pct", 0.0)),
    )


# ── Long-Short 回测 ─────────────────────────────────────────────────

def run_momentum_long_short_backtest(
    bars: list[dict], params: MomentumParams, config: BacktestConfig | None = None,
) -> dict[str, Any]:
    """Long-Short: buy/strong_buy → long, sell/strong_sell → short, neutral → flat."""
    cfg = config or BacktestConfig()
    cost = max(0.0, 1.0 - cfg.commission_rate - cfg.slippage_pct)
    min_len = params.long_p + 2
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    prices = [float(b["y"]) for b in bars]
    ema_s = ema_series(prices, params.short_p)
    ema_l = ema_series(prices, params.long_p)
    bb_data = bollinger_series(prices, params.bb_period, params.bb_mult) if params.bb_period > 0 else [None] * len(prices)
    rsi_data = rsi_series(prices, params.rsi_period) if params.rsi_period > 0 else [None] * len(prices)
    pos = 0  # -1 short, 0 flat, +1 long
    entry_p = 0.0
    capital = 1.0
    cooldown = 0

    for i in range(len(bars)):
        t, px = bars[i]["t"], float(bars[i]["y"])
        if pos == 1 and entry_p > 0:
            eq = capital * px / entry_p
        elif pos == -1 and entry_p > 0:
            eq = capital * max(0.0, 2.0 - px / entry_p)
        else:
            eq = capital
        if i + 1 < min_len:
            equity_curve.append({"t": t, "equity": round(eq, 6), "price": px})
            continue
        ls, ll, ps = ema_s[i], ema_l[i], ema_s[i - 1]
        if ls is None or ll is None or ps is None:
            equity_curve.append({"t": t, "equity": round(eq, 6), "price": px})
            continue
        sp = ((ls - ll) / ll) * 100 if ll else 0.0
        slp = ((ls - ps) / ps) * 100 if ps else 0.0
        sig = "neutral"
        if ls > ll and sp > params.spread_entry and slp > params.slope_entry:
            sig = "strong_buy" if sp > params.spread_strong else "buy"
        elif ls < ll and sp < -params.spread_entry and slp < -params.slope_entry:
            sig = "strong_sell" if sp < -params.spread_strong else "sell"
        bb_now = bb_data[i] if i < len(bb_data) else None
        bb_prev = bb_data[i - 1] if i > 0 and i - 1 < len(bb_data) else None
        if bb_now:
            sig = _fuse_with_bb(sig, bb_now["percentB"], bb_prev is not None and bb_now["bandwidth"] > bb_prev["bandwidth"])
        rsi_v = rsi_data[i] if i < len(rsi_data) else None
        if rsi_v is not None:
            sig = _fuse_with_rsi(sig, rsi_v)

        tgt = 1 if sig in ("strong_buy", "buy") else (-1 if sig in ("strong_sell", "sell") else 0)
        if cooldown > 0:
            cooldown -= 1
        elif tgt != pos and px > 0:
            if pos == 1 and entry_p > 0:
                capital *= (px / entry_p) * cost
                trades.append({"action": "sell", "t": t, "price": round(px, 6), "signal": sig})
            elif pos == -1 and entry_p > 0:
                capital *= max(0.0, 2.0 - px / entry_p) * cost
                trades.append({"action": "cover", "t": t, "price": round(px, 6), "signal": sig})
            if tgt != 0:
                capital *= cost
                entry_p = px
                trades.append({"action": "buy" if tgt == 1 else "short", "t": t, "price": round(px, 6), "signal": sig})
            else:
                entry_p = 0.0
            pos = tgt
            cooldown = params.cooldown_bars
            eq = capital
        equity_curve.append({"t": t, "equity": round(eq, 6), "price": px})

    metrics = _compute_metrics(equity_curve, trades, bars)
    metrics["mode"] = "long_short"
    cost_str = f"手续费{cfg.commission_rate*100:.3f}%/滑点{cfg.slippage_pct*100:.3f}%；" if (cfg.commission_rate > 0 or cfg.slippage_pct > 0) else "不计手续费与滑点；"
    metrics["note"] = f"Long-Short，{cost_str}年化按首尾时间线性外推；夏普仅供参考。"
    return {"equity": equity_curve, "trades": trades, "metrics": metrics}


# ── 统一调度 ─────────────────────────────────────────────────────────

def run_momentum_backtest(
    bars: list[dict], params: MomentumParams, config: BacktestConfig | None = None,
) -> dict[str, Any]:
    cfg = config or BacktestConfig()
    if cfg.mode == "long_short":
        return run_momentum_long_short_backtest(bars, params, cfg)
    return run_momentum_long_only_backtest(bars, params, cfg)


# ── Grid Search ──────────────────────────────────────────────────────

def run_grid_search(
    bars: list[dict],
    grid_params: dict[str, list],
    base_params: dict | None = None,
    config: BacktestConfig | None = None,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Grid search over parameter space, returns top N by Sharpe ratio."""
    bp = base_params or {}
    names = sorted(grid_params.keys())
    combos = list(product(*(grid_params[k] for k in names)))
    if len(combos) > 500:
        combos = combos[:500]
    results: list[dict[str, Any]] = []
    for combo in combos:
        override = {**bp, **dict(zip(names, combo))}
        try:
            params = MomentumParams(
                short_p=int(override.get("short_p", 5)),
                long_p=int(override.get("long_p", 20)),
                spread_entry=float(override.get("spread_entry", 0.10)),
                spread_strong=float(override.get("spread_strong", 0.35)),
                slope_entry=float(override.get("slope_entry", 0.02)),
                strength_multiplier=float(override.get("strength_multiplier", 120.0)),
                cooldown_bars=int(override.get("cooldown_bars", 0)),
                bb_period=int(override.get("bb_period", 20)),
                bb_mult=float(override.get("bb_mult", 2.0)),
                rsi_period=int(override.get("rsi_period", 14)),
                bb_buy_kill=float(override.get("bb_buy_kill", 0.3)),
                bb_sell_kill=float(override.get("bb_sell_kill", 0.7)),
            )
        except (TypeError, ValueError):
            continue
        result = run_momentum_backtest(bars, params, config)
        m = result.get("metrics", {})
        results.append({
            "params": {"short_p": params.short_p, "long_p": params.long_p,
                       "spread_entry": params.spread_entry, "spread_strong": params.spread_strong,
                       "slope_entry": params.slope_entry, "bb_period": params.bb_period,
                       "rsi_period": params.rsi_period},
            "metrics": {"sharpeRatio": m.get("sharpeRatio"), "totalReturnPct": m.get("totalReturnPct"),
                        "maxDrawdownPct": m.get("maxDrawdownPct"), "winRatePct": m.get("winRatePct"),
                        "roundTripCount": m.get("roundTripCount")},
        })
    results.sort(key=lambda r: r["metrics"].get("sharpeRatio") or -999, reverse=True)
    return results[:top_n]


# ── Walk-Forward ─────────────────────────────────────────────────────

def run_walk_forward(
    bars: list[dict],
    params: MomentumParams,
    config: BacktestConfig | None = None,
    train_ratio: float = 0.7,
) -> dict[str, Any]:
    """Train/test split walk-forward validation."""
    n = len(bars)
    split = int(n * train_ratio)
    min_bars = params.long_p + 10
    if split < min_bars or n - split < min_bars:
        return {"error": "insufficient_data", "need": min_bars, "train": split, "test": n - split}
    train_result = run_momentum_backtest(bars[:split], params, config)
    test_result = run_momentum_backtest(bars[split:], params, config)
    return {
        "in_sample": {"bars": split, "metrics": train_result["metrics"]},
        "out_of_sample": {"bars": n - split, "metrics": test_result["metrics"]},
    }


# ── 反转策略回测 ─────────────────────────────────────────────────────

def run_reversal_long_only_backtest(
    bars: list[dict], params: ReversalParams, config: BacktestConfig | None = None,
) -> dict[str, Any]:
    """反转策略 Long-Only 回测。"""
    cfg = config or BacktestConfig()
    cost_factor = max(0.0, 1.0 - cfg.commission_rate - cfg.slippage_pct)
    min_len = max(params.rsi_period + 1, params.bb_period, params.ema_period) + 2
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    cash = 1.0
    shares = 0.0
    position_long = False
    cooldown_remaining = 0

    for i in range(len(bars)):
        t, price = bars[i]["t"], bars[i]["y"]
        eq_before = cash + shares * price

        if i + 1 < min_len:
            equity_curve.append({"t": t, "equity": round(eq_before, 6), "price": price})
            continue

        window = [float(b["y"]) for b in bars[: i + 1]]
        result = calc_reversal(window, params)
        sig = result["signal"] if result else "neutral"

        target_long = sig in ("strong_buy", "buy")

        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        elif target_long and not position_long and cash > 0 and price > 0:
            shares = cash * cost_factor / price
            cash = 0.0
            position_long = True
            cooldown_remaining = params.cooldown_bars
            trades.append({"action": "buy", "t": t, "price": round(price, 6), "signal": sig})
        elif not target_long and position_long and shares > 0 and price > 0:
            cash = shares * price * cost_factor
            trades.append({"action": "sell", "t": t, "price": round(price, 6), "signal": sig})
            shares = 0.0
            position_long = False
            cooldown_remaining = params.cooldown_bars

        eq = cash + shares * price
        equity_curve.append({"t": t, "equity": round(eq, 6), "price": price})

    metrics = _compute_metrics(equity_curve, trades, bars)
    if cfg.commission_rate > 0 or cfg.slippage_pct > 0:
        metrics["note"] = f"手续费{cfg.commission_rate*100:.3f}%/滑点{cfg.slippage_pct*100:.3f}%；" + metrics.get("note", "")
    return {"equity": equity_curve, "trades": trades, "metrics": metrics}


def run_reversal_long_short_backtest(
    bars: list[dict], params: ReversalParams, config: BacktestConfig | None = None,
) -> dict[str, Any]:
    """反转策略 Long-Short 回测。"""
    cfg = config or BacktestConfig()
    cost = max(0.0, 1.0 - cfg.commission_rate - cfg.slippage_pct)
    min_len = max(params.rsi_period + 1, params.bb_period, params.ema_period) + 2
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    pos = 0
    entry_p = 0.0
    capital = 1.0
    cooldown = 0

    for i in range(len(bars)):
        t, px = bars[i]["t"], float(bars[i]["y"])
        if pos == 1 and entry_p > 0:
            eq = capital * px / entry_p
        elif pos == -1 and entry_p > 0:
            eq = capital * max(0.0, 2.0 - px / entry_p)
        else:
            eq = capital

        if i + 1 < min_len:
            equity_curve.append({"t": t, "equity": round(eq, 6), "price": px})
            continue

        window = [float(b["y"]) for b in bars[: i + 1]]
        result = calc_reversal(window, params)
        sig = result["signal"] if result else "neutral"

        tgt = 1 if sig in ("strong_buy", "buy") else (-1 if sig in ("strong_sell", "sell") else 0)
        if cooldown > 0:
            cooldown -= 1
        elif tgt != pos and px > 0:
            if pos == 1 and entry_p > 0:
                capital *= (px / entry_p) * cost
                trades.append({"action": "sell", "t": t, "price": round(px, 6), "signal": sig})
            elif pos == -1 and entry_p > 0:
                capital *= max(0.0, 2.0 - px / entry_p) * cost
                trades.append({"action": "cover", "t": t, "price": round(px, 6), "signal": sig})
            if tgt != 0:
                capital *= cost
                entry_p = px
                trades.append({"action": "buy" if tgt == 1 else "short", "t": t, "price": round(px, 6), "signal": sig})
            else:
                entry_p = 0.0
            pos = tgt
            cooldown = params.cooldown_bars
            eq = capital
        equity_curve.append({"t": t, "equity": round(eq, 6), "price": px})

    metrics = _compute_metrics(equity_curve, trades, bars)
    metrics["mode"] = "long_short"
    cost_str = f"手续费{cfg.commission_rate*100:.3f}%/滑点{cfg.slippage_pct*100:.3f}%；" if (cfg.commission_rate > 0 or cfg.slippage_pct > 0) else "不计手续费与滑点；"
    metrics["note"] = f"反转 Long-Short，{cost_str}年化按首尾时间线性外推；夏普仅供参考。"
    return {"equity": equity_curve, "trades": trades, "metrics": metrics}


def run_reversal_backtest(
    bars: list[dict], params: ReversalParams, config: BacktestConfig | None = None,
) -> dict[str, Any]:
    cfg = config or BacktestConfig()
    if cfg.mode == "long_short":
        return run_reversal_long_short_backtest(bars, params, cfg)
    return run_reversal_long_only_backtest(bars, params, cfg)


def reversal_params_from_body(body: dict, symbol: str | None = None) -> ReversalParams:
    """从请求体和配置文件构建反转策略参数。"""
    config = RUNTIME_CONFIG.get("reversal") or {}
    defaults = config.get("default") if isinstance(config.get("default"), dict) else config

    _aliases = {"ag0": "huyin", "xag": "comex", "au0": "hujin", "xau": "comex_gold"}
    resolved = _aliases.get(symbol, symbol) if symbol else symbol

    symbol_config = {}
    if resolved and resolved in config and isinstance(config[resolved], dict):
        symbol_config = config[resolved]

    merged = {**defaults, **symbol_config}
    p = body.get("params") or {}

    return ReversalParams(
        rsi_period=int(p.get("rsi_period", merged.get("rsi_period", 14))),
        rsi_oversold=float(p.get("rsi_oversold", merged.get("rsi_oversold", 30.0))),
        rsi_overbought=float(p.get("rsi_overbought", merged.get("rsi_overbought", 70.0))),
        rsi_extreme_low=float(p.get("rsi_extreme_low", merged.get("rsi_extreme_low", 20.0))),
        rsi_extreme_high=float(p.get("rsi_extreme_high", merged.get("rsi_extreme_high", 80.0))),
        bb_period=int(p.get("bb_period", merged.get("bb_period", 20))),
        bb_mult=float(p.get("bb_mult", merged.get("bb_mult", 2.0))),
        pctb_low=float(p.get("pctb_low", merged.get("pctb_low", 0.05))),
        pctb_high=float(p.get("pctb_high", merged.get("pctb_high", 0.95))),
        pctb_extreme_low=float(p.get("pctb_extreme_low", merged.get("pctb_extreme_low", -0.05))),
        pctb_extreme_high=float(p.get("pctb_extreme_high", merged.get("pctb_extreme_high", 1.05))),
        ema_period=int(p.get("ema_period", merged.get("ema_period", 20))),
        deviation_entry=float(p.get("deviation_entry", merged.get("deviation_entry", 1.5))),
        deviation_strong=float(p.get("deviation_strong", merged.get("deviation_strong", 2.5))),
        rsi_weight=float(p.get("rsi_weight", merged.get("rsi_weight", 0.4))),
        bb_weight=float(p.get("bb_weight", merged.get("bb_weight", 0.35))),
        deviation_weight=float(p.get("deviation_weight", merged.get("deviation_weight", 0.25))),
        min_score=float(p.get("min_score", merged.get("min_score", 0.5))),
        strong_score=float(p.get("strong_score", merged.get("strong_score", 0.8))),
        cooldown_bars=int(p.get("cooldown_bars", merged.get("cooldown_bars", 2))),
    )
