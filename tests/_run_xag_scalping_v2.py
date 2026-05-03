"""COMEX 银秒级策略 v2：自设计策略 + walk-forward OOS 验证。

策略（从 tick 统计特性反推）：
  S1 MR-Z  ── z-score 均值回归：|z|>z_in 入场反向，|z|<z_out 止盈，|z|>z_stop 止损。
  S2 BO-D  ── Donchian 突破追涨：突破最近 N tick 高低点后顺势，ATR 比例止损/止盈。

验证方法：
  walk-forward，按可用日期顺序：day[t] 做 in-sample 参数网格寻优 → day[t+1] 纯 OOS 应用。
  成本：commission 0.002%/边 + slippage 0.002%/边 = round-trip 0.008%（对应 CME micro silver 实际值）。

产出：
  tests/_run_xag_scalping_v2.py 一键产出 `backtest_xag_v2.json` + 控制台对比表。
"""
from __future__ import annotations

import io
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from itertools import product
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.tick_storage import get_available_dates, get_ticks_for_date

INSTRUMENT = "xag"
OUTLIER_MIN_MS = 1_500_000_000_000
COMM = 2e-5   # 0.002% 每边
SLIP = 2e-5
COST_FACTOR_ONE_SIDE = 1.0 - COMM - SLIP


# ── 策略 1：z-score mean reversion ──────────────────────────────────
@dataclass
class MRParams:
    mean_w: int = 20        # 滚动均值窗口
    std_w: int = 60         # 滚动 std 窗口
    z_in: float = 2.0       # 入场 z 阈值
    z_out: float = 0.3      # 止盈 z 阈值
    z_stop: float = 3.5     # 止损 z 阈值
    max_hold: int = 30      # 最大持仓 bar 数
    cooldown: int = 3


@dataclass
class TFParams:
    """Tail-Fade：价格单 tick 跳动超过 K·std 时反向。"""
    std_w: int = 60
    k_enter: float = 2.8
    tp_sigma: float = 0.8     # 目标：回撤 tp_sigma·std
    sl_sigma: float = 1.8     # 止损：同向再扩 sl_sigma·std
    max_hold: int = 8
    cooldown: int = 3


@dataclass
class RGMRParams:
    """Regime-Gated MR：仅在滚动 VR<vr_thr 时做 MR。"""
    mean_w: int = 30
    std_w: int = 120
    vr_w: int = 200
    vr_q: int = 5
    vr_thr: float = 0.95
    z_in: float = 1.8
    z_out: float = 0.3
    z_stop: float = 3.0
    max_hold: int = 30
    cooldown: int = 3


@dataclass
class BOParams:
    ch_n: int = 40          # Donchian 通道长度（ticks）
    atr_n: int = 30         # ATR 窗口
    atr_sl_mult: float = 1.5
    atr_tp_mult: float = 2.0
    max_hold: int = 25
    cooldown: int = 3


@dataclass
class TradeResult:
    pnl_pct: float
    bars: int
    direction: int          # +1 long, -1 short
    exit_reason: str


# ── 引擎：逐 bar 状态机，成本按每次换仓扣一次 ───────────────────────
def _apply_costs(gross_pct: float) -> float:
    """双边成本：gross return (%) → 净 return (%)"""
    return gross_pct - (COMM + SLIP) * 2 * 100


