"""
Precious Metal Monitor Server v6.0 — 贵金属行情监控
=============================================
支持: 白银 (AG/XAG) + 黄金 (AU/XAU)
快数据（3秒更新）: 新浪沪银/沪金 + 新浪XAG/XAU
慢数据（60秒更新）: akshare分钟线/日线 + 新浪汇率
所有 API 立即返回缓存数据（非阻塞）
Windows IPv4 专用绑定

启动: python server.py
访问: http://127.0.0.1:8765/
"""

from backend.bootstrap import prime_caches
from backend.config import FAST_POLL, PORT, SERVER_HOST, SLOW_POLL, log
from backend.http_server import MonitorRequestHandler, ThreadedHttpServer
from backend.pollers import FastDataPoller, SlowDataPoller
from backend.state import state


def build_startup_banner():
    return """
    ══════════════════════════════════════════════════════
       Precious Metal Monitor Server v6.0
       Silver (AG/XAG) + Gold (AU/XAU)
    ──────────────────────────────────────────────────────
       Fast poll: %ds (Sina AG0/XAG/AU0/XAU → akshare)
       Slow poll: %ds (akshare history + Sina USDCNY)
    ──────────────────────────────────────────────────────
       Alert: 3-Tick jump > %.1f%%
       Bind: %s:%d
       Endpoints:
       GET /              Frontend
       GET /api/all       Combined (Silver+Gold+Spread+HV)
       GET /api/huyin     HuYin AG JSON
       GET /api/comex     COMEX Silver JSON
       GET /api/hujin     HuJin AU JSON
       GET /api/comex_gold COMEX Gold JSON
       GET /api/alerts    Alert History
       GET /api/status    Service Status
    ══════════════════════════════════════════════════════
    """ % (FAST_POLL, SLOW_POLL, state.tick_jump_threshold, SERVER_HOST, PORT)


def main():
    print(build_startup_banner())
    prime_caches()

    fast_poller = FastDataPoller()
    fast_poller.start()
    slow_poller = SlowDataPoller()
    slow_poller.start()

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
        print("\nShutting down...")
        fast_poller.stop()
        slow_poller.stop()
        fast_poller.join(timeout=3)
        slow_poller.join(timeout=3)
        server.shutdown()
        print("Stopped.")


if __name__ == "__main__":
    main()
