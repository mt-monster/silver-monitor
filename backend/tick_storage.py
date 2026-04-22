"""Tick 数据持久化到 SQLite，支持秒级 tick 写入与按日期/时间段查询。"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ticks.db")
_LOCK = threading.Lock()


def _ensure_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_tick_db() -> None:
    """初始化 tick 数据库表结构。"""
    with _ensure_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                price REAL NOT NULL,
                date_str TEXT NOT NULL,
                created_at REAL DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticks_inst_date ON ticks(instrument_id, date_str)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(instrument_id, timestamp_ms)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_5min_windows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id TEXT NOT NULL,
                date_str TEXT NOT NULL,
                window_start_ms INTEGER NOT NULL,
                window_end_ms INTEGER NOT NULL,
                strategy TEXT NOT NULL,
                params_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                equity_json TEXT,
                trades_json TEXT,
                created_at REAL DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_bt5_inst_date ON backtest_5min_windows(instrument_id, date_str)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_best_window (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id TEXT NOT NULL,
                date_str TEXT NOT NULL,
                strategy TEXT NOT NULL,
                best_window_start_ms INTEGER NOT NULL,
                best_window_end_ms INTEGER NOT NULL,
                best_params_json TEXT NOT NULL,
                best_metrics_json TEXT NOT NULL,
                scan_count INTEGER NOT NULL,
                all_windows_json TEXT,
                created_at REAL DEFAULT (strftime('%s','now')),
                UNIQUE(instrument_id, date_str, strategy)
            )
        """)
        conn.commit()


def save_tick(instrument_id: str, timestamp_ms: int, price: float, date_str: str | None = None) -> None:
    """写入单条 tick（线程安全）。"""
    if date_str is None:
        from datetime import datetime, timezone
        date_str = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).astimezone().strftime("%Y-%m-%d")
    with _LOCK:
        with _ensure_db() as conn:
            conn.execute(
                "INSERT INTO ticks (instrument_id, timestamp_ms, price, date_str) VALUES (?, ?, ?, ?)",
                (instrument_id, timestamp_ms, price, date_str),
            )
            conn.commit()


def save_ticks_batch(records: list[tuple[str, int, float, str]]) -> None:
    """批量写入 tick（线程安全）。"""
    if not records:
        return
    with _LOCK:
        with _ensure_db() as conn:
            conn.executemany(
                "INSERT INTO ticks (instrument_id, timestamp_ms, price, date_str) VALUES (?, ?, ?, ?)",
                records,
            )
            conn.commit()


def get_ticks_for_date(instrument_id: str, date_str: str) -> list[dict[str, Any]]:
    """查询某品种某天的所有 tick，按时间排序。"""
    with _ensure_db() as conn:
        cur = conn.execute(
            "SELECT timestamp_ms, price FROM ticks WHERE instrument_id = ? AND date_str = ? ORDER BY timestamp_ms",
            (instrument_id, date_str),
        )
        return [{"t": row[0], "y": row[1]} for row in cur.fetchall()]