def run_mr(prices: list[float], p: MRParams) -> list[TradeResult]:
    n = len(prices)
    w = max(p.mean_w, p.std_w)
    if n < w + 5:
        return []

    # rolling mean & std（O(n)）
    mean_buf = [0.0] * n
    std_buf = [0.0] * n
    # 简单实现：对每个 i 做增量不如重计算 —— n=30000 可接受
    # 用 prefix sum 和 sum of squares
    psum = [0.0] * (n + 1)
    psum2 = [0.0] * (n + 1)
    for i in range(n):
        psum[i + 1] = psum[i] + prices[i]
        psum2[i + 1] = psum2[i] + prices[i] * prices[i]

    trades: list[TradeResult] = []
    position = 0      # +1/-1/0
    entry_px = 0.0
    entry_i = 0
    cooldown_left = 0

    for i in range(w, n):
        mw = p.mean_w
        m = (psum[i + 1] - psum[i + 1 - mw]) / mw
        sw = p.std_w
        ex = (psum[i + 1] - psum[i + 1 - sw]) / sw
        ex2 = (psum2[i + 1] - psum2[i + 1 - sw]) / sw
        var = max(0.0, ex2 - ex * ex)
        std = math.sqrt(var)
        price = prices[i]

        if std <= 0:
            continue
        z = (price - m) / std

        # 持仓检查
        if position != 0:
            bars_held = i - entry_i
            # 止损
            if (position > 0 and z < -p.z_stop) or (position < 0 and z > p.z_stop):
                gross = (price - entry_px) / entry_px * 100 * position
                trades.append(TradeResult(_apply_costs(gross), bars_held, position, "stop"))
                position = 0
                cooldown_left = p.cooldown
                continue
            # 止盈
            if abs(z) <= p.z_out:
                gross = (price - entry_px) / entry_px * 100 * position
                trades.append(TradeResult(_apply_costs(gross), bars_held, position, "target"))
                position = 0
                cooldown_left = p.cooldown
                continue
            # 时间止损
            if bars_held >= p.max_hold:
                gross = (price - entry_px) / entry_px * 100 * position
                trades.append(TradeResult(_apply_costs(gross), bars_held, position, "time"))
                position = 0
                cooldown_left = p.cooldown
                continue

        # 开仓
        if position == 0:
            if cooldown_left > 0:
                cooldown_left -= 1
                continue
            if z > p.z_in:
                position = -1   # 价格过高 → 做空
                entry_px = price
                entry_i = i
            elif z < -p.z_in:
                position = +1   # 价格过低 → 做多
                entry_px = price
                entry_i = i

    # 收盘强平
    if position != 0:
        gross = (prices[-1] - entry_px) / entry_px * 100 * position
        trades.append(TradeResult(_apply_costs(gross), n - 1 - entry_i, position, "close"))

    return trades


def run_tf(prices: list[float], p: TFParams) -> list[TradeResult]:
    """Tail-Fade: 单 tick 跳动 > k_enter*std 时反向进入。"""
    n = len(prices)
    w = p.std_w + 2
    if n < w + 5:
        return []

    # 预计算 log-returns 并滚动 std
    rets = [0.0] + [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, n)]
    # 滚动 std (population)
    psum = [0.0] * (n + 1)
    psum2 = [0.0] * (n + 1)
    for i in range(n):
        psum[i + 1] = psum[i] + rets[i]
        psum2[i + 1] = psum2[i] + rets[i] * rets[i]

    trades: list[TradeResult] = []
    position = 0
    entry_px = 0.0
    entry_i = 0
    tp_px = 0.0
    sl_px = 0.0
    cooldown_left = 0

    for i in range(w, n):
        sw = p.std_w
        ex = (psum[i + 1] - psum[i + 1 - sw]) / sw
        ex2 = (psum2[i + 1] - psum2[i + 1 - sw]) / sw
        var = max(0.0, ex2 - ex * ex)
        std = math.sqrt(var)
        price = prices[i]

        if position != 0:
            bars_held = i - entry_i
            if position > 0:
                if price <= sl_px:
                    gross = (sl_px - entry_px) / entry_px * 100
                    trades.append(TradeResult(_apply_costs(gross), bars_held, +1, "stop"))
                    position = 0; cooldown_left = p.cooldown; continue
                if price >= tp_px:
                    gross = (tp_px - entry_px) / entry_px * 100
                    trades.append(TradeResult(_apply_costs(gross), bars_held, +1, "target"))
                    position = 0; cooldown_left = p.cooldown; continue
            else:
                if price >= sl_px:
                    gross = (entry_px - sl_px) / entry_px * 100
                    trades.append(TradeResult(_apply_costs(gross), bars_held, -1, "stop"))
                    position = 0; cooldown_left = p.cooldown; continue
                if price <= tp_px:
                    gross = (entry_px - tp_px) / entry_px * 100
                    trades.append(TradeResult(_apply_costs(gross), bars_held, -1, "target"))
                    position = 0; cooldown_left = p.cooldown; continue
            if bars_held >= p.max_hold:
                gross = (price - entry_px) / entry_px * 100 * position
                trades.append(TradeResult(_apply_costs(gross), bars_held, position, "time"))
                position = 0; cooldown_left = p.cooldown; continue

        if position == 0 and std > 0:
            if cooldown_left > 0:
                cooldown_left -= 1
                continue
            r_now = rets[i]
            if r_now > p.k_enter * std:
                # 价格突涨 → 做空
                position = -1
                entry_px = price; entry_i = i
                tp_px = price * (1 - p.tp_sigma * std)
                sl_px = price * (1 + p.sl_sigma * std)
            elif r_now < -p.k_enter * std:
                position = +1
                entry_px = price; entry_i = i
                tp_px = price * (1 + p.tp_sigma * std)
                sl_px = price * (1 - p.sl_sigma * std)

    if position != 0:
        gross = (prices[-1] - entry_px) / entry_px * 100 * position
        trades.append(TradeResult(_apply_costs(gross), n - 1 - entry_i, position, "close"))
    return trades


