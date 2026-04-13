import json
import socketserver
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler

from backend.config import CST, FAST_POLL, HAS_AKSHARE, SLOW_POLL, log
from backend.state import state


class ThreadedHttpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class MonitorRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=".", **kwargs)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            self._send_json_api(path)
            return
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/threshold":
            self._handle_threshold()
            return
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"not_found"}')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle_threshold(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            val = float(body.get("threshold", 0))
            if val < 1.0 or val > 10.0:
                raise ValueError("threshold must be between 1 and 10")
            state.tick_jump_threshold = round(val, 1)
            log.info(f"[Config] Alert threshold changed to {state.tick_jump_threshold}%")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "threshold": state.tick_jump_threshold}).encode())
        except Exception as exc:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

    def _send_json_api(self, path):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

        if path == "/api/comex":
            data = state.comex_silver_cache.get("data")
        elif path in ("/api/huyin", "/api/ag", "/api/silver"):
            data = state.silver_cache.get("data")
        elif path == "/api/hujin":
            data = state.gold_cache.get("data")
        elif path == "/api/comex_gold":
            data = state.comex_gold_cache.get("data")
        elif path == "/api/all":
            data = state.combined_cache.get("data")
        elif path == "/api/status":
            data = {
                "status": "running",
                "fastPoll": FAST_POLL,
                "slowPoll": SLOW_POLL,
                "comexCacheAge": round(time.time() - state.comex_silver_cache.get("ts", 0), 1),
                "huyinCacheAge": round(time.time() - state.silver_cache.get("ts", 0), 1),
                "hujinCacheAge": round(time.time() - state.gold_cache.get("ts", 0), 1),
                "comexGoldCacheAge": round(time.time() - state.comex_gold_cache.get("ts", 0), 1),
                "hasAkshare": HAS_AKSHARE,
                "serverTime": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            }
        elif path == "/api/alerts":
            with state.alerts_lock:
                alerts = list(state.alert_history)
                stats = dict(state.alert_stats)
                hu_ring = list(state.silver_tick_ring)
                co_ring = list(state.comex_silver_tick_ring)
                au_ring = list(state.gold_tick_ring)
                cg_ring = list(state.comex_gold_tick_ring)
            data = {
                "alerts": alerts,
                "count": len(alerts),
                "threshold": state.tick_jump_threshold,
                "stats": stats,
                "huTickRing": hu_ring,
                "comexTickRing": co_ring,
                "hujinTickRing": au_ring,
                "comexGoldTickRing": cg_ring,
            }
        elif path == "/api/sources":
            data = {
                "available": [
                    {"id": "sina-ag0", "name": "Sina AG0", "type": "沪银实时", "authRequired": False, "status": "active"},
                    {"id": "sina-xag", "name": "Sina XAG", "type": "COMEX银实时", "authRequired": False, "status": "active"},
                    {"id": "sina-au0", "name": "Sina AU0", "type": "沪金实时", "authRequired": False, "status": "active"},
                    {"id": "sina-xau", "name": "Sina XAU", "type": "COMEX金实时", "authRequired": False, "status": "active"},
                    {
                        "id": "akshare",
                        "name": "AKShare History",
                        "type": "AG/AU/XAG/XAU history",
                        "authRequired": False,
                        "status": "active" if HAS_AKSHARE else "not_installed",
                    },
                ]
            }
        else:
            data = {"error": "not_found", "path": path}

        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass
