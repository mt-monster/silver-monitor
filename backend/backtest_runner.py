"""5分钟 tick 窗口滑动扫描回测引擎。

核心功能：
- 对某一天的所有 tick 数据，以滑动窗口（默认步长 30s）生成所有可能的 5 分钟片段
- 对每个片段执行策略回测，记录绩效
- 支持参数网格扫描，找出每个窗口的最佳参数
- 保存最佳结果到 SQLite
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from typing import Any

from backend.backtest import (
    BacktestConfig,
    run_momentum_backtest,
    run_reversal_backtest,
)
from backend.config import CST, log
from backend.state import state
from backend.strategies.momentum import MomentumParams
from backend.strategies.reversal import ReversalParams
from backend.tick_storage import (
    get_ticks_for_date,
    save_daily_best,
    save_window_backtest,
)

WINDOW_MS = 5 * 60 * 1000  # 5 分钟
DEFAULT_STEP_MS = 30 * 1000  # 默认滑动步长 30 秒

# 参数网格：对 5 分钟 tick 回测做轻量参数扫描
# 只变 spread_entry / slope_entry，其余用默认值
DEFAULT_PARAM_GRID = {
    "spread_entry": [0.01, 0.02, 0.03, 0.05],
    "slope_entry": [0.005, 0.01, 0.015, 0.02],
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _date_str_from_ms(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=CST).strftime("%Y-%m-%d")


def _time_str_from_ms(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=CST).strftime("%H:%M:%S")


def _build_param_combinations(
    base_params: dict[str, Any],
    grid: dict[str, list] | None = None,
) -> list[dict[str, Any]]:
    """生成参数组合列表。"""
    from itertools import product

    g = grid or {}
    if not g:
        return [base_params]
    names = sorted(g.keys())
    combos = list(product(*(g[k] for k in names)))
    results = []
    for combo in combos:
        p = dict(base_params)
        p.update(dict(zip(names, combo)))
        results.append(p)
    return results


def _run_momentum_for_window(
    bars: list[dict],
    params_dict: dict[str, Any],
    bt_cfg: BacktestConfig | None = None,
) -> dict[str, Any]:
    """对单个窗口执行动量回测。"""
    bt_cfg = bt_cfg or BacktestConfig()
    p = MomentumParams(
        short_p=int(params_dict.get("short_p", 5)),
        long_p=int(params_dict.get("long_p", 15)),
        spread_entry=float(params_dict.get("spread_entry", 0.03)),
        spread_strong=float(params_dict.get("spread_strong", 0.08)),
        slope_entry=float(params_dict.get("slope_entry", 0.015)),
        strength_multiplier=float(params_dict.get("strength_multiplier", 250.0)),
        cooldown_bars=int(params_dict.get("cooldown_bars", 2)),
        bb_period=int(params_dict.get("bb_period", 10)),
        bb_mult=float(params_dict.get("bb_mult", 2.0)),
        rsi_period=int(params_dict.get("rsi_period", 10)),
        bb_buy_kill=float(params_dict.get("bb_buy_kill", 0.3)),
        bb_sell_kill=float(params_dict.get("bb_sell_kill", 0.7)),
        min_volatility_pct=float(params_dict.get("min_volatility_pct", 0.03)),
    )
    return run_momentum_backtest(bars, p, bt_cfg)


def _score_for_ranking(metrics: dict[str, Any]) -> float:
    """综合评分：优先总收益率，辅以夏普和最大回撤。"""
    total_ret = metrics.get("totalReturnPct") or 0.0
    sharpe = metrics.get("sharpeRatio") or 0.0
    mdd = metrics.get("maxDrawdownPct") or 0.0
    # 综合分数：收益率权重 0.6，夏普权重 0.3，回撤惩罚 0.1
    # 对短周期回测，总收益率比年化夏普更直观
    return total_ret * 0.6 + sharpe * 10.0 * 0.3 - mdd * 0.1


def run_single_window_backtest(
    bars: list[dict],
    strategy: str = "momentum",
    base_params: dict[str, Any] | None = None,
    param_grid: dict[str, list] | None = None,
    bt_cfg: BacktestConfig | None = None,
) -> dict[str, Any]:
    """对单个 5 分钟窗口做回测，支持参数网格扫描。

    Returns:
        {
            "best_params": {...},
            "best_metrics": {...},
            "all_results": [{"params": ..., "metrics": ...}, ...],
            "equity": [...],
            "trades": [...],
        }
    """
    base = base_params or {}
    combos = _build_param_combinations(base, param_grid)
    best_score = float("-inf")
    best_result: dict[str, Any] | None = None
    all_results = []

    for combo in combos:
        try:
            if strategy == "momentum":
                result = _run_momentum_for_window(bars, combo, bt_cfg)
            else:
                # reversal 暂用默认参数
                p = ReversalParams()
                result = run_reversal_backtest(bars, p, bt_cfg)
            m = result.get("metrics", {})
            score = _score_for_ranking(m)
            entry = {
                "params": combo,
                "metrics": m,
                "score": score,
            }
            all_results.append(entry)
            if score > best_score:
                best_score = score
                best_result = {
                    "best_params": combo,
                    "best_metrics": m,
                    "equity": result.get("equity", []),
                    "trades": result.get("trades", []),
                }
        except Exception as exc:
            log.warning(f"[5min-window] param error: {exc}")
            continue

    if best_result is None:
        return {
            "best_params": base,
            "best_metrics": {},
            "all_results": [],
            "equity": [],
            "trades": [],
        }

    return {
        "best_params": best_result["best_params"],
        "best_metrics": best_result["best_metrics"],
        "all_results": all_results,
        "equity": best_result.get("equity", []),
        "trades": best_result.get("trades", []),
    }


def scan_5min_windows(
    instrument_id: str,
    date_str: str,
    strategy: str = "momentum",
    base_params: dict[str, Any] | None = None,
    param_grid: dict[str, list] | None = None,
    step_ms: int = DEFAULT_STEP_MS,
    bt_cfg: BacktestConfig | None = None,
    save_results: bool = True,
    progress_callback: Any = None,
) -> dict[str, Any]:
    """扫描某天的所有 5 分钟 tick 窗口，找出最佳绩效的时间点和参数。

    Args:
        instrument_id: 品种 ID，如 "xag"
        date_str: 日期，如 "2026-04-21"
        strategy: "momentum" 或 "reversal"
        base_params: 基础参数
        param_grid: 参数网格，None 则只用 base_params
        step_ms: 滑动步长（毫秒），默认 30 秒
        bt_cfg: 回测配置
        save_results: 是否保存到 SQLite
        progress_callback: 可选的进度回调函数 (current, total) -> None

    Returns:
        {
            "instrument_id": "xag",
            "date_str": "2026-04-21",
            "strategy": "momentum",
            "window_ms": 300000,
            "step_ms": 30000,
            "total_windows": 120,
            "best_window": {
                "start_ms": ...,
                "end_ms": ...,
                "start_time": "09:30:00",
                "end_time": "09:35:00",
                "best_params": {...},
                "best_metrics": {...},
            },
            "top_windows": [...],  # 前 10 个窗口
            "scan_time_sec": 5.2,
        }
    """
    t0 = time.time()
    ticks = get_ticks_for_date(instrument_id, date_str)
    if len(ticks) < 100:
        from backend.tick_storage import get_available_dates
        available = get_available_dates(instrument_id)
        return {
            "error": "insufficient_ticks",
            "tick_count": len(ticks),
            "instrument_id": instrument_id,
            "date_str": date_str,
            "available_dates": available,
            "message": f"{instrument_id} 在 {date_str} 仅有 {len(ticks)} 条 tick，不足以扫描。"
                       f" 数据库中该品种有数据的日期: {', '.join(available[:5]) if available else '无'}"
        }

    # 生成滑动窗口
    first_ts = ticks[0]["t"]
    last_ts = ticks[-1]["t"]
    windows = []
    start = first_ts
    while start + WINDOW_MS <= last_ts:
        windows.append((start, start + WINDOW_MS))
        start += step_ms

    if not windows:
        return {"error": "no_valid_windows", "tick_count": len(ticks), "duration_ms": last_ts - first_ts}

    best_score = float("-inf")
    best_window: dict[str, Any] | None = None
    top_windows = []

    for idx, (w_start, w_end) in enumerate(windows):
        # 提取窗口内的 tick
        window_ticks = [t for t in ticks if w_start <= t["t"] <= w_end]
        if len(window_ticks) < 50:  # 至少需要 50 个点才能算
            if progress_callback:
                progress_callback(idx + 1, len(windows))
            continue

        result = run_single_window_backtest(
            window_ticks, strategy=strategy, base_params=base_params,
            param_grid=param_grid, bt_cfg=bt_cfg,
        )
        m = result["best_metrics"]
        score = _score_for_ranking(m)

        entry = {
            "start_ms": w_start,
            "end_ms": w_end,
            "start_time": _time_str_from_ms(w_start),
            "end_time": _time_str_from_ms(w_end),
            "best_params": result["best_params"],
            "best_metrics": m,
            "score": score,
            "tick_count": len(window_ticks),
        }
        top_windows.append(entry)

        if score > best_score:
            best_score = score
            best_window = entry

        # 保存每个窗口的结果（可选，批量保存时可能数据量很大）
        if save_results:
            try:
                save_window_backtest(
                    instrument_id, date_str, w_start, w_end, strategy,
                    result["best_params"], m,
                    equity=result.get("equity"), trades=result.get("trades"),
                )
            except Exception as exc:
                log.warning(f"[save_window] {exc}")

        if progress_callback:
            progress_callback(idx + 1, len(windows))

    # 排序并取 top 10
    top_windows.sort(key=lambda x: x["score"], reverse=True)
    top_10 = top_windows[:10]

    scan_time = round(time.time() - t0, 2)

    output = {
        "instrument_id": instrument_id,
        "date_str": date_str,
        "strategy": strategy,
        "window_ms": WINDOW_MS,
        "step_ms": step_ms,
        "total_windows": len(windows),
        "scanned_windows": len(top_windows),
        "best_window": best_window,
        "top_windows": [
            {
                "start_time": w["start_time"],
                "end_time": w["end_time"],
                "best_params": w["best_params"],
                "best_metrics": w["best_metrics"],
                "score": w["score"],
            }
            for w in top_10
        ],
        "tick_quality": _compute_tick_quality(ticks),
        "scan_time_sec": scan_time,
    }

    # 保存每日最佳
    if best_window and save_results:
        try:
            save_daily_best(
                instrument_id, date_str, strategy,
                best_window["start_ms"], best_window["end_ms"],
                best_window["best_params"], best_window["best_metrics"],
                len(top_windows),
                all_windows=[
                    {
                        "start_time": w["start_time"],
                        "end_time": w["end_time"],
                        "score": w["score"],
                        "totalReturnPct": w["best_metrics"].get("totalReturnPct"),
                        "maxDrawdownPct": w["best_metrics"].get("maxDrawdownPct"),
                        "roundTripCount": w["best_metrics"].get("roundTripCount"),
                    }
                    for w in top_windows
                ],
            )
        except Exception as exc:
            log.warning(f"[save_daily_best] {exc}")

    return output


def get_best_window_result(
    instrument_id: str,
    date_str: str,
    strategy: str = "momentum",
) -> dict[str, Any] | None:
    """从数据库查询某日最佳窗口结果。"""
    from backend.tick_storage import get_daily_best
    return get_daily_best(instrument_id, date_str, strategy)


def _compute_tick_quality(ticks: list[dict]) -> dict[str, Any]:
    """计算 tick 数据质量指标。"""
    if not ticks or len(ticks) < 2:
        return {
            "tickCount": len(ticks),
            "avgIntervalSec": None,
            "cv": None,
            "priceChangePct": None,
            "dataQuality": "insufficient",
        }

    prices = [t["y"] for t in ticks]
    intervals_ms = [ticks[i + 1]["t"] - ticks[i]["t"] for i in range(len(ticks) - 1)]
    avg_interval = sum(intervals_ms) / len(intervals_ms) / 1000.0

    mean_p = sum(prices) / len(prices)
    variance = sum((p - mean_p) ** 2 for p in prices) / len(prices)
    cv = (math.sqrt(variance) / mean_p * 100.0) if mean_p > 0 else 0.0

    price_change_pct = ((max(prices) - min(prices)) / min(prices) * 100.0) if min(prices) > 0 else 0.0

    # 数据质量分级
    n = len(ticks)
    if n >= 200 and cv >= 0.05:
        quality = "excellent"
    elif n >= 100 and cv >= 0.02:
        quality = "good"
    elif n >= 50:
        quality = "sparse"
    else:
        quality = "insufficient"

    return {
        "tickCount": n,
        "avgIntervalSec": round(avg_interval, 2),
        "cv": round(cv, 4),
        "priceChangePct": round(price_change_pct, 4),
        "dataQuality": quality,
    }


def scan_5min_from_buffer(
    instrument_id: str = "xag",
    strategy: str = "momentum",
    lookback_minutes: int = 5,
    base_params: dict[str, Any] | None = None,
    param_grid: dict[str, list] | None = None,
    bt_cfg: BacktestConfig | None = None,
) -> dict[str, Any]:
    """直接从内存 realtime_backtest_buffers 扫描最近 N 分钟的 tick 窗口。

    无需等待数据库积累，适合"实时 5 分钟"场景。
    """
    t0 = time.time()

    with state.cache_lock:
        rt_buf = state.realtime_backtest_buffers.get(instrument_id, [])

    if not rt_buf:
        return {
            "error": "no_buffer_data",
            "instrument_id": instrument_id,
            "message": f"{instrument_id} 的实时缓冲区为空，请等待 FastDataPoller 积累数据。",
        }

    # 截取最近 lookback_minutes 的数据
    cutoff_ms = _now_ms() - lookback_minutes * 60 * 1000
    ticks = [{"t": b["t"], "y": b["y"]} for b in rt_buf if b["t"] >= cutoff_ms]

    tick_quality = _compute_tick_quality(ticks)

    if len(ticks) < 30:
        return {
            "error": "insufficient_ticks",
            "instrument_id": instrument_id,
            "tick_count": len(ticks),
            "tick_quality": tick_quality,
            "message": f"最近 {lookback_minutes} 分钟仅有 {len(ticks)} 条 tick，不足以回测。",
        }

    # 5 分钟窗口内滑动扫描（步长 10 秒，更精细）
    step_ms = 10 * 1000
    first_ts = ticks[0]["t"]
    last_ts = ticks[-1]["t"]
    windows = []
    start = first_ts
    while start + WINDOW_MS <= last_ts:
        windows.append((start, start + WINDOW_MS))
        start += step_ms

    if not windows:
        # 如果数据不足一个完整 5 分钟窗口，直接用全部数据回测
        result = run_single_window_backtest(
            ticks, strategy=strategy, base_params=base_params,
            param_grid=param_grid, bt_cfg=bt_cfg,
        )
        m = result["best_metrics"]
        return {
            "instrument_id": instrument_id,
            "strategy": strategy,
            "source": "realtime_buffer",
            "window_ms": last_ts - first_ts,
            "total_windows": 0,
            "scanned_windows": 0,
            "best_window": {
                "start_ms": first_ts,
                "end_ms": last_ts,
                "start_time": _time_str_from_ms(first_ts),
                "end_time": _time_str_from_ms(last_ts),
                "best_params": result["best_params"],
                "best_metrics": m,
                "tick_count": len(ticks),
            },
            "top_windows": [],
            "tick_quality": tick_quality,
            "scan_time_sec": round(time.time() - t0, 2),
        }

    best_score = float("-inf")
    best_window: dict[str, Any] | None = None
    top_windows = []

    for w_start, w_end in windows:
        window_ticks = [t for t in ticks if w_start <= t["t"] <= w_end]
        if len(window_ticks) < 30:
            continue

        result = run_single_window_backtest(
            window_ticks, strategy=strategy, base_params=base_params,
            param_grid=param_grid, bt_cfg=bt_cfg,
        )
        m = result["best_metrics"]
        score = _score_for_ranking(m)

        entry = {
            "start_ms": w_start,
            "end_ms": w_end,
            "start_time": _time_str_from_ms(w_start),
            "end_time": _time_str_from_ms(w_end),
            "best_params": result["best_params"],
            "best_metrics": m,
            "score": score,
            "tick_count": len(window_ticks),
        }
        top_windows.append(entry)

        if score > best_score:
            best_score = score
            best_window = entry

    top_windows.sort(key=lambda x: x["score"], reverse=True)
    top_10 = top_windows[:10]

    scan_time = round(time.time() - t0, 2)

    return {
        "instrument_id": instrument_id,
        "strategy": strategy,
        "source": "realtime_buffer",
        "window_ms": WINDOW_MS,
        "step_ms": step_ms,
        "total_windows": len(windows),
        "scanned_windows": len(top_windows),
        "best_window": best_window,
        "top_windows": [
            {
                "start_time": w["start_time"],
                "end_time": w["end_time"],
                "best_params": w["best_params"],
                "best_metrics": w["best_metrics"],
                "score": w["score"],
            }
            for w in top_10
        ],
        "tick_quality": tick_quality,
        "scan_time_sec": scan_time,
    }


def get_available_scan_dates(instrument_id: str, strategy: str = "momentum") -> list[str]:
    """获取已有扫描结果的日期列表。"""
    from backend.tick_storage import _ensure_db
    with _ensure_db() as conn:
        cur = conn.execute(
            "SELECT DISTINCT date_str FROM daily_best_window WHERE instrument_id = ? AND strategy = ? ORDER BY date_str DESC",
            (instrument_id, strategy),
        )
        return [row[0] for row in cur.fetchall()]