def run_rgmr(prices: list[float], p: RGMRParams) -> list[TradeResult]:
    """Regime-Gated MR: 只在滚动 VR<vr_thr（实际呈现均值回归）时做 z-score MR。"""
    n = len(prices)
    w = max(p.mean_w, p.std_w, p.vr_w) + 2
    if n < w + 5:
        return []

    rets = [0.0] + [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, n)]
    psum = [0.0] * (n + 1)
    psum2 = [0.0] * (n + 1)
    rsum = [0.0] * (n + 1)
    rsum2 = [0.0] * (n + 1)
    for i in range(n):
        psum[i + 1] = psum[i] + prices[i]
        psum2[i + 1] = psum2[i] + prices[i] * prices[i]
        rsum[i + 1] = rsum[i] + rets[i]
        rsum2[i + 1] = rsum2[i] + rets[i] * rets[i]

    trades: list[TradeResult] = []
    position = 0
    entry_px = 0.0
    entry_i = 0
    cooldown_left = 0

    for i in range(w, n):
        # 滚动 mean / std (price)
        mw = p.mean_w
        m = (psum[i + 1] - psum[i + 1 - mw]) / mw
        sw = p.std_w
        ex = (psum[i + 1] - psum[i + 1 - sw]) / sw
        ex2 = (psum2[i + 1] - psum2[i + 1 - sw]) / sw
        var = max(0.0, ex2 - ex * ex)
        std = math.sqrt(var)
        if std <= 0:
            continue
        z = (prices[i] - m) / std

        # 滚动 VR(vr_q) on last vr_w returns
        vw = p.vr_w
        r_window = rets[i - vw + 1 : i + 1]
        if len(r_window) < vw:
            continue
        var1 = (rsum2[i + 1] - rsum2[i + 1 - vw]) / vw
        mean1 = (rsum[i + 1] - rsum[i + 1 - vw]) / vw
        var1 = max(0.0, var1 - mean1 * mean1)
        # q-period returns
        q = p.vr_q
        q_rets = [sum(r_window[j:j + q]) for j in range(len(r_window) - q + 1)]
        if len(q_rets) < 2 or var1 <= 0:
            continue
        mq = sum(q_rets) / len(q_rets)
        varq = sum((x - mq) ** 2 for x in q_rets) / len(q_rets)
        vr = varq / (q * var1)

        price = prices[i]

        if position != 0:
            bars_held = i - entry_i
            if (position > 0 and z < -p.z_stop) or (position < 0 and z > p.z_stop):
                gross = (price - entry_px) / entry_px * 100 * position
                trades.append(TradeResult(_apply_costs(gross), bars_held, position, "stop"))
                position = 0; cooldown_left = p.cooldown; continue
            if abs(z) <= p.z_out:
                gross = (price - entry_px) / entry_px * 100 * position
                trades.append(TradeResult(_apply_costs(gross), bars_held, position, "target"))
                position = 0; cooldown_left = p.cooldown; continue
            if bars_held >= p.max_hold:
                gross = (price - entry_px) / entry_px * 100 * position
                trades.append(TradeResult(_apply_costs(gross), bars_held, position, "time"))
                position = 0; cooldown_left = p.cooldown; continue

        if position == 0 and vr < p.vr_thr:
            if cooldown_left > 0:
                cooldown_left -= 1
                continue
            if z > p.z_in:
                position = -1; entry_px = price; entry_i = i
            elif z < -p.z_in:
                position = +1; entry_px = price; entry_i = i

    if position != 0:
        gross = (prices[-1] - entry_px) / entry_px * 100 * position
        trades.append(TradeResult(_apply_costs(gross), n - 1 - entry_i, position, "close"))
    return trades


