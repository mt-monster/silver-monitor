"""COMEX 银 tick 实盘验证策略。

策略目标不是保证收益，而是把高频策略写成可验证的状态机：
- 只读取已经发生的 tick；
- 每次开仓都有止损、止盈、移动止盈和最大持仓 tick 数；
- 提供 walk-forward 验证，避免只看窗口内最优参数。
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from backend.tick_storage import get_available_dates, get_ticks_for_date


OUTLIER_MIN_TIMESTAMP_MS = 1_500_000_000_000


@dataclass(frozen=True)
class XAGLiveParams:
    """XAG 秒级 tick 策略参数。"""

    min_ticks: int = 160
    mean_window: int = 80
    trend_window: int = 45
    channel_window: int = 120
    vr_window: int = 120
    vr_lag: int = 5
    z_entry: float = 2.1
    trend_entry_pct: float = 0.06
    breakout_buffer_pct: float = 0.012
    mean_reversion_vr: float = 0.92
    breakout_vr: float = 1.08
    stop_loss_pct: float = 0.10
    take_profit_pct: float = 0.18
    trailing_trigger_pct: float = 0.08
    trailing_retrace_pct: float = 0.035
    max_hold_ticks: int = 90
    cooldown_ticks: int = 12
    min_position_pct: float = 0.20
    max_position_pct: float = 0.80


@dataclass
class XAGLiveTrade:
    """单笔纸交易结果。"""

    entry_t: int
    exit_t: int
    direction: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    hold_ticks: int
    reason: str


def clean_xag_ticks(ticks: Iterable[dict[str, Any]]) -> list[dict[str, float | int]]:
    """过滤明显异常 tick，并按时间排序。"""

    clean: list[dict[str, float | int]] = []
    for item in ticks:
        try:
            ts = int(item.get("t") or item.get("timestamp_ms") or 0)
            price = float(item.get("y") if item.get("y") is not None else item.get("price"))
        except (TypeError, ValueError):
            continue
        if ts < OUTLIER_MIN_TIMESTAMP_MS:
            continue
        if not 50.0 <= price <= 100.0:
            continue
        clean.append({"t": ts, "y": price})
    clean.sort(key=lambda x: int(x["t"]))
    return clean


def load_xag_ticks_for_date(date_str: str) -> list[dict[str, float | int]]:
    """从 SQLite tick 库读取某天 COMEX 银 tick。"""

    return clean_xag_ticks(get_ticks_for_date("xag", date_str))


def load_available_xag_dates() -> list[str]:
    """返回有有效 XAG tick 的日期，按时间升序排列。"""

    dates = []
    for date_str in get_available_dates("xag"):
        if len(load_xag_ticks_for_date(date_str)) >= 200:
            dates.append(date_str)
    return sorted(dates)


def _variance_ratio(returns: list[float], lag: int) -> float | None:
    if len(returns) < lag * 4:
        return None
    one_var = statistics.pvariance(returns)
    if one_var <= 0:
        return None
    lagged = [sum(returns[i : i + lag]) for i in range(len(returns) - lag + 1)]
    if len(lagged) < 2:
        return None
    return statistics.pvariance(lagged) / (lag * one_var)


def _signal_from_prices(prices: list[float], p: XAGLiveParams) -> dict[str, Any]:
    need = max(p.min_ticks, p.mean_window + 2, p.channel_window + 2, p.vr_window + 2)
    if len(prices) < need:
        return {
            "signal": "neutral",
            "direction": "flat",
            "positionPct": 0.0,
            "reason": f"有效 tick 不足：{len(prices)}/{need}",
        }

    price = prices[-1]
    mean_slice = prices[-p.mean_window :]
    mean = statistics.fmean(mean_slice)
    std = statistics.pstdev(mean_slice)
    if std <= 0 or mean <= 0:
        return {"signal": "neutral", "direction": "flat", "positionPct": 0.0, "reason": "波动不足"}

    z = (price - mean) / std
    trend_base = prices[-p.trend_window]
    trend_pct = (price - trend_base) / trend_base * 100.0 if trend_base > 0 else 0.0
    channel = prices[-p.channel_window - 1 : -1]
    high = max(channel)
    low = min(channel)
    returns = [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(len(prices) - p.vr_window, len(prices))
        if prices[i - 1] > 0
    ]
    vr = _variance_ratio(returns, p.vr_lag)

    signal = "neutral"
    direction = "flat"
    regime = "unknown"
    strength = 0.0
    reason = "无优势信号"

    if vr is not None and vr <= p.mean_reversion_vr and abs(z) >= p.z_entry:
        regime = "mean_reversion"
        if z > 0:
            signal, direction = "sell", "short"
            reason = f"均值回归：z={z:.2f}，VR={vr:.2f}，价格高于均值"
        else:
            signal, direction = "buy", "long"
            reason = f"均值回归：z={z:.2f}，VR={vr:.2f}，价格低于均值"
        strength = min(1.0, abs(z) / (p.z_entry * 1.8))
    elif vr is not None and vr >= p.breakout_vr and abs(trend_pct) >= p.trend_entry_pct:
        up_break = price >= high * (1.0 + p.breakout_buffer_pct / 100.0)
        down_break = price <= low * (1.0 - p.breakout_buffer_pct / 100.0)
        if up_break and trend_pct > 0:
            regime = "breakout"
            signal, direction = "buy", "long"
            strength = min(1.0, abs(trend_pct) / (p.trend_entry_pct * 2.5))
            reason = f"趋势突破：trend={trend_pct:.3f}%，VR={vr:.2f}，突破上沿"
        elif down_break and trend_pct < 0:
            regime = "breakout"
            signal, direction = "sell", "short"
            strength = min(1.0, abs(trend_pct) / (p.trend_entry_pct * 2.5))
            reason = f"趋势突破：trend={trend_pct:.3f}%，VR={vr:.2f}，跌破下沿"

    position_pct = 0.0
    if direction != "flat":
        position_pct = p.min_position_pct + (p.max_position_pct - p.min_position_pct) * strength

    return {
        "signal": signal,
        "direction": direction,
        "positionPct": round(position_pct * 100.0, 2),
        "regime": regime,
        "reason": reason,
        "price": round(price, 4),
        "zScore": round(z, 4),
        "trendPct": round(trend_pct, 4),
        "varianceRatio": round(vr, 4) if vr is not None else None,
        "risk": {
            "stopLossPct": p.stop_loss_pct,
            "takeProfitPct": p.take_profit_pct,
            "trailingTriggerPct": p.trailing_trigger_pct,
            "trailingRetracePct": p.trailing_retrace_pct,
            "maxHoldTicks": p.max_hold_ticks,
        },
    }


def calc_xag_live_signal(
    ticks: list[dict[str, float | int]],
    params: XAGLiveParams | None = None,
) -> dict[str, Any]:
    """用最近 tick 计算实盘信号。

    信号分两类：
    - 均值回归：VR 偏低时，对 z-score 极端偏离做反向；
    - 突破跟随：VR 偏高且价格突破通道时，顺势进场。
    """

    p = params or XAGLiveParams()
    xs = clean_xag_ticks(ticks)
    return _signal_from_prices([float(x["y"]) for x in xs], p)


def _pnl_pct(direction: str, entry: float, price: float) -> float:
    if direction == "long":
        return (price - entry) / entry * 100.0
    if direction == "short":
        return (entry - price) / entry * 100.0
    return 0.0


def simulate_xag_live_strategy(
    ticks: list[dict[str, float | int]],
    params: XAGLiveParams | None = None,
    round_trip_cost_pct: float = 0.008,
    signal_step: int = 1,
) -> dict[str, Any]:
    """按实盘顺序模拟策略，不使用未来数据。"""

    p = params or XAGLiveParams()
    xs = clean_xag_ticks(ticks)
    prices = [float(x["y"]) for x in xs]
    active: dict[str, Any] | None = None
    trades: list[XAGLiveTrade] = []
    cooldown = 0
    warmup = max(p.min_ticks, p.mean_window + 2, p.channel_window + 2, p.vr_window + 2)

    for i, tick in enumerate(xs):
        price = float(tick["y"])
        ts = int(tick["t"])
        if active is not None:
            pnl = _pnl_pct(active["direction"], active["entry_price"], price)
            active["mfe"] = max(active["mfe"], pnl)
            hold = i - active["entry_i"]
            exit_reason = None
            if pnl <= -p.stop_loss_pct:
                exit_reason = "stop_loss"
            elif pnl >= p.take_profit_pct:
                exit_reason = "take_profit"
            elif active["mfe"] >= p.trailing_trigger_pct and pnl <= active["mfe"] - p.trailing_retrace_pct:
                exit_reason = "trailing_stop"
            elif hold >= p.max_hold_ticks:
                exit_reason = "time_stop"

            if exit_reason:
                trades.append(
                    XAGLiveTrade(
                        entry_t=active["entry_t"],
                        exit_t=ts,
                        direction=active["direction"],
                        entry_price=active["entry_price"],
                        exit_price=price,
                        pnl_pct=round(pnl - round_trip_cost_pct, 5),
                        hold_ticks=hold,
                        reason=exit_reason,
                    )
                )
                active = None
                cooldown = p.cooldown_ticks
            continue

        if i < warmup:
            continue
        if cooldown > 0:
            cooldown -= 1
            continue
        if signal_step > 1 and i % signal_step != 0:
            continue

        start = max(0, i - warmup * 2)
        sig = _signal_from_prices(prices[start : i + 1], p)
        if sig["direction"] in ("long", "short"):
            active = {
                "entry_i": i,
                "entry_t": ts,
                "entry_price": price,
                "direction": sig["direction"],
                "mfe": 0.0,
            }

    if active is not None and xs:
        last = xs[-1]
        price = float(last["y"])
        pnl = _pnl_pct(active["direction"], active["entry_price"], price)
        trades.append(
            XAGLiveTrade(
                entry_t=active["entry_t"],
                exit_t=int(last["t"]),
                direction=active["direction"],
                entry_price=active["entry_price"],
                exit_price=price,
                pnl_pct=round(pnl - round_trip_cost_pct, 5),
                hold_ticks=len(xs) - 1 - active["entry_i"],
                reason="close",
            )
        )

    return {
        "params": asdict(p),
        "metrics": evaluate_xag_trades(trades),
        "trades": [asdict(t) for t in trades],
    }


def evaluate_xag_trades(trades: list[XAGLiveTrade] | list[dict[str, Any]]) -> dict[str, Any]:
    """汇总纸交易绩效。"""

    pnls = [float(t.pnl_pct if isinstance(t, XAGLiveTrade) else t.get("pnl_pct", 0.0)) for t in trades]
    if not pnls:
        return {
            "tradeCount": 0,
            "winRatePct": 0.0,
            "profitFactor": 0.0,
            "totalReturnPct": 0.0,
            "avgPnlPct": 0.0,
            "maxDrawdownPct": 0.0,
        }

    wins = [x for x in pnls if x > 0]
    losses = [-x for x in pnls if x < 0]
    compound = 1.0
    equity = [0.0]
    for x in pnls:
        compound *= 1.0 + x / 100.0
        equity.append(equity[-1] + x)
    peak = equity[0]
    max_dd = 0.0
    for val in equity:
        peak = max(peak, val)
        max_dd = max(max_dd, peak - val)

    return {
        "tradeCount": len(pnls),
        "winRatePct": round(len(wins) / len(pnls) * 100.0, 2),
        "profitFactor": round(sum(wins) / sum(losses), 2) if losses else 999.0,
        "totalReturnPct": round((compound - 1.0) * 100.0, 4),
        "avgPnlPct": round(sum(pnls) / len(pnls), 5),
        "maxDrawdownPct": round(max_dd, 4),
        "bestTradePct": round(max(pnls), 5),
        "worstTradePct": round(min(pnls), 5),
    }


def default_param_grid() -> list[XAGLiveParams]:
    """小网格，供 walk-forward 使用。"""

    out: list[XAGLiveParams] = []
    for z_entry in (1.9, 2.2):
        for trend_entry_pct in (0.05,):
            for stop_loss_pct, take_profit_pct in ((0.08, 0.14), (0.12, 0.24)):
                out.append(
                    XAGLiveParams(
                        z_entry=z_entry,
                        trend_entry_pct=trend_entry_pct,
                        stop_loss_pct=stop_loss_pct,
                        take_profit_pct=take_profit_pct,
                    )
                )
    return out


def walk_forward_xag_validation(
    dates: list[str] | None = None,
    grid: list[XAGLiveParams] | None = None,
) -> dict[str, Any]:
    """按 day[t] 训练、day[t+1] 验证的 walk-forward 报告。"""

    use_dates = dates or load_available_xag_dates()
    params_grid = grid or default_param_grid()
    rows = []
    oos_trades: list[dict[str, Any]] = []
    for idx in range(len(use_dates) - 1):
        train_date = use_dates[idx]
        test_date = use_dates[idx + 1]
        train_ticks = load_xag_ticks_for_date(train_date)
        test_ticks = load_xag_ticks_for_date(test_date)
        best_params = None
        best_metrics = None
        best_score = -1e18
        for params in params_grid:
            result = simulate_xag_live_strategy(train_ticks, params, signal_step=5)
            metrics = result["metrics"]
            if metrics["tradeCount"] < 8:
                continue
            score = (
                metrics["totalReturnPct"] * 2.0
                + metrics["profitFactor"] * 0.5
                - metrics["maxDrawdownPct"] * 1.2
            )
            if score > best_score:
                best_score = score
                best_params = params
                best_metrics = metrics
        if best_params is None:
            continue
        test_result = simulate_xag_live_strategy(test_ticks, best_params, signal_step=5)
        for trade in test_result["trades"]:
            trade["date"] = test_date
        oos_trades.extend(test_result["trades"])
        rows.append(
            {
                "trainDate": train_date,
                "testDate": test_date,
                "bestParams": asdict(best_params),
                "inSampleMetrics": best_metrics,
                "outOfSampleMetrics": test_result["metrics"],
            }
        )

    return {
        "instrument": "xag",
        "dates": use_dates,
        "method": "walk_forward_day_t_to_day_t_plus_1",
        "rows": rows,
        "oosOverall": evaluate_xag_trades(oos_trades),
        "oosTrades": oos_trades,
    }
