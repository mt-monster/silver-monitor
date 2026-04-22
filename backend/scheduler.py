"""APScheduler 定时任务：每天自动扫描前一天的 5 分钟 tick 窗口最佳绩效。"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config import CST, log

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


def _yesterday_date_str() -> str:
    return (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")


def _daily_scan_job():
    """每日定时任务：扫描 COMEX 银昨天的所有 5 分钟窗口。"""
    date_str = _yesterday_date_str()
    log.info(f"[Scheduler] Starting daily 5-min scan for {date_str}")
    try:
        from backend.backtest_runner import scan_5min_windows
        result = scan_5min_windows(
            instrument_id="xag",
            date_str=date_str,
            strategy="momentum",
            step_ms=30_000,
            param_grid={
                "spread_entry": [0.01, 0.02, 0.03, 0.05],
                "slope_entry": [0.005, 0.01, 0.015, 0.02],
            },
            save_results=True,
        )
        if "error" in result:
            log.warning(f"[Scheduler] Daily scan failed: {result['error']}")
        else:
            best = result.get("best_window")
            if best:
                log.info(
                    f"[Scheduler] Daily scan complete: best={best['start_time']}~{best['end_time']} "
                    f"return={best.get('best_metrics', {}).get('totalReturnPct')}"
                )
            else:
                log.info("[Scheduler] Daily scan complete: no best window found")
    except Exception as exc:
        log.error(f"[Scheduler] Daily scan exception: {exc}")


def start_scheduler() -> BackgroundScheduler | None:
    """启动后台调度器。每天北京时间 04:00 执行（COMEX 收盘后约 1 小时）。"""
    global _scheduler
    with _lock:
        if _scheduler is not None and _scheduler.running:
            log.info("[Scheduler] Already running")
            return _scheduler
        try:
            sched = BackgroundScheduler(timezone=str(CST))
            # 每天 04:00 CST 执行
            sched.add_job(
                _daily_scan_job,
                trigger=CronTrigger(hour=4, minute=0, timezone=str(CST)),
                id="daily_5min_scan",
                replace_existing=True,
            )
            sched.start()
            _scheduler = sched
            log.info("[Scheduler] Started. Daily scan at 04:00 CST.")
            return sched
        except Exception as exc:
            log.error(f"[Scheduler] Failed to start: {exc}")
            return None


def stop_scheduler() -> None:
    """停止调度器。"""
    global _scheduler
    with _lock:
        if _scheduler is not None and _scheduler.running:
            _scheduler.shutdown(wait=False)
            log.info("[Scheduler] Stopped")
        _scheduler = None


def trigger_scan_now(instrument_id: str = "xag", date_str: str | None = None) -> dict:
    """手动触发一次扫描（用于 API 或调试）。"""
    date_str = date_str or _yesterday_date_str()
    from backend.backtest_runner import scan_5min_windows
    return scan_5min_windows(
        instrument_id=instrument_id,
        date_str=date_str,
        strategy="momentum",
        step_ms=30_000,
        param_grid={
            "spread_entry": [0.01, 0.02, 0.03, 0.05],
            "slope_entry": [0.005, 0.01, 0.015, 0.02],
        },
        save_results=True,
    )