def run_bo(prices: list[float], p: BOParams) -> list[TradeResult]:
    n = len(prices)
    w = max(p.ch_n, p.atr_n) + 2
    if n < w + 5:
        return []

    trades: list[TradeResult] = []
    position = 0
    entry_px = 0.0
    entry_i = 0
    stop_px = 0.0
    target_px = 0.0
    cooldown_left = 0

    # rolling ATR（简单实现：|p[i]-p[i-1]| 的滚动均值）
    abs_diff = [0.0] + [abs(prices[i] - prices[i - 1]) for i in range(1, n)]

    for i in range(w, n):
        # 最近 ch_n 区间高低（不含当前）
        lo_i, hi_i = i - p.ch_n, i
        hi = max(prices[lo_i:hi_i])
        lo = min(prices[lo_i:hi_i])
        atr = sum(abs_diff[i - p.atr_n:i]) / p.atr_n
        price = prices[i]

        if position != 0:
            bars_held = i - entry_i
            # 止损 / 止盈
            if position > 0:
                if price <= stop_px:
                    gross = (stop_px - entry_px) / entry_px * 100
                    trades.append(TradeResult(_apply_costs(gross), bars_held, +1, "stop"))
                    position = 0; cooldown_left = p.cooldown; continue
                if price >= target_px:
                    gross = (target_px - entry_px) / entry_px * 100
                    trades.append(TradeResult(_apply_costs(gross), bars_held, +1, "target"))
                    position = 0; cooldown_left = p.cooldown; continue
            else:
                if price >= stop_px:
                    gross = (entry_px - stop_px) / entry_px * 100
                    trades.append(TradeResult(_apply_costs(gross), bars_held, -1, "stop"))
                    position = 0; cooldown_left = p.cooldown; continue
                if price <= target_px:
                    gross = (entry_px - target_px) / entry_px * 100
                    trades.append(TradeResult(_apply_costs(gross), bars_held, -1, "target"))
                    position = 0; cooldown_left = p.cooldown; continue
            if bars_held >= p.max_hold:
                gross = (price - entry_px) / entry_px * 100 * position
                trades.append(TradeResult(_apply_costs(gross), bars_held, position, "time"))
                position = 0; cooldown_left = p.cooldown; continue

        if position == 0 and atr > 0:
            if cooldown_left > 0:
                cooldown_left -= 1
                continue
            if price > hi:
                position = +1
                entry_px = price; entry_i = i
                stop_px = price - p.atr_sl_mult * atr
                target_px = price + p.atr_tp_mult * atr
            elif price < lo:
                position = -1
                entry_px = price; entry_i = i
                stop_px = price + p.atr_sl_mult * atr
                target_px = price - p.atr_tp_mult * atr

    if position != 0:
        gross = (prices[-1] - entry_px) / entry_px * 100 * position
        trades.append(TradeResult(_apply_costs(gross), n - 1 - entry_i, position, "close"))
    return trades


# ── 评估 ─────────────────────────────────────────────────────────────
def evaluate(trades: list[TradeResult]) -> dict:
    if not trades:
        return {"trades": 0, "compound_pct": 0, "win_pct": 0, "pf": 0,
                "avg_bars": 0, "expectancy_pct": 0, "sharpe": 0}
    rets = [t.pnl_pct for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r < 0]
    compound = 1.0
    for r in rets:
        compound *= (1 + r / 100.0)
    compound_pct = (compound - 1) * 100
    pf = (sum(wins) / sum(losses)) if losses else (float("inf") if wins else 0)
    std = statistics.pstdev(rets) if len(rets) > 1 else 0
    sharpe = (statistics.mean(rets) / std * math.sqrt(len(rets))) if std > 0 else 0
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_pct": round(len(wins) / len(trades) * 100, 2),
        "compound_pct": round(compound_pct, 3),
        "total_pct": round(sum(rets), 3),
        "avg_pct": round(sum(rets) / len(trades), 4),
        "expectancy_pct": round(sum(rets) / len(trades), 4),
        "pf": round(pf, 2) if pf != float("inf") else 999.0,
        "avg_bars": round(sum(t.bars for t in trades) / len(trades), 1),
        "sharpe": round(sharpe, 3),
        "max_win_pct": round(max(rets), 4),
        "max_loss_pct": round(min(rets), 4),
    }