def get_ticks_range(instrument_id: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    """查询某品种某时间范围内的 tick。"""
    with _ensure_db() as conn:
        cur = conn.execute(
            "SELECT timestamp_ms, price FROM ticks WHERE instrument_id = ? AND timestamp_ms >= ? AND timestamp_ms <= ? ORDER BY timestamp_ms",
            (instrument_id, start_ms, end_ms),
        )
        return [{"t": row[0], "y": row[1]} for row in cur.fetchall()]


def get_available_dates(instrument_id: str) -> list[str]:
    """获取某品种有数据的所有日期。"""
    with _ensure_db() as conn:
        cur = conn.execute(
            "SELECT DISTINCT date_str FROM ticks WHERE instrument_id = ? ORDER BY date_str DESC",
            (instrument_id,),
        )
        return [row[0] for row in cur.fetchall()]


def delete_old_ticks(before_date_str: str) -> int:
    """删除指定日期之前的 tick。"""
    with _LOCK:
        with _ensure_db() as conn:
            cur = conn.execute("DELETE FROM ticks WHERE date_str < ?", (before_date_str,))
            conn.commit()
            return cur.rowcount


def save_window_backtest(
    instrument_id: str,
    date_str: str,
    window_start_ms: int,
    window_end_ms: int,
    strategy: str,
    params: dict,
    metrics: dict,
    equity: list[dict] | None = None,
    trades: list[dict] | None = None,
) -> None:
    """保存单个 5 分钟窗口的回测结果。"""
    import json
    with _LOCK:
        with _ensure_db() as conn:
            conn.execute(
                """
                INSERT INTO backtest_5min_windows
                (instrument_id, date_str, window_start_ms, window_end_ms, strategy, params_json, metrics_json, equity_json, trades_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument_id, date_str, window_start_ms, window_end_ms, strategy,
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(metrics, ensure_ascii=False),
                    json.dumps(equity, ensure_ascii=False) if equity else None,
                    json.dumps(trades, ensure_ascii=False) if trades else None,
                ),
            )
            conn.commit()


def save_daily_best(
    instrument_id: str,
    date_str: str,
    strategy: str,
    best_start_ms: int,
    best_end_ms: int,
    best_params: dict,
    best_metrics: dict,
    scan_count: int,
    all_windows: list[dict] | None = None,
) -> None:
    """保存某日最佳窗口结果（UPSERT）。"""
    import json
    with _LOCK:
        with _ensure_db() as conn:
            conn.execute(
                """
                INSERT INTO daily_best_window
                (instrument_id, date_str, strategy, best_window_start_ms, best_window_end_ms,
                 best_params_json, best_metrics_json, scan_count, all_windows_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id, date_str, strategy) DO UPDATE SET
                    best_window_start_ms=excluded.best_window_start_ms,
                    best_window_end_ms=excluded.best_window_end_ms,
                    best_params_json=excluded.best_params_json,
                    best_metrics_json=excluded.best_metrics_json,
                    scan_count=excluded.scan_count,
                    all_windows_json=excluded.all_windows_json,
                    created_at=strftime('%s','now')
                """,
                (
                    instrument_id, date_str, strategy, best_start_ms, best_end_ms,
                    json.dumps(best_params, ensure_ascii=False),
                    json.dumps(best_metrics, ensure_ascii=False),
                    scan_count,
                    json.dumps(all_windows, ensure_ascii=False) if all_windows else None,
                ),
            )
            conn.commit()


def get_daily_best(instrument_id: str, date_str: str, strategy: str = "momentum") -> dict[str, Any] | None:
    """查询某日最佳窗口结果。"""
    import json
    with _ensure_db() as conn:
        cur = conn.execute(
            "SELECT * FROM daily_best_window WHERE instrument_id = ? AND date_str = ? AND strategy = ?",
            (instrument_id, date_str, strategy),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        d = dict(zip(cols, row))
        d["best_params"] = json.loads(d["best_params_json"]) if d.get("best_params_json") else {}
        d["best_metrics"] = json.loads(d["best_metrics_json"]) if d.get("best_metrics_json") else {}
        d["all_windows"] = json.loads(d["all_windows_json"]) if d.get("all_windows_json") else []
        return d


def get_window_results(instrument_id: str, date_str: str, strategy: str = "momentum") -> list[dict[str, Any]]:
    """查询某日所有窗口回测结果。"""
    import json
    with _ensure_db() as conn:
        cur = conn.execute(
            "SELECT * FROM backtest_5min_windows WHERE instrument_id = ? AND date_str = ? AND strategy = ? ORDER BY window_start_ms",
            (instrument_id, date_str, strategy),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        out = []
        for row in rows:
            d = dict(zip(cols, row))
            d["params"] = json.loads(d["params_json"]) if d.get("params_json") else {}
            d["metrics"] = json.loads(d["metrics_json"]) if d.get("metrics_json") else {}
            d["equity"] = json.loads(d["equity_json"]) if d.get("equity_json") else []
            d["trades"] = json.loads(d["trades_json"]) if d.get("trades_json") else []
            out.append(d)
        return out


# 初始化数据库
init_tick_db()
