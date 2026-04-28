"""COMEX 银 5 分钟窗口回测：基线 vs 优化对比（自定义全窗口扫描）。

变体：
- 基线（无止损 + RSI 70/30）
- v1 对齐 paper_trading（止损 0.15/止盈 0.30/移动止盈/60bar）
- v2 v1 + RSI 放宽 75/25
- v3 更紧止损 0.10/止盈 0.25 + RSI 75/25 + max_hold 90

直接调用 run_single_window_backtest 收集全部窗口结果（不限 top10）。
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# UTF-8 控制台输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.backtest import BacktestConfig
from backend.backtest_runner import run_single_window_backtest, _score_for_ranking
from backend.tick_storage import get_available_dates, get_ticks_for_date


DATES = ["2026-04-23", "2026-04-24", "2026-04-25", "2026-04-27"]
INSTRUMENT = "xag"
WINDOW_MS = 5 * 60 * 1000
STEP_MS = WINDOW_MS  # 非重叠 5min 窗口，贴近“5分钟级别”实盘复盘并控制耗时

BASE_PARAMS = {
    "short_p": 10, "long_p": 20,
    "spread_entry": 0.012, "spread_strong": 0.08,
    "slope_entry": 0.012,
    "strength_multiplier": 250,
    "cooldown_bars": 5,
    "bb_period": 20, "bb_mult": 2.0,
    "rsi_period": 10,
    "bb_buy_kill": 0.3, "bb_sell_kill": 0.7,
    "min_volatility_pct": 0.03,
    "volume_period": 0,  # 关闭成交量过滤，避免 tick volume 缺失
}

PARAM_GRID = {
    "spread_entry": [0.008, 0.012, 0.020],
    "slope_entry": [0.008, 0.012, 0.018],
}


def scan_all_windows(date_str: str, base_params: dict, bt_cfg: BacktestConfig) -> list[dict]:
    """对某日所有 5min 窗口跑参数网格回测，返回每个窗口的最佳指标。"""
    ticks = get_ticks_for_date(INSTRUMENT, date_str)
    if len(ticks) < 100:
        return []
    first_ts, last_ts = ticks[0]["t"], ticks[-1]["t"]
    windows = []
    start = first_ts
    while start + WINDOW_MS <= last_ts:
        windows.append((start, start + WINDOW_MS))
        start += STEP_MS

    out = []
    left = 0
    right = 0
    n_ticks = len(ticks)
    for w_start, w_end in windows:
        while left < n_ticks and ticks[left]["t"] < w_start:
            left += 1
        if right < left:
            right = left
        while right < n_ticks and ticks[right]["t"] <= w_end:
            right += 1
        wt = ticks[left:right]
        if len(wt) < 50:
            continue
        result = run_single_window_backtest(
            wt, strategy="momentum", base_params=base_params,
            param_grid=PARAM_GRID, bt_cfg=bt_cfg,
        )
        m = result["best_metrics"]
        if not m:
            continue
        out.append({
            "metrics": m,
            "score": _score_for_ranking(m),
            "best_params": result["best_params"],
            "start_ms": w_start,
            "end_ms": w_end,
        })
    return out


def aggregate(all_windows: list[dict]) -> dict:
    if not all_windows:
        return {"valid_windows": 0}
    n = len(all_windows)
    rets = [w["metrics"].get("totalReturnPct") or 0.0 for w in all_windows]
    dds = [w["metrics"].get("maxDrawdownPct") or 0.0 for w in all_windows]
    trades = [w["metrics"].get("roundTripCount") or 0 for w in all_windows]
    risk_exits = [w["metrics"].get("riskExitCount") or 0 for w in all_windows]
    wins = [w["metrics"].get("winRatePct") for w in all_windows if w["metrics"].get("winRatePct") is not None]
    pfs = [w["metrics"].get("profitFactor") for w in all_windows
           if isinstance(w["metrics"].get("profitFactor"), (int, float))]
    sharpes = [w["metrics"].get("sharpeRatio") for w in all_windows
               if isinstance(w["metrics"].get("sharpeRatio"), (int, float))]
    pos = sum(1 for r in rets if r > 0.001)
    neg = sum(1 for r in rets if r < -0.001)
    total_trades = sum(trades)
    windows_with_trades = sum(1 for t in trades if t > 0)
    total_ret_compound = 1.0
    for r in rets:
        total_ret_compound *= (1 + r / 100.0)
    total_ret_pct = (total_ret_compound - 1) * 100

    best_idx = max(range(n), key=lambda i: all_windows[i]["score"])
    best = all_windows[best_idx]
    worst_idx = min(range(n), key=lambda i: all_windows[i]["metrics"].get("totalReturnPct") or 0.0)
    worst = all_windows[worst_idx]

    return {
        "valid_windows": n,
        "windows_with_trades": windows_with_trades,
        "trade_rate_pct": round(windows_with_trades / n * 100, 2),
        "pos_windows": pos,
        "neg_windows": neg,
        "pos_rate_pct": round(pos / n * 100, 2),
        "avg_return_pct": round(sum(rets) / n, 4),
        "median_return_pct": round(sorted(rets)[n // 2], 4),
        "compound_return_pct": round(total_ret_pct, 3),
        "avg_max_drawdown_pct": round(sum(dds) / n, 4),
        "max_drawdown_pct": round(max(dds), 3) if dds else 0,
        "avg_trades_per_window": round(sum(trades) / n, 2),
        "total_trades": total_trades,
        "avg_risk_exits_per_window": round(sum(risk_exits) / n, 3),
        "total_risk_exits": sum(risk_exits),
        "avg_win_rate_pct": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_profit_factor": round(sum(pfs) / len(pfs), 2) if pfs else None,
        "avg_sharpe": round(sum(sharpes) / len(sharpes), 3) if sharpes else None,
        "best_window_return_pct": round(best["metrics"].get("totalReturnPct") or 0, 3),
        "worst_window_return_pct": round(worst["metrics"].get("totalReturnPct") or 0, 3),
    }


def run_variant(name: str, bt_cfg: BacktestConfig, base_params: dict) -> dict:
    print(f"\n{'=' * 80}")
    print(f"变体: {name}")
    print(f"  止损={bt_cfg.stop_loss_pct}% 止盈={bt_cfg.take_profit_pct}% "
          f"移动止盈={bt_cfg.trailing_trigger_pct}/{bt_cfg.trailing_retracement_pct}% "
          f"max_hold={bt_cfg.max_hold_bars}bar")
    print(f"  RSI buy_kill={base_params.get('rsi_buy_kill', 70)} "
          f"sell_kill={base_params.get('rsi_sell_kill', 30)}")
    print(f"{'=' * 80}")

    all_windows = []
    for d in DATES:
        wins = scan_all_windows(d, base_params, bt_cfg)
        print(f"  {d}: {len(wins)} 窗口")
        all_windows.extend(wins)

    summary = aggregate(all_windows)
    return {"variant": name, "summary": summary}


def main():
    available = get_available_dates(INSTRUMENT)
    print(f"可用日期: {available}")

    base = dict(BASE_PARAMS)
    base_relaxed = dict(BASE_PARAMS, rsi_buy_kill=75.0, rsi_sell_kill=25.0)

    cfg_baseline = BacktestConfig()
    cfg_v1 = BacktestConfig(
        stop_loss_pct=0.15, take_profit_pct=0.30,
        trailing_trigger_pct=0.10, trailing_retracement_pct=0.05,
        max_hold_bars=60,
    )
    cfg_v2 = BacktestConfig(
        stop_loss_pct=0.15, take_profit_pct=0.30,
        trailing_trigger_pct=0.10, trailing_retracement_pct=0.05,
        max_hold_bars=60,
    )
    cfg_v3 = BacktestConfig(
        stop_loss_pct=0.10, take_profit_pct=0.25,
        trailing_trigger_pct=0.08, trailing_retracement_pct=0.04,
        max_hold_bars=90,
    )
    cfg_v4 = BacktestConfig(
        stop_loss_pct=0.20, take_profit_pct=0.50,
        trailing_trigger_pct=0.20, trailing_retracement_pct=0.10,
        max_hold_bars=120,
    )
    cfg_v5 = BacktestConfig(
        max_hold_bars=90,
    )
    cfg_v6 = BacktestConfig(
        stop_loss_pct=0.20,
        max_hold_bars=120,
    )
    base_very_relaxed = dict(BASE_PARAMS, rsi_buy_kill=80.0, rsi_sell_kill=20.0)

    results = []
    results.append(run_variant("baseline (no SL/TP, RSI 70/30)", cfg_baseline, base))
    results.append(run_variant("v1 align paper (SL0.15/TP0.30/60bar)", cfg_v1, base))
    results.append(run_variant("v2 v1 + RSI 75/25", cfg_v2, base_relaxed))
    results.append(run_variant("v3 tighter SL0.10/TP0.25/90bar + RSI 75/25", cfg_v3, base_relaxed))
    results.append(run_variant("v4 wider SL0.20/TP0.50/120bar + RSI 75/25", cfg_v4, base_relaxed))
    results.append(run_variant("v5 time stop only 90bar + RSI 75/25", cfg_v5, base_relaxed))
    results.append(run_variant("v6 SL0.20 only/120bar + RSI 75/25", cfg_v6, base_relaxed))
    results.append(run_variant("v7 no SL/TP + RSI 80/20", cfg_baseline, base_very_relaxed))

    # 对比表
    print("\n" + "=" * 130)
    print("绩效对比汇总（4 天 tick 数据，非重叠 5 分钟窗口，9 组参数网格）")
    print("=" * 130)
    cols = ["变体", "窗口", "有交易%", "正收益%", "平均收益%", "复利%", "最大回撤", "胜率%", "PF", "Sharpe", "风控/窗", "最佳", "最差"]
    fmt = "{:<46} {:>5} {:>7} {:>7} {:>10} {:>9} {:>9} {:>7} {:>6} {:>7} {:>8} {:>7} {:>7}"
    print(fmt.format(*cols))
    print("-" * 130)
    for r in results:
        s = r["summary"]
        if s.get("valid_windows", 0) == 0:
            print(f"{r['variant']:<46} 无有效窗口")
            continue
        print(fmt.format(
            r["variant"][:46],
            s["valid_windows"],
            s["trade_rate_pct"],
            s["pos_rate_pct"],
            s["avg_return_pct"],
            s["compound_return_pct"],
            s["avg_max_drawdown_pct"],
            s["avg_win_rate_pct"] or 0,
            s["avg_profit_factor"] or 0,
            s["avg_sharpe"] or 0,
            s["avg_risk_exits_per_window"],
            s["best_window_return_pct"],
            s["worst_window_return_pct"],
        ))
    print("=" * 130)

    out_path = Path(__file__).parent.parent / "backtest_xag_5min_compare.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存到 {out_path}")


if __name__ == "__main__":
    main()
