#!/usr/bin/env python3
"""
COMEX银(XAG) 最近5分钟 tick 数据回测分析
使用本地 ticks.db 中的 Infoway tick 数据
对比动量策略 vs 反转策略的短周期绩效
"""

import sqlite3
import time
import json
import math
import sys
from datetime import datetime, timezone
from itertools import product

sys.path.insert(0, '.')

from backend.strategies.momentum import MomentumParams, calc_momentum
from backend.strategies.reversal import ReversalParams, calc_reversal
from backend.backtest import (
    run_momentum_backtest,
    run_reversal_backtest,
    BacktestConfig,
    _compute_metrics,
)


def load_latest_5min_ticks(instrument_id: str = "xag") -> list[dict]:
    """从 ticks.db 加载指定品种最近的5分钟 tick 数据。"""
    conn = sqlite3.connect("data/ticks.db")
    cur = conn.execute("SELECT MAX(timestamp_ms) FROM ticks WHERE instrument_id = ?", (instrument_id,))
    max_ts = cur.fetchone()[0]
    if not max_ts:
        print("No tick data found for", instrument_id)
        sys.exit(1)
    start_ms = max_ts - 5 * 60 * 1000
    cur = conn.execute(
        "SELECT timestamp_ms, price FROM ticks WHERE instrument_id = ? AND timestamp_ms >= ? AND timestamp_ms <= ? ORDER BY timestamp_ms",
        (instrument_id, start_ms, max_ts),
    )
    rows = cur.fetchall()
    conn.close()
    bars = [{"t": int(r[0]), "y": float(r[1])} for r in rows]
    return bars, max_ts


def bars_to_1s(bars: list[dict]) -> list[dict]:
    """将 tick 序列按 1 秒聚合为 bar（取该秒最后一个价）。"""
    if not bars:
        return []
    grouped = {}
    for b in bars:
        sec = b["t"] // 1000
        grouped[sec] = b  # 后面的覆盖前面的，即取最后一价
    out = [{"t": sec * 1000, "y": b["y"]} for sec, b in sorted(grouped.items())]
    return out


def print_metrics(metrics: dict, label: str):
    print(f"\n=== {label} ===")
    for k, v in metrics.items():
        if k == "note":
            continue
        print(f"  {k}: {v}")
    if metrics.get("note"):
        print(f"  note: {metrics['note']}")


def grid_search_momentum(bars: list[dict], top_n: int = 5) -> list[dict]:
    """对动量策略做参数网格搜索，返回 top N 参数组合。"""
    grid = {
        "short_p": [3, 5, 8],
        "long_p": [10, 15, 20],
        "spread_entry": [0.01, 0.02, 0.03, 0.05],
        "slope_entry": [0.005, 0.01, 0.015],
        "cooldown_bars": [0, 1, 2],
    }
    names = sorted(grid.keys())
    combos = list(product(*(grid[k] for k in names)))
    results = []
    config = BacktestConfig(mode="long_only")
    for combo in combos:
        override = dict(zip(names, combo))
        if override.get("long_p", 20) <= override.get("short_p", 5):
            continue
        params = MomentumParams(
            short_p=int(override.get("short_p", 5)),
            long_p=int(override.get("long_p", 20)),
            spread_entry=float(override.get("spread_entry", 0.02)),
            spread_strong=float(override.get("spread_strong", override.get("spread_entry", 0.02) * 2.5)),
            slope_entry=float(override.get("slope_entry", 0.01)),
            cooldown_bars=int(override.get("cooldown_bars", 0)),
            bb_period=5,
            bb_mult=2.0,
            rsi_period=5,
        )
        result = run_momentum_backtest(bars, params, config)
        m = result.get("metrics", {})
        results.append({
            "params": override,
            "metrics": m,
            "trades": result.get("trades", []),
            "equity": result.get("equity", []),
        })
    # 排序：优先总收益，其次夏普（若存在），再其次胜率
    results.sort(key=lambda r: (
        r["metrics"].get("totalReturnPct", -999),
        r["metrics"].get("winRatePct", 0) or 0,
    ), reverse=True)
    return results[:top_n]