# ── 参数网格 ────────────────────────────────────────────────────────
MR_GRID = {
    "mean_w":  [20, 40],
    "std_w":   [120],
    "z_in":    [1.5, 2.0, 2.5],
    "z_out":   [0.3, 0.5],
    "z_stop":  [3.0, 4.0],
    "max_hold":[20, 40],
    "cooldown":[3],
}   # 2*3*2*2*2 = 48 组

BO_GRID = {
    "ch_n":        [20, 40, 80],
    "atr_n":       [60],
    "atr_sl_mult": [1.0, 1.5],
    "atr_tp_mult": [2.0, 3.0],
    "max_hold":    [20, 40],
    "cooldown":    [3],
}   # 3*2*2*2 = 24 组

TF_GRID = {
    "std_w":    [60, 120],
    "k_enter":  [2.2, 2.8, 3.5],
    "tp_sigma": [0.5, 0.8],
    "sl_sigma": [1.5, 2.0],
    "max_hold": [5, 10],
    "cooldown": [3],
}   # 2*3*2*2*2 = 48 组

RGMR_GRID = {
    "mean_w":  [20, 40],
    "std_w":   [120],
    "vr_w":    [200],
    "vr_q":    [5],
    "vr_thr":  [0.90, 0.95, 1.00],
    "z_in":    [1.5, 2.0],
    "z_out":   [0.3],
    "z_stop":  [3.0, 4.0],
    "max_hold":[30],
    "cooldown":[3],
}   # 2*3*2*2 = 24 组


def _grid_combos(grid: dict) -> list[dict]:
    names = sorted(grid.keys())
    out = []
    for combo in product(*(grid[k] for k in names)):
        out.append(dict(zip(names, combo)))
    return out


def _score(metrics: dict) -> float:
    """综合得分：复利 × sqrt(交易数) - 0.2 × |最大单笔亏损|，偏好样本多且稳健。"""
    n = metrics["trades"]
    if n < 5:
        return -1e9
    return metrics["compound_pct"] * math.sqrt(n) - 0.2 * abs(metrics["max_loss_pct"])


_GRID_MAP = {"mr": MR_GRID, "bo": BO_GRID, "tf": TF_GRID, "rgmr": RGMR_GRID}
_PARAM_MAP = {"mr": MRParams, "bo": BOParams, "tf": TFParams, "rgmr": RGMRParams}
_RUN_MAP = {"mr": run_mr, "bo": run_bo, "tf": run_tf, "rgmr": run_rgmr}


def optimize(prices: list[float], strategy: str) -> tuple[dict, dict]:
    grid = _GRID_MAP[strategy]
    param_cls = _PARAM_MAP[strategy]
    runner = _RUN_MAP[strategy]
    combos = _grid_combos(grid)
    best = None
    best_metrics = None
    best_score = -1e18
    for c in combos:
        trades = runner(prices, param_cls(**c))
        m = evaluate(trades)
        s = _score(m)
        if s > best_score:
            best_score = s
            best = c
            best_metrics = m
    return best, best_metrics


def apply_params(prices: list[float], strategy: str, params: dict) -> dict:
    trades = _RUN_MAP[strategy](prices, _PARAM_MAP[strategy](**params))
    return evaluate(trades)


# ── Walk-Forward 主流程 ─────────────────────────────────────────────
def _load_prices(date_str: str) -> list[float]:
    ts = get_ticks_for_date(INSTRUMENT, date_str)
    return [t["y"] for t in ts if t.get("t", 0) >= OUTLIER_MIN_MS and t.get("y")]


