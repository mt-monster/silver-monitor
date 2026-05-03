"""固定参数 OOS 验证：用 Top 变体在全部 5min 窗口上跑单一参数，消除 per-window grid 的看未来偏差。

挑选依据：`backtest_xag_scalping.json` 中 V6/V7/V8/V9 的 top-20 modal 参数组合。
每组变体选 3 个候选参数配置独立评估；得分口径与主脚本一致。
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
from backend.backtest_runner import run_single_window_backtest
from backend.tick_storage import get_available_dates, get_ticks_for_date

INSTRUMENT = "xag"
WINDOW_MS = 5 * 60 * 1000
MIN_TICKS = 80
OUTLIER_MIN_MS = 1_500_000_000_000


def _iter_windows(ticks):
    if not ticks:
        return []
    first, last = ticks[0]["t"], ticks[-1]["t"]
    out, s = [], first
    while s + WINDOW_MS <= last:
        out.append((s, s + WINDOW_MS))
        s += WINDOW_MS
    return out


def _slice(ticks, w_start, w_end, cursor):
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


# 从 inspect 结果挑出的候选（short_p, spread_entry, slope_entry）
CANDIDATES = [
    # (label, short_p, spread_entry, slope_entry)
    ("C1 稳健 sP8/sp0.006/sl0.003", 8, 0.006, 0.003),
    ("C2 激进 sP3/sp0.003/sl0.006", 3, 0.003, 0.006),
    ("C3 均衡 sP5/sp0.006/sl0.003", 5, 0.006, 0.003),
    ("C4 宽 sP3/sp0.006/sl0.006", 3, 0.006, 0.006),
]

BASE_PARAMS = {
    "long_p": 13,
    "spread_strong": 0.03,
    "strength_multiplier": 250,
    "cooldown_bars": 2,
    "bb_period": 20, "bb_mult": 2.0,
    "rsi_period": 7,
    "bb_buy_kill": 0.3, "bb_sell_kill": 0.7,
    "min_volatility_pct": 0.01,
    "volume_period": 0,
    "rsi_buy_kill": 75.0, "rsi_sell_kill": 25.0,
}

# 配置：V7/V8/V9 级别的期货成本 + 中止损
FUT_CFG_LONG = BacktestConfig(
    mode="long_only", commission_rate=2e-5, slippage_pct=2e-5,
    stop_loss_pct=0.08, take_profit_pct=0.16,
    trailing_trigger_pct=0.06, trailing_retracement_pct=0.03,
    max_hold_bars=35,
)
FUT_CFG_LS = BacktestConfig(
    mode="long_short", commission_rate=2e-5, slippage_pct=2e-5,
    stop_loss_pct=0.08, take_profit_pct=0.16,
    trailing_trigger_pct=0.06, trailing_retracement_pct=0.03,
    max_hold_bars=35,
)


def evaluate(label, short_p, spread_entry, slope_entry, cfg, ticks_by_date):
    params = dict(BASE_PARAMS, short_p=short_p,
                  spread_entry=spread_entry, slope_entry=slope_entry)
    all_rets, all_wrs, all_pfs, all_trades, all_rx = [], [], [], [], []
    by_day_rets = {}
    n_win = 0
    for date_str, ticks in ticks_by_date.items():
        cursor = [0, 0]
        for w_start, w_end in _iter_windows(ticks):
            wt = _slice(ticks, w_start, w_end, cursor)
            if len(wt) < MIN_TICKS:
                continue
            res = run_single_window_backtest(
                wt, strategy="momentum", base_params=params,
                param_grid=None, bt_cfg=cfg,
            )
            m = res["best_metrics"]
            if not m:
                continue
            n_win += 1
            r = m.get("totalReturnPct") or 0.0
            all_rets.append(r)
            by_day_rets.setdefault(date_str, []).append(r)
            if m.get("winRatePct") is not None:
                all_wrs.append(m["winRatePct"])
            pf = m.get("profitFactor")
            if isinstance(pf, (int, float)):
                all_pfs.append(pf)
            all_trades.append(m.get("roundTripCount") or 0)
            all_rx.append(m.get("riskExitCount") or 0)

    if n_win == 0:
        return None
    pos = sum(1 for r in all_rets if r > 0.001)
    compound = 1.0
    for r in all_rets:
        compound *= (1 + r / 100.0)
    compound_pct = (compound - 1) * 100
    daily = {}
    worst_day = 0.0
    for d, lst in by_day_rets.items():
        c = 1.0
        for r in lst:
            c *= (1 + r / 100.0)
        pct = (c - 1) * 100
        daily[d] = round(pct, 3)
        worst_day = min(worst_day, pct)

    return {
        "label": label,
        "mode": cfg.mode,
        "params": params,
        "n_windows": n_win,
        "pos_rate_pct": round(pos / n_win * 100, 2),
        "avg_return_pct": round(sum(all_rets) / n_win, 4),
        "compound_return_pct": round(compound_pct, 3),
        "avg_win_rate_pct": round(sum(all_wrs) / len(all_wrs), 2) if all_wrs else None,
        "avg_profit_factor": round(sum(all_pfs) / len(all_pfs), 2) if all_pfs else None,
        "avg_trades_per_window": round(sum(all_trades) / n_win, 2),
        "total_trades": sum(all_trades),
        "windows_with_trades": sum(1 for t in all_trades if t > 0),
        "daily_compound_pct": daily,
        "worst_day_compound_pct": round(worst_day, 3),
    }


def main():
    t0 = time.time()
    dates = get_available_dates(INSTRUMENT)
    ticks_by_date = {}
    for d in dates:
        raw = [t for t in get_ticks_for_date(INSTRUMENT, d)
               if t.get("t", 0) >= OUTLIER_MIN_MS and t.get("y")]
        if len(raw) >= MIN_TICKS:
            ticks_by_date[d] = raw
    print(f"dates={list(ticks_by_date.keys())}")

    results = []
    for cfg_label, cfg in [("long_only", FUT_CFG_LONG), ("long_short", FUT_CFG_LS)]:
        for name, sp, se, sl in CANDIDATES:
            full = f"{cfg_label} / {name}"
            print(f"  评估 {full}")
            r = evaluate(full, sp, se, sl, cfg, ticks_by_date)
            if r:
                results.append(r)

    print("\n" + "=" * 140)
    print(f"固定参数 OOS 对比 (期货成本 0.002%/边，窗口 5min 非重叠)")
    print("=" * 140)
    header = ["候选", "窗口", "有交易", "正收益%", "均%", "复利%", "胜率%", "PF", "交易/窗", "最差日复利%"]
    fmt = "{:<44} {:>5} {:>7} {:>8} {:>8} {:>8} {:>7} {:>6} {:>8} {:>11}"
    print(fmt.format(*header))
    print("-" * 140)
    for r in results:
        print(fmt.format(
            r["label"][:44], r["n_windows"],
            r["windows_with_trades"], r["pos_rate_pct"],
            r["avg_return_pct"], r["compound_return_pct"],
            r["avg_win_rate_pct"] or 0, r["avg_profit_factor"] or 0,
            r["avg_trades_per_window"], r["worst_day_compound_pct"],
        ))
    print("=" * 140)

    out = Path(__file__).resolve().parent.parent / "backtest_xag_scalping_oos.json"
    json.dump({"results": results, "elapsed_sec": round(time.time() - t0, 2)},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n已保存 {out} (耗时 {round(time.time()-t0,2)}s)")


if __name__ == "__main__":
    main()