def grid_search_reversal(bars: list[dict], top_n: int = 5) -> list[dict]:
    """对反转策略做参数网格搜索，返回 top N 参数组合。"""
    grid = {
        "rsi_period": [5, 8, 10, 14],
        "rsi_oversold": [25, 30, 35],
        "rsi_overbought": [65, 70, 75],
        "deviation_entry": [0.1, 0.15, 0.2, 0.3],
        "min_score": [0.3, 0.4, 0.5],
        "cooldown_bars": [0, 1, 2],
    }
    names = sorted(grid.keys())
    combos = list(product(*(grid[k] for k in names)))
    results = []
    config = BacktestConfig(mode="long_only")
    for combo in combos:
        override = dict(zip(names, combo))
        params = ReversalParams(
            rsi_period=int(override.get("rsi_period", 5)),
            rsi_oversold=float(override.get("rsi_oversold", 30)),
            rsi_overbought=float(override.get("rsi_overbought", 70)),
            rsi_extreme_low=20,
            rsi_extreme_high=80,
            bb_period=5,
            bb_mult=2.0,
            ema_period=5,
            deviation_entry=float(override.get("deviation_entry", 0.15)),
            deviation_strong=float(override.get("deviation_entry", 0.15)) * 2.5,
            min_score=float(override.get("min_score", 0.4)),
            strong_score=0.8,
            cooldown_bars=int(override.get("cooldown_bars", 1)),
        )
        result = run_reversal_backtest(bars, params, config)
        m = result.get("metrics", {})
        results.append({
            "params": override,
            "metrics": m,
            "trades": result.get("trades", []),
            "equity": result.get("equity", []),
        })
    results.sort(key=lambda r: (
        r["metrics"].get("totalReturnPct", -999),
        r["metrics"].get("winRatePct", 0) or 0,
    ), reverse=True)
    return results[:top_n]


def analyze_signal_distribution(bars: list[dict]):
    """统计动量和反转策略的逐 bar 信号分布。"""
    mom_rt_params = MomentumParams(
        short_p=5, long_p=15, spread_entry=0.03, spread_strong=0.08,
        slope_entry=0.015, cooldown_bars=2, bb_period=10, bb_mult=2.0,
        rsi_period=10, bb_buy_kill=0.3, bb_sell_kill=0.7,
    )
    rev_rt_params = ReversalParams(
        rsi_period=5, rsi_oversold=28, rsi_overbought=72,
        deviation_entry=0.15, deviation_strong=0.4,
        bb_period=5, ema_period=5, min_score=0.35, strong_score=0.65,
        cooldown_bars=1,
    )

    mom_signals = []
    rev_signals = []
    prices = [b["y"] for b in bars]
    for i in range(len(bars)):
        window = prices[: i + 1]
        m = calc_momentum(window, mom_rt_params)
        r = calc_reversal(window, rev_rt_params)
        mom_signals.append(m["signal"] if m else "wait")
        rev_signals.append(r["signal"] if r else "wait")

    from collections import Counter
    print("\n--- 动量策略信号分布 ---")
    for sig, cnt in Counter(mom_signals).most_common():
        print(f"  {sig}: {cnt} ({cnt/len(mom_signals)*100:.1f}%)")
    print("\n--- 反转策略信号分布 ---")
    for sig, cnt in Counter(rev_signals).most_common():
        print(f"  {sig}: {cnt} ({cnt/len(rev_signals)*100:.1f}%)")

    # 检查信号一致性
    agree = sum(1 for m, r in zip(mom_signals, rev_signals) if m == r)
    opp = sum(1 for m, r in zip(mom_signals, rev_signals)
              if (m in ("buy", "strong_buy") and r in ("sell", "strong_sell")) or
                 (m in ("sell", "strong_sell") and r in ("buy", "strong_buy")))
    print(f"\n信号一致性: {agree}/{len(mom_signals)} ({agree/len(mom_signals)*100:.1f}%)")
    print(f"信号反向: {opp}/{len(mom_signals)} ({opp/len(mom_signals)*100:.1f}%)")