def walk_forward(strategy: str, dates: list[str]) -> dict:
    print(f"\n{'=' * 100}")
    print(f"Walk-Forward ({strategy.upper()}) — 训练 day[t], OOS 测试 day[t+1]")
    print(f"{'=' * 100}")

    oos_trades_all = []
    rows = []
    for i in range(len(dates) - 1):
        train_d = dates[i]
        test_d = dates[i + 1]
        train_px = _load_prices(train_d)
        test_px = _load_prices(test_d)
        if len(train_px) < 500 or len(test_px) < 500:
            continue
        t0 = time.time()
        best, best_m = optimize(train_px, strategy)
        oos_trades = _RUN_MAP[strategy](test_px, _PARAM_MAP[strategy](**best))
        oos_m = evaluate(oos_trades)
        oos_trades_all.extend(oos_trades)
        dt = time.time() - t0
        rows.append({
            "train": train_d, "test": test_d,
            "best_params": best,
            "is_metrics": best_m,
            "oos_metrics": oos_m,
            "seconds": round(dt, 2),
        })
        p_short = {k: best[k] for k in sorted(best)}
        print(f"  train={train_d} → test={test_d}  params={p_short}")
        print(f"     IS: n={best_m['trades']:>4} win={best_m['win_pct']:>5.1f}% "
              f"compound={best_m['compound_pct']:>7.3f}% pf={best_m['pf']:>5.2f} "
              f"bars={best_m['avg_bars']:>4.1f}")
        print(f"    OOS: n={oos_m['trades']:>4} win={oos_m['win_pct']:>5.1f}% "
              f"compound={oos_m['compound_pct']:>7.3f}% pf={oos_m['pf']:>5.2f} "
              f"bars={oos_m['avg_bars']:>4.1f}  ({dt:.1f}s)")

    # 汇总 OOS
    all_m = evaluate(oos_trades_all)
    print(f"\n>> 全 OOS 汇总 [{strategy.upper()}]: n={all_m['trades']} win={all_m['win_pct']}% "
          f"compound={all_m['compound_pct']}% pf={all_m['pf']} sharpe={all_m['sharpe']} "
          f"expectancy={all_m['expectancy_pct']}%")
    return {"strategy": strategy, "rows": rows, "oos_overall": all_m}


def main():
    t0 = time.time()
    dates = list(reversed(get_available_dates(INSTRUMENT)))  # 时间正序
    print(f"日期正序: {dates}")

    res_mr = walk_forward("mr", dates)
    res_bo = walk_forward("bo", dates)
    res_tf = walk_forward("tf", dates)
    res_rgmr = walk_forward("rgmr", dates)
    all_res = [res_mr, res_bo, res_tf, res_rgmr]

    print(f"\n{'=' * 100}")
    print(f"综合对比 (成本: commission {COMM*100:.3f}%/边 + slip {SLIP*100:.3f}%/边 = 0.008% round-trip)")
    print(f"{'=' * 100}")
    print(f"{'Strategy':<8} {'Trades':>7} {'Win%':>7} {'Compound%':>10} {'PF':>6} "
          f"{'Sharpe':>7} {'Expect%':>8} {'AvgBars':>8}")
    for r in all_res:
        m = r["oos_overall"]
        print(f"{r['strategy'].upper():<8} {m['trades']:>7} {m['win_pct']:>7} "
              f"{m['compound_pct']:>10} {m['pf']:>6} {m['sharpe']:>7} "
              f"{m['expectancy_pct']:>8} {m['avg_bars']:>8}")

    # 验收门槛
    print("\n验收门槛 (OOS 综合): trades≥50 && win≥52% && PF≥1.3 && compound>0")
    for r in all_res:
        m = r["oos_overall"]
        ok = (m["trades"] >= 50 and m["win_pct"] >= 52 and m["pf"] >= 1.3 and m["compound_pct"] > 0)
        print(f"  [{'PASS' if ok else 'FAIL'}] {r['strategy'].upper()}")

    out = Path(__file__).resolve().parent.parent / "backtest_xag_v2.json"

    def _default(o):
        if hasattr(o, "__dict__"):
            return o.__dict__
        raise TypeError(str(type(o)))

    json.dump({r["strategy"]: r for r in all_res} | {"elapsed_sec": round(time.time() - t0, 2)},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=_default)
    print(f"\n已保存 {out}  (总耗时 {round(time.time()-t0,2)}s)")


if __name__ == "__main__":
    main()
