"""COMEX 银秒级高频策略验证（1 分钟内 tick 级动量）。

方案要点：
- 数据：`data/ticks.db` 中 xag 全部历史日期；每条 tick 作为一个 bar（中位 ≈1.7s）。
- 窗口：非重叠 5 分钟，窗口内做参数网格回测。
- 变体：6 组风控 × RSI 组合，涵盖无止损基线、紧止损、宽止损、纯移动止盈、纯时间止损、RSI 放宽。
- 网格：`short_p × long_p × spread_entry × slope_entry`，追求秒级量级。
- 输出：控制台绩效对比表 + `backtest_xag_scalping.json`（含变体汇总与 Top20 窗口 equity/trades）。

运行：
    python tests/_run_xag_scalping.py
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.backtest import BacktestConfig
from backend.backtest_runner import _score_for_ranking, run_single_window_backtest
from backend.tick_storage import get_available_dates, get_ticks_for_date


INSTRUMENT = "xag"
WINDOW_MS = 5 * 60 * 1000           # 5 分钟窗口
STEP_MS = WINDOW_MS                 # 非重叠
MIN_TICKS_PER_WINDOW = 80           # 5 分钟 ≥80 tick 才有意义
OUTLIER_MIN_MS = 1_500_000_000_000  # 过滤掉 t < 2017-07-14 的脏点
TOP_N = 20

# ── 秒级基础参数（每 tick 即 1 bar；short_p=5 → 约 8s 滤波）
BASE_PARAMS: dict = {
    "short_p": 5,
    "long_p": 13,
    "spread_entry": 0.006,
    "spread_strong": 0.03,
    "slope_entry": 0.006,
    "strength_multiplier": 250,
    "cooldown_bars": 2,
    "bb_period": 20,
    "bb_mult": 2.0,
    "rsi_period": 7,
    "bb_buy_kill": 0.3,
    "bb_sell_kill": 0.7,
    "min_volatility_pct": 0.01,
    "volume_period": 0,
    "rsi_buy_kill": 70.0,
    "rsi_sell_kill": 30.0,
}

# ── 参数网格：每窗口枚举（3×3×3=27 次回测/窗口；加 long-short 模式则 ×2）
PARAM_GRID: dict[str, list] = {
    "short_p": [3, 5, 8],
    "spread_entry": [0.003, 0.006, 0.012],
    "slope_entry": [0.003, 0.006, 0.012],
}


def _filter_valid_ticks(ticks: list[dict]) -> list[dict]:
    return [t for t in ticks if t.get("t", 0) >= OUTLIER_MIN_MS and t.get("y")]


def _iter_windows(ticks: list[dict]) -> list[tuple[int, int]]:
    if not ticks:
        return []
    first, last = ticks[0]["t"], ticks[-1]["t"]
    out = []
    s = first
    while s + WINDOW_MS <= last:
        out.append((s, s + WINDOW_MS))
        s += STEP_MS
    return out


def _slice_window(ticks: list[dict], w_start: int, w_end: int,
                  cursor: list[int]) -> list[dict]:
    """利用 cursor 记忆推进位置，O(n) 切片。"""
    left, right = cursor
    n = len(ticks)
    while left < n and ticks[left]["t"] < w_start:
        left += 1
    if right < left:
        right = left
    while right < n and ticks[right]["t"] <= w_end:
        right += 1
    cursor[0], cursor[1] = left, right
    return ticks[left:right]


def scan_variant(variant: dict, ticks_by_date: dict[str, list[dict]]) -> dict:
    """对所有日期 × 所有 5min 窗口跑该变体的参数网格回测。"""
    cfg: BacktestConfig = variant["cfg"]
    base_params: dict = variant["base_params"]
    mode_label = "long_short" if cfg.mode == "long_short" else "long_only"

    print(f"\n{'=' * 96}")
    print(f"变体: {variant['name']} [{mode_label}]")
    print(f"  SL={cfg.stop_loss_pct:.3f}% TP={cfg.take_profit_pct:.3f}% "
          f"Trail={cfg.trailing_trigger_pct:.3f}/{cfg.trailing_retracement_pct:.3f}% "
          f"maxHold={cfg.max_hold_bars}bar  "
          f"RSIkill={base_params['rsi_buy_kill']:.0f}/{base_params['rsi_sell_kill']:.0f}")
    print("=" * 96)

    all_windows: list[dict] = []
    for date_str, ticks in ticks_by_date.items():
        wins = _iter_windows(ticks)
        cursor = [0, 0]
        day_hits = 0
        for w_start, w_end in wins:
            wt = _slice_window(ticks, w_start, w_end, cursor)
            if len(wt) < MIN_TICKS_PER_WINDOW:
                continue
            res = run_single_window_backtest(
                wt, strategy="momentum",
                base_params=base_params,
                param_grid=PARAM_GRID,
                bt_cfg=cfg,
            )
            m = res["best_metrics"]
            if not m:
                continue
            all_windows.append({
                "date": date_str,
                "start_ms": w_start,
                "end_ms": w_end,
                "tick_count": len(wt),
                "best_params": res["best_params"],
                "best_metrics": m,
                "score": _score_for_ranking(m),
                "equity": res.get("equity", []),
                "trades": res.get("trades", []),
            })
            day_hits += 1
        print(f"  {date_str}: 窗口回测 {day_hits} 个")

    summary = _aggregate(all_windows)
    top = sorted(all_windows, key=lambda x: x["score"], reverse=True)[:TOP_N]
    return {
        "variant": variant["name"],
        "mode": mode_label,
        "bt_cfg": {
            "stop_loss_pct": cfg.stop_loss_pct,
            "take_profit_pct": cfg.take_profit_pct,
            "trailing_trigger_pct": cfg.trailing_trigger_pct,
            "trailing_retracement_pct": cfg.trailing_retracement_pct,
            "max_hold_bars": cfg.max_hold_bars,
        },
        "base_params": base_params,
        "summary": summary,
        "top_windows": [
            {
                "date": w["date"],
                "start_ms": w["start_ms"],
                "end_ms": w["end_ms"],
                "tick_count": w["tick_count"],
                "best_params": w["best_params"],
                "best_metrics": w["best_metrics"],
                "score": round(w["score"], 4),
                "equity_len": len(w["equity"]),
                "trade_count": len(w["trades"]),
            }
            for w in top
        ],
    }


def _aggregate(all_windows: list[dict]) -> dict:
    n = len(all_windows)
    if n == 0:
        return {"valid_windows": 0}
    rets = [w["best_metrics"].get("totalReturnPct") or 0.0 for w in all_windows]
    dds = [w["best_metrics"].get("maxDrawdownPct") or 0.0 for w in all_windows]
    trades = [w["best_metrics"].get("roundTripCount") or 0 for w in all_windows]
    risk_exits = [w["best_metrics"].get("riskExitCount") or 0 for w in all_windows]
    wins = [w["best_metrics"].get("winRatePct") for w in all_windows
            if w["best_metrics"].get("winRatePct") is not None]
    pfs = [w["best_metrics"].get("profitFactor") for w in all_windows
           if isinstance(w["best_metrics"].get("profitFactor"), (int, float))]
    sharpes = [w["best_metrics"].get("sharpeRatio") for w in all_windows
               if isinstance(w["best_metrics"].get("sharpeRatio"), (int, float))]
    pos = sum(1 for r in rets if r > 0.001)
    neg = sum(1 for r in rets if r < -0.001)
    total_trades = sum(trades)
    windows_with_trades = sum(1 for t in trades if t > 0)

    compound = 1.0
    for r in rets:
        compound *= (1 + r / 100.0)
    compound_pct = (compound - 1) * 100

    # 逐日复利（只看该变体表现的时间分布）
    by_day: dict[str, list[float]] = {}
    for w in all_windows:
        by_day.setdefault(w["date"], []).append(w["best_metrics"].get("totalReturnPct") or 0.0)
    daily_compound = {}
    worst_day_compound = 0.0
    for d, lst in by_day.items():
        c = 1.0
        for r in lst:
            c *= (1 + r / 100.0)
        pct = (c - 1) * 100
        daily_compound[d] = round(pct, 3)
        worst_day_compound = min(worst_day_compound, pct)

    return {
        "valid_windows": n,
        "windows_with_trades": windows_with_trades,
        "trade_rate_pct": round(windows_with_trades / n * 100, 2),
        "pos_windows": pos,
        "neg_windows": neg,
        "pos_rate_pct": round(pos / n * 100, 2),
        "avg_return_pct": round(sum(rets) / n, 4),
        "median_return_pct": round(sorted(rets)[n // 2], 4),
        "compound_return_pct": round(compound_pct, 3),
        "avg_max_drawdown_pct": round(sum(dds) / n, 4),
        "max_drawdown_pct": round(max(dds), 3) if dds else 0,
        "avg_trades_per_window": round(sum(trades) / n, 2),
        "total_trades": total_trades,
        "avg_risk_exits_per_window": round(sum(risk_exits) / n, 3),
        "total_risk_exits": sum(risk_exits),
        "avg_win_rate_pct": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_profit_factor": round(sum(pfs) / len(pfs), 2) if pfs else None,
        "avg_sharpe": round(sum(sharpes) / len(sharpes), 3) if sharpes else None,
        "best_window_return_pct": round(max(rets), 3),
        "worst_window_return_pct": round(min(rets), 3),
        "daily_compound_pct": daily_compound,
        "worst_day_compound_pct": round(worst_day_compound, 3),
    }


def _cfg(mode="long_only", comm=0.0005, slip=0.0002, **kw) -> BacktestConfig:
    return BacktestConfig(mode=mode, commission_rate=comm, slippage_pct=slip, **kw)


def build_variants() -> list[dict]:
    base = dict(BASE_PARAMS)
    base_rsi75 = dict(BASE_PARAMS, rsi_buy_kill=75.0, rsi_sell_kill=25.0)
    base_rsi80 = dict(BASE_PARAMS, rsi_buy_kill=80.0, rsi_sell_kill=20.0)

    # CME micro silver tick 成本经验值：佣金+滑点≈每边 0.002%（round-trip 0.004%）
    FUT_COMM = 0.00002   # 0.002% 每边
    FUT_SLIP = 0.00002

    return [
        {
            "name": "V0 baseline (无止损, RSI 70/30)",
            "cfg": BacktestConfig(mode="long_only"),
            "base_params": base,
        },
        {
            "name": "V1 紧止损 (SL0.05/TP0.10/maxHold20, RSI 75/25)",
            "cfg": BacktestConfig(
                mode="long_only",
                stop_loss_pct=0.05, take_profit_pct=0.10,
                trailing_trigger_pct=0.04, trailing_retracement_pct=0.02,
                max_hold_bars=20,
            ),
            "base_params": base_rsi75,
        },
        {
            "name": "V2 中止损 (SL0.08/TP0.16/maxHold35, RSI 75/25)",
            "cfg": BacktestConfig(
                mode="long_only",
                stop_loss_pct=0.08, take_profit_pct=0.16,
                trailing_trigger_pct=0.06, trailing_retracement_pct=0.03,
                max_hold_bars=35,
            ),
            "base_params": base_rsi75,
        },
        {
            "name": "V3 纯移动止盈 (trail 0.05/0.025, maxHold35, RSI 75/25)",
            "cfg": BacktestConfig(
                mode="long_only",
                trailing_trigger_pct=0.05, trailing_retracement_pct=0.025,
                max_hold_bars=35,
            ),
            "base_params": base_rsi75,
        },
        {
            "name": "V4 纯时间止损 (maxHold20, RSI 80/20)",
            "cfg": BacktestConfig(
                mode="long_only",
                max_hold_bars=20,
            ),
            "base_params": base_rsi80,
        },
        {
            "name": "V5 Long-Short 中止损 (SL0.08/TP0.16/maxHold35, RSI 75/25)",
            "cfg": BacktestConfig(
                mode="long_short",
                stop_loss_pct=0.08, take_profit_pct=0.16,
                trailing_trigger_pct=0.06, trailing_retracement_pct=0.03,
                max_hold_bars=35,
            ),
            "base_params": base_rsi75,
        },
        # ── 成本敏感性（CME 期货实际成本 ≈ 0.002%/边）
        {
            "name": "V6 零成本基线 (无止损, RSI 75/25, 纯信号)",
            "cfg": _cfg(comm=0.0, slip=0.0),
            "base_params": base_rsi75,
        },
        {
            "name": "V7 期货成本 (SL0.05/TP0.10/maxHold20, RSI 75/25)",
            "cfg": _cfg(
                comm=FUT_COMM, slip=FUT_SLIP,
                stop_loss_pct=0.05, take_profit_pct=0.10,
                trailing_trigger_pct=0.04, trailing_retracement_pct=0.02,
                max_hold_bars=20,
            ),
            "base_params": base_rsi75,
        },
        {
            "name": "V8 期货成本 (SL0.08/TP0.16/maxHold35, RSI 75/25)",
            "cfg": _cfg(
                comm=FUT_COMM, slip=FUT_SLIP,
                stop_loss_pct=0.08, take_profit_pct=0.16,
                trailing_trigger_pct=0.06, trailing_retracement_pct=0.03,
                max_hold_bars=35,
            ),
            "base_params": base_rsi75,
        },
        {
            "name": "V9 期货成本 long-short (SL0.08/TP0.16/maxHold35, RSI 75/25)",
            "cfg": _cfg(
                mode="long_short",
                comm=FUT_COMM, slip=FUT_SLIP,
                stop_loss_pct=0.08, take_profit_pct=0.16,
                trailing_trigger_pct=0.06, trailing_retracement_pct=0.03,
                max_hold_bars=35,
            ),
            "base_params": base_rsi75,
        },
    ]


def main() -> None:
    t0 = time.time()
    dates = get_available_dates(INSTRUMENT)
    print(f"可用日期: {dates}")

    ticks_by_date: dict[str, list[dict]] = {}
    for d in dates:
        raw = get_ticks_for_date(INSTRUMENT, d)
        clean = _filter_valid_ticks(raw)
        if len(clean) >= MIN_TICKS_PER_WINDOW:
            ticks_by_date[d] = clean
        print(f"  {d}: raw={len(raw)} clean={len(clean)}")

    variants = build_variants()
    results = []
    for v in variants:
        results.append(scan_variant(v, ticks_by_date))

    # ── 绩效汇总表
    print("\n" + "=" * 150)
    print(f"COMEX 银秒级高频策略绩效对比（日期数={len(ticks_by_date)}，非重叠 5min 窗口，每窗口 27 组参数网格）")
    print("=" * 150)
    header = ["变体", "模式", "窗口", "有交易%", "正收益%", "均收益%", "中位%", "复利%",
              "均回撤", "最大回撤", "胜率%", "PF", "Sharpe", "风控/窗", "最佳窗", "最差窗", "最差日复利%"]
    fmt = "{:<46} {:<10} {:>5} {:>7} {:>7} {:>8} {:>7} {:>8} {:>7} {:>8} {:>6} {:>5} {:>7} {:>8} {:>7} {:>7} {:>9}"
    print(fmt.format(*header))
    print("-" * 150)
    for r in results:
        s = r["summary"]
        if s.get("valid_windows", 0) == 0:
            print(f"{r['variant']:<46} 无有效窗口")
            continue
        print(fmt.format(
            r["variant"][:46],
            r["mode"],
            s["valid_windows"],
            s["trade_rate_pct"],
            s["pos_rate_pct"],
            s["avg_return_pct"],
            s["median_return_pct"],
            s["compound_return_pct"],
            s["avg_max_drawdown_pct"],
            s["max_drawdown_pct"],
            s["avg_win_rate_pct"] or 0,
            s["avg_profit_factor"] or 0,
            s["avg_sharpe"] or 0,
            s["avg_risk_exits_per_window"],
            s["best_window_return_pct"],
            s["worst_window_return_pct"],
            s["worst_day_compound_pct"],
        ))
    print("=" * 150)

    # ── 验收评估
    print("\n验收门槛: 正收益窗口率 ≥55% && 胜率 ≥52% && PF ≥1.3 && 复利>0 && 最差日复利 ≥ -2%")
    passed = []
    for r in results:
        s = r["summary"]
        if s.get("valid_windows", 0) == 0:
            continue
        cond = (
            (s.get("pos_rate_pct") or 0) >= 55.0
            and (s.get("avg_win_rate_pct") or 0) >= 52.0
            and (s.get("avg_profit_factor") or 0) >= 1.3
            and (s.get("compound_return_pct") or 0) > 0
            and (s.get("worst_day_compound_pct") or 0) >= -2.0
        )
        mark = "[PASS]" if cond else "[FAIL]"
        print(f"  {mark} {r['variant']}")
        if cond:
            passed.append(r)

    out_path = Path(__file__).resolve().parent.parent / "backtest_xag_scalping.json"
    payload = {
        "meta": {
            "instrument": INSTRUMENT,
            "dates": list(ticks_by_date.keys()),
            "window_ms": WINDOW_MS,
            "step_ms": STEP_MS,
            "min_ticks_per_window": MIN_TICKS_PER_WINDOW,
            "param_grid": PARAM_GRID,
            "base_params": BASE_PARAMS,
            "elapsed_sec": round(time.time() - t0, 2),
        },
        "results": results,
        "passed_variants": [r["variant"] for r in passed],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存到 {out_path}")
    print(f"总耗时 {payload['meta']['elapsed_sec']} 秒")


if __name__ == "__main__":
    main()