def main():
    bars_raw, max_ts = load_latest_5min_ticks("xag")
    dt_end = datetime.fromtimestamp(max_ts / 1000, tz=timezone.utc).astimezone()
    dt_start = datetime.fromtimestamp((max_ts - 5 * 60 * 1000) / 1000, tz=timezone.utc).astimezone()
    print(f"COMEX银 (XAG) 5分钟 tick 回测")
    print(f"时间窗口: {dt_start.strftime('%Y-%m-%d %H:%M:%S')} ~ {dt_end.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"原始 tick 数: {len(bars_raw)}")

    # 按1秒聚合
    bars = bars_to_1s(bars_raw)
    print(f"聚合为 1s bars: {len(bars)}")
    if len(bars) < 30:
        print("数据不足，无法回测")
        return

    prices = [b["y"] for b in bars]
    print(f"价格范围: {min(prices):.3f} ~ {max(prices):.3f}")
    print(f"首尾价格: {prices[0]:.3f} -> {prices[-1]:.3f} (净变化 {prices[-1]-prices[0]:.3f})")

    # --- 动量策略回测（realtime 参数）---
    mom_rt_params = MomentumParams(
        short_p=5, long_p=15, spread_entry=0.03, spread_strong=0.08,
        slope_entry=0.015, cooldown_bars=2, bb_period=10, bb_mult=2.0,
        rsi_period=10, bb_buy_kill=0.3, bb_sell_kill=0.7,
    )
    mom_rt_result = run_momentum_backtest(bars, mom_rt_params, BacktestConfig(mode="long_only"))
    print_metrics(mom_rt_result["metrics"], "动量策略 (Realtime 参数)")

    # 动量 Long-Short
    mom_ls_result = run_momentum_backtest(bars, mom_rt_params, BacktestConfig(mode="long_short"))
    print_metrics(mom_ls_result["metrics"], "动量策略 Long-Short (Realtime 参数)")

    # --- 反转策略回测（realtime 参数）---
    rev_rt_params = ReversalParams(
        rsi_period=5, rsi_oversold=28, rsi_overbought=72,
        deviation_entry=0.15, deviation_strong=0.4,
        bb_period=5, ema_period=5, min_score=0.35, strong_score=0.65,
        cooldown_bars=1,
    )
    rev_rt_result = run_reversal_backtest(bars, rev_rt_params, BacktestConfig(mode="long_only"))
    print_metrics(rev_rt_result["metrics"], "反转策略 (Realtime 参数)")

    rev_ls_result = run_reversal_backtest(bars, rev_rt_params, BacktestConfig(mode="long_short"))
    print_metrics(rev_ls_result["metrics"], "反转策略 Long-Short (Realtime 参数)")

    # --- 带成本的回测 ---
    config_cost = BacktestConfig(mode="long_only", commission_rate=0.0005, slippage_pct=0.0002)
    mom_cost = run_momentum_backtest(bars, mom_rt_params, config_cost)
    rev_cost = run_reversal_backtest(bars, rev_rt_params, config_cost)
    print_metrics(mom_cost["metrics"], "动量策略 (手续费0.05% + 滑点0.02%)")
    print_metrics(rev_cost["metrics"], "反转策略 (手续费0.05% + 滑点0.02%)")

    # --- 信号分布分析 ---
    analyze_signal_distribution(bars)

    # --- 网格搜索 ---
    print("\n\n========== 动量策略参数网格搜索 (Top 5) ==========")
    mom_best = grid_search_momentum(bars, top_n=5)
    for i, r in enumerate(mom_best, 1):
        print(f"\nRank {i}: params={r['params']}")
        m = r["metrics"]
        print(f"  总收益: {m.get('totalReturnPct')}% | 回撤: {m.get('maxDrawdownPct')}% | "
              f"胜率: {m.get('winRatePct')}% | 交易次数: {m.get('roundTripCount')} | "
              f"平均持仓bars: {m.get('avgHoldingBars')}")

    print("\n\n========== 反转策略参数网格搜索 (Top 5) ==========")
    rev_best = grid_search_reversal(bars, top_n=5)
    for i, r in enumerate(rev_best, 1):
        print(f"\nRank {i}: params={r['params']}")
        m = r["metrics"]
        print(f"  总收益: {m.get('totalReturnPct')}% | 回撤: {m.get('maxDrawdownPct')}% | "
              f"胜率: {m.get('winRatePct')}% | 交易次数: {m.get('roundTripCount')} | "
              f"平均持仓bars: {m.get('avgHoldingBars')}")

    # --- 保存结果 ---
    report = {
        "instrument": "xag",
        "window_start": dt_start.strftime("%Y-%m-%d %H:%M:%S"),
        "window_end": dt_end.strftime("%Y-%m-%d %H:%M:%S"),
        "bars": len(bars),
        "momentum": {
            "default_rt": mom_rt_result["metrics"],
            "long_short": mom_ls_result["metrics"],
            "with_cost": mom_cost["metrics"],
            "top_params": [{"params": r["params"], "metrics": r["metrics"]} for r in mom_best],
        },
        "reversal": {
            "default_rt": rev_rt_result["metrics"],
            "long_short": rev_ls_result["metrics"],
            "with_cost": rev_cost["metrics"],
            "top_params": [{"params": r["params"], "metrics": r["metrics"]} for r in rev_best],
        },
    }
    with open("backtest_5min_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n\n报告已保存至 backtest_5min_report.json")


if __name__ == "__main__":
    main()
