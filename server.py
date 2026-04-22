"""
Commodity Monitor Server v7.0 — 商品全品类行情监控
=============================================
支持: 贵金属 / 有色金属 / 黑色系 / 能源化工 / 农产品 / 国际
快数据（3秒）: 新浪 Sina 实时行情 + iFinD/Infoway COMEX
慢数据（60秒）: Sina 历史K线 + 新浪汇率
数据源: Sina / iFinD / Infoway WebSocket
所有 API 立即返回缓存数据（非阻塞）

启动: python server.py
访问: http://127.0.0.1:8765/
"""

from backend.bootstrap import prime_caches
from backend.config import FAST_POLL, PORT, SERVER_HOST, SLOW_POLL, log
from backend.http_server import MonitorRequestHandler, ThreadedHttpServer
from backend.infoway import infoway_start, infoway_stop, infoway_crypto_start
from backend.instruments import REGISTRY
from backend.pollers import CommodityPoller, FastDataPoller, SlowDataPoller
from backend.state import state


def build_startup_banner():
    n = len(REGISTRY)
    return f"""
    ══════════════════════════════════════════════════════
       Commodity Monitor Server v7.0
       {n} instruments across 6 categories
    ──────────────────────────────────────────────────────
       Fast poll: {FAST_POLL}s (Precious metals + all commodities)
       Slow poll: {SLOW_POLL}s (Sina history + USDCNY)
       Data: Sina / iFinD / Infoway WS
    ──────────────────────────────────────────────────────
       Alert: 3-Tick jump > {state.tick_jump_threshold:.1f}%
       Bind: {SERVER_HOST}:{PORT}
       Endpoints:
       GET /api/instruments   All commodity prices
       GET /api/instrument/X  Single instrument
       GET /api/all           Precious metals combined
       GET /api/alerts        Alert history
       GET /api/status        Service status
    ══════════════════════════════════════════════════════
    """


def main():
    print(build_startup_banner())
    infoway_start()
    infoway_crypto_start()
    prime_caches()

    fast_poller = FastDataPoller()
    fast_poller.start()
    slow_poller = SlowDataPoller()
    slow_poller.start()
    commodity_poller = CommodityPoller(interval=FAST_POLL)
    commodity_poller.start()

    # 启动定时调度器（每日 04:00 自动扫描昨天 5min 窗口）
    from backend.scheduler import start_scheduler, stop_scheduler
    start_scheduler()

    try:
        server = ThreadedHttpServer((SERVER_HOST, PORT), MonitorRequestHandler)
        log.info(f"Server started: http://127.0.0.1:{PORT}/")
    except OSError as exc:
        log.error(f"Failed to bind port {PORT}: {exc}")
        log.error(f"Is another process using port {PORT}? Run: netstat -ano | findstr :{PORT}")
        raise

    print(f"  Open browser: http://127.0.0.1:{PORT}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Received KeyboardInterrupt, shutting down...")
    except Exception as exc:
        log.error(f"serve_forever crashed: {exc}", exc_info=True)
    finally:
        log.info("Shutting down pollers and server...")
        fast_poller.stop()
        slow_poller.stop()
        commodity_poller.stop()
        fast_poller.join(timeout=3)
        slow_poller.join(timeout=3)
        commodity_poller.join(timeout=3)
        stop_scheduler()
        server.shutdown()
        # Logout iFinD session if active
        try:
            from backend.ifind import client as ifind_client
            ifind_client.logout()
        except Exception:
            pass
        infoway_stop()
        log.info("Server stopped.")


if __name__ == "__main__":
    main()
