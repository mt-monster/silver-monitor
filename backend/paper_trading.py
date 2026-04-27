"""实盘纸交易追踪模块。

信号发出时记录"虚拟开仓"，根据后续价格变化统计信号质量。
提供止损/止盈/时间止损/移动止盈框架，但不涉及真实资金。
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from backend.config import log


@dataclass
class PaperTrade:
    """单笔纸交易记录。"""
    id: str
    instrument_id: str
    entry_time_ms: int
    entry_price: float
    signal: str
    direction: str
    source: str
    exit_time_ms: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl_pct: Optional[float] = None
    holding_seconds: Optional[float] = None
    mae_pct: Optional[float] = None  # 最大不利变动
    mfe_pct: Optional[float] = None  # 最大有利变动


@dataclass
class PaperTradingConfig:
    """纸交易配置，可在 monitor.config.json 的 paper_trading 段覆盖。"""
    stop_loss_pct: float = 0.15       # 止损线 %
    take_profit_pct: float = 0.30     # 止盈线 %
    trailing_trigger_pct: float = 0.10  # 移动止盈触发 %
    trailing_retracement_pct: float = 0.05  # 移动止盈回撤 %
    max_hold_seconds: int = 60        # 最大持仓时间
    max_closed_trades: int = 500      # 最大保留平仓记录数


class PaperTradingTracker:
    """纸交易追踪器。

    每个品种维护一个活跃仓位（active_trade）和已平仓列表（closed_trades）。
    当组合信号变化时，如果方向改变，平掉旧仓位并开新仓位。
    每次价格更新时检查活跃仓位是否触发止损/止盈/移动止盈/时间止损。
    """

    def __init__(self, config: Optional[PaperTradingConfig] = None):
        self.config = config or PaperTradingConfig()
        self.active_trades: dict[str, PaperTrade] = {}  # instrument_id -> PaperTrade
        self.closed_trades: list[PaperTrade] = []
        self._lock = threading.Lock()
        self._trade_counter = 0

    def _next_id(self) -> str:
        self._trade_counter += 1
        return f"pt-{self._trade_counter}-{int(time.time()*1000)}"

    # ── 信号驱动 ──────────────────────────────────────────────

    def on_combined_signal(self, instrument_id: str, price: float, combined: dict):
        """组合信号变化时调用。方向变化则平仓/开仓。

        Args:
            instrument_id: 品种ID，如 "xag"
            price: 当前价格
            combined: calc_combined_signal 返回值
        """
        signal = combined.get("signal", "neutral")
        source = combined.get("source", "unknown")
        direction = _signal_to_direction(signal)

        if direction == "flat":
            self._close_trade(instrument_id, price, int(time.time() * 1000), "signal_neutral")
            return

        with self._lock:
            active = self.active_trades.get(instrument_id)
            if active:
                active_dir = _signal_to_direction(active.signal)
                if active_dir == direction:
                    # 同方向：若新信号更强则更新
                    if _signal_rank(signal) > _signal_rank(active.signal):
                        active.signal = signal
                        active.source = source
                    return
                else:
                    # 方向翻转：先平仓
                    self._do_close(active, price, int(time.time() * 1000), "signal_reverse")
                    self.active_trades.pop(instrument_id, None)

            # 开新仓
            trade = PaperTrade(
                id=self._next_id(),
                instrument_id=instrument_id,
                entry_time_ms=int(time.time() * 1000),
                entry_price=price,
                signal=signal,
                direction=direction,
                source=source,
            )
            self.active_trades[instrument_id] = trade
            log.info(f"[PaperTrade] OPEN {instrument_id} {signal} @ {price:.4f} src={source}")

    def on_price_tick(self, instrument_id: str, price: float):
        """价格更新时调用，检查活跃仓位的止损/止盈/移动止盈/时间止损。"""
        with self._lock:
            trade = self.active_trades.get(instrument_id)
            if not trade:
                return

            now_ms = int(time.time() * 1000)
            cfg = self.config

            # 计算当前盈亏百分比
            if trade.direction == "long":
                pnl_pct = (price - trade.entry_price) / trade.entry_price * 100
            else:
                pnl_pct = (trade.entry_price - price) / trade.entry_price * 100

            # 更新 MAE / MFE
            trade.mae_pct = min(trade.mae_pct or 0, pnl_pct)
            trade.mfe_pct = max(trade.mfe_pct or 0, pnl_pct)

            # 1) 止损
            if pnl_pct <= -cfg.stop_loss_pct:
                self._do_close(trade, price, now_ms, f"stop_loss({pnl_pct:.2f}%)")
                self.active_trades.pop(instrument_id, None)
                return

            # 2) 止盈
            if pnl_pct >= cfg.take_profit_pct:
                self._do_close(trade, price, now_ms, f"take_profit({pnl_pct:.2f}%)")
                self.active_trades.pop(instrument_id, None)
                return

            # 3) 移动止盈
            if trade.mfe_pct and trade.mfe_pct >= cfg.trailing_trigger_pct:
                trailing_stop = trade.mfe_pct - cfg.trailing_retracement_pct
                if pnl_pct <= trailing_stop:
                    self._do_close(trade, price, now_ms, f"trailing_stop({pnl_pct:.2f}%)")
                    self.active_trades.pop(instrument_id, None)
                    return

            # 4) 时间止损
            hold_sec = (now_ms - trade.entry_time_ms) / 1000
            if hold_sec >= cfg.max_hold_seconds:
                self._do_close(trade, price, now_ms, f"time_stop({hold_sec:.0f}s)")
                self.active_trades.pop(instrument_id, None)
                return

    def _close_trade(self, instrument_id: str, price: float, time_ms: int, reason: str):
        with self._lock:
            trade = self.active_trades.pop(instrument_id, None)
            if trade:
                self._do_close(trade, price, time_ms, reason)

    def _do_close(self, trade: PaperTrade, exit_price: float, exit_time_ms: int, reason: str):
        if trade.direction == "long":
            pnl_pct = (exit_price - trade.entry_price) / trade.entry_price * 100
        else:
            pnl_pct = (trade.entry_price - exit_price) / trade.entry_price * 100

        trade.exit_price = exit_price
        trade.exit_time_ms = exit_time_ms
        trade.exit_reason = reason
        trade.pnl_pct = round(pnl_pct, 4)
        trade.holding_seconds = round((exit_time_ms - trade.entry_time_ms) / 1000, 2)

        self.closed_trades.append(trade)
        # 限制记录数量，避免内存膨胀
        if len(self.closed_trades) > self.config.max_closed_trades:
            self.closed_trades = self.closed_trades[-self.config.max_closed_trades // 2 * 3:]

        log.info(
            f"[PaperTrade] CLOSE {trade.instrument_id} {trade.signal} "
            f"@ {exit_price:.4f} pnl={pnl_pct:+.4f}% reason={reason} hold={trade.holding_seconds:.1f}s"
        )

    # ── 统计查询 ──────────────────────────────────────────────

    def get_stats(self, instrument_id: Optional[str] = None, window_seconds: int = 86400) -> dict:
        """获取指定时间窗口内的统计信息。"""
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - window_seconds * 1000

        with self._lock:
            trades = [
                t for t in self.closed_trades
                if t.exit_time_ms and t.exit_time_ms >= cutoff_ms
                and (instrument_id is None or t.instrument_id == instrument_id)
            ]

            if not trades:
                return {
                    "totalTrades": 0,
                    "winRate": 0.0,
                    "profitFactor": 0.0,
                    "avgPnl": 0.0,
                    "avgHoldSeconds": 0.0,
                    "maxDrawdown": 0.0,
                    "sharpe": 0.0,
                    "totalPnl": 0.0,
                    "trades": [],
                }

            wins = [t for t in trades if (t.pnl_pct or 0) > 0]
            losses = [t for t in trades if (t.pnl_pct or 0) <= 0]

            total_pnl = sum(t.pnl_pct or 0 for t in trades)
            win_pnl = sum(t.pnl_pct or 0 for t in wins)
            loss_pnl = sum(abs(t.pnl_pct or 0) for t in losses)

            avg_hold = sum(t.holding_seconds or 0 for t in trades) / len(trades)

            # 权益曲线与最大回撤
            equity = [0.0]
            for t in trades:
                equity.append(equity[-1] + (t.pnl_pct or 0))
            max_dd = 0.0
            peak = equity[0]
            for val in equity:
                peak = max(peak, val)
                max_dd = max(max_dd, peak - val)

            # 近似夏普比率
            pnls = [t.pnl_pct or 0 for t in trades]
            if len(pnls) > 1:
                mean_pnl = sum(pnls) / len(pnls)
                variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
                std = math.sqrt(variance) if variance > 0 else 0
                sharpe = (mean_pnl / std * math.sqrt(len(pnls))) if std > 0 else 0.0
            else:
                sharpe = 0.0

            return {
                "totalTrades": len(trades),
                "winRate": round(len(wins) / len(trades) * 100, 2),
                "profitFactor": round(win_pnl / loss_pnl, 2) if loss_pnl > 0 else (999.0 if win_pnl > 0 else 0.0),
                "avgPnl": round(total_pnl / len(trades), 4),
                "avgHoldSeconds": round(avg_hold, 2),
                "maxDrawdown": round(max_dd, 4),
                "sharpe": round(sharpe, 2),
                "totalPnl": round(total_pnl, 4),
                "trades": [
                    {
                        "id": t.id,
                        "instrument": t.instrument_id,
                        "signal": t.signal,
                        "direction": t.direction,
                        "entryPrice": t.entry_price,
                        "exitPrice": t.exit_price,
                        "pnlPct": t.pnl_pct,
                        "holdSeconds": t.holding_seconds,
                        "reason": t.exit_reason,
                        "entryTime": t.entry_time_ms,
                        "exitTime": t.exit_time_ms,
                        "mfe": t.mfe_pct,
                        "mae": t.mae_pct,
                    }
                    for t in trades[-50:]
                ],
            }

    def get_active_trades(self) -> list[dict]:
        """获取当前活跃仓位列表。"""
        now_ms = int(time.time() * 1000)
        with self._lock:
            return [
                {
                    "id": t.id,
                    "instrument": t.instrument_id,
                    "signal": t.signal,
                    "direction": t.direction,
                    "entryPrice": t.entry_price,
                    "entryTime": t.entry_time_ms,
                    "holdSeconds": round((now_ms - t.entry_time_ms) / 1000, 1),
                    "source": t.source,
                }
                for t in self.active_trades.values()
            ]

    def get_summary_by_instrument(self, window_seconds: int = 86400) -> dict[str, dict]:
        """按品种汇总统计。"""
        with self._lock:
            instruments = {t.instrument_id for t in self.closed_trades if t.exit_time_ms}
        return {
            iid: self.get_stats(iid, window_seconds)
            for iid in instruments
        }


# ── 辅助函数 ──────────────────────────────────────────────

def _signal_to_direction(signal: str) -> str:
    if signal in ("strong_buy", "buy"):
        return "long"
    if signal in ("strong_sell", "sell"):
        return "short"
    return "flat"


def _signal_rank(signal: str) -> int:
    return {"strong_buy": 4, "buy": 3, "neutral": 2, "sell": 1, "strong_sell": 0}.get(signal, 2)


# ── 全局纸交易追踪器实例 ──────────────────────────────────────────
# 在模块导入时即创建，供 pollers.py 和 http_server.py 直接使用
from backend.config import RUNTIME_CONFIG  # type: ignore[import]  # noqa: E402

_pt_cfg = RUNTIME_CONFIG.get("paper_trading", {})
paper_trading_tracker = PaperTradingTracker(
    PaperTradingConfig(
        stop_loss_pct=float(_pt_cfg.get("stop_loss_pct", 0.15)),
        take_profit_pct=float(_pt_cfg.get("take_profit_pct", 0.30)),
        trailing_trigger_pct=float(_pt_cfg.get("trailing_trigger_pct", 0.10)),
        trailing_retracement_pct=float(_pt_cfg.get("trailing_retracement_pct", 0.05)),
        max_hold_seconds=int(_pt_cfg.get("max_hold_seconds", 60)),
    )
)
