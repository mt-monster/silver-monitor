import json
import random
import socketserver
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler

from backend.backtest import load_history, momentum_params_from_body, run_momentum_long_only_backtest
from backend.config import CST, FAST_POLL, HAS_AKSHARE, RUNTIME_CONFIG, SLOW_POLL, log
from backend.research.monte_carlo import run_huyin_monte_carlo
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
        if path == "/api/backtest":
            self._handle_backtest()
            return
        if path == "/api/research/monte-carlo":
            self._handle_research_monte_carlo()
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
            if val < 0.0 or val > 5.0:
                raise ValueError("threshold must be between 0 and 5")
            if abs(val * 2 - round(val * 2)) > 1e-9:
                raise ValueError("threshold must be in 0.5 steps")
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

    def _handle_backtest(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            strategy = (body.get("strategy") or "").strip().lower()
            symbol = (body.get("symbol") or "").strip().lower()
            mode = (body.get("mode") or "long_only").strip().lower()

            if strategy != "momentum":
                raise ValueError("only strategy=momentum is supported")
            if mode != "long_only":
                raise ValueError("only mode=long_only is supported")

            bars, interval, hist_err = load_history(symbol)
            if hist_err == "unknown_symbol":
                raise ValueError("unknown symbol; use huyin, comex, hujin, comex_gold")
            if hist_err == "akshare_not_available":
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"ok": False, "error": "akshare_not_available"}).encode()
                )
                return
            if hist_err == "no_history" or not bars:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "no_history"}).encode())
                return

            params = momentum_params_from_body(body)
            result = run_momentum_long_only_backtest(bars, params)
            t0 = int(bars[0]["t"])
            t1 = int(bars[-1]["t"])
            meta = {
                "symbol": symbol,
                "strategy": strategy,
                "mode": mode,
                "interval": interval,
                "bars": len(bars),
                "fromMs": t0,
                "toMs": t1,
                "from": datetime.fromtimestamp(t0 / 1000.0, tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
                "to": datetime.fromtimestamp(t1 / 1000.0, tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
                "costModel": "none",
            }
            payload = {"ok": True, "meta": meta, **result}
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
        except ValueError as exc:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode())
        except Exception as exc:
            log.warning(f"[backtest] {exc}")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode())

    @staticmethod
    def _format_research_mc_error(warns: list[str], min_ret: int, fast_poll_sec: int) -> str:
        if not warns:
            return "数据不足，无法完成模拟。"
        code = warns[0]
        if code == "not_enough_samples_in_window":
            return (
                "回望窗口内几乎没有有效采样点。请确认：① 沪银处于交易时段；② 后端快轮询在运行；"
                "③ 可适当增大「回望窗口（分钟）」后重试。"
            )
        if code == "invalid_last_price":
            return "最新价格无效，请稍后重试。"
        if code == "median_dt_too_small":
            return "采样时间间隔异常（过小），无法换算到秒尺度，请稍后重试。"
        if code.startswith("need_at_least_"):
            got: int | None = None
            for w in warns:
                if w.startswith("got_"):
                    try:
                        got = int(w[4:])
                    except ValueError:
                        pass
            got_s = str(got) if got is not None else "?"
            est_sec = (min_ret + 1) * max(1, fast_poll_sec)
            return (
                f"对数收益条数不足：当前约 {got_s} 条，至少需要 {min_ret} 条。"
                f"快轮询约每 {fast_poll_sec}s 写入一点，通常需连续运行约 {est_sec}s 以上再试。"
                "也可在 monitor.config.json 中调低 research.monte_carlo_min_returns（结果会更噪）。"
            )
        return code

    def _research_huyin_context(self) -> dict:
        cfg = RUNTIME_CONFIG.get("research") or {}
        with state.cache_lock:
            samples = state.huyin_research_samples
            n = len(samples)
            tail = list(samples[-20:]) if samples else []
            hu = dict(state.silver_cache.get("data") or {})
        return {
            "ok": True,
            "sampleCount": n,
            "maxSamples": int(cfg.get("huyin_sample_max", 2000)),
            "closed": bool(hu.get("closed")),
            "lastPrice": float(hu.get("price") or 0),
            "datetimeCst": hu.get("datetime_cst"),
            "monteCarloDefaults": {
                "paths": int(cfg.get("monte_carlo_default_paths", 3000)),
                "maxPaths": int(cfg.get("monte_carlo_max_paths", 50000)),
                "minReturns": int(cfg.get("monte_carlo_min_returns", 15)),
                "histogramBins": int(cfg.get("monte_carlo_histogram_bins", 20)),
                "pathPreviewCount": int(cfg.get("path_preview_count", 40)),
                "pathSteps": int(cfg.get("path_steps", 28)),
            },
            "recentSamples": tail,
        }

    def _handle_research_monte_carlo(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            cfg = RUNTIME_CONFIG.get("research") or {}
            min_ret = int(cfg.get("monte_carlo_min_returns", 15))
            max_paths = int(cfg.get("monte_carlo_max_paths", 50000))
            default_paths = int(cfg.get("monte_carlo_default_paths", 3000))
            hist_bins = int(cfg.get("monte_carlo_histogram_bins", 20))
            path_preview = max(0, min(60, int(body.get("path_preview_count", cfg.get("path_preview_count", 40)))))
            path_st = max(4, min(60, int(body.get("path_steps", cfg.get("path_steps", 28)))))

            horizon = int(body.get("horizon_sec", 1))
            if horizon not in (1, 5):
                raise ValueError("horizon_sec must be 1 or 5")

            paths = int(body.get("paths", default_paths))
            model = (body.get("model") or "gbm").strip().lower()
            if model not in ("gbm", "bootstrap"):
                raise ValueError("model must be gbm or bootstrap")

            drift = (body.get("drift") or "zero").strip().lower()
            if drift not in ("zero", "estimated"):
                raise ValueError("drift must be zero or estimated")

            window_minutes = int(body.get("window_minutes", 120))
            if window_minutes < 5 or window_minutes > 7 * 24 * 60:
                raise ValueError("window_minutes must be between 5 and 10080")

            seed = body.get("seed")
            rng = random.Random(int(seed)) if seed is not None else random.Random()

            with state.cache_lock:
                samples = list(state.huyin_research_samples)

            payload, _warns = run_huyin_monte_carlo(
                samples,
                horizon_sec=horizon,
                paths=paths,
                model=model,  # type: ignore[arg-type]
                drift=drift,  # type: ignore[arg-type]
                window_minutes=window_minutes,
                min_returns=min_ret,
                max_paths=max_paths,
                histogram_bins=hist_bins,
                rng=rng,
                path_preview_count=path_preview,
                path_steps=path_st,
            )
            if payload is None:
                msg = self._format_research_mc_error(_warns, min_ret, FAST_POLL)
                raise ValueError(msg)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
        except ValueError as exc:
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))
        except Exception as exc:
            log.warning(f"[research/monte-carlo] {exc}")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))

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
        elif path == "/api/research/huyin":
            data = self._research_huyin_context()
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
