import json
import queue
import random
import socketserver
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler

from backend.backtest import (
    BacktestConfig, load_history, momentum_params_from_body, backtest_config_from_body,
    run_momentum_backtest, run_momentum_long_only_backtest, run_grid_search, run_walk_forward,
    reversal_params_from_body, run_reversal_backtest,
)
from backend.config import CST, FAST_POLL, RUNTIME_CONFIG, SLOW_POLL, log, reload_runtime_config
from backend.infoway import infoway_available, infoway_crypto_available
from backend.strategies.momentum import MomentumParams, calc_momentum
from backend.instruments import CATEGORIES, REGISTRY, registry_to_json
from backend.pollers import sync_precious_to_instrument_caches, SOURCE_REGISTRY, SOURCE_LABELS
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
        if path == "/api/stream":
            self._handle_sse()
            return
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
        if path == "/api/config/reload":
            self._handle_config_reload()
            return
        if path == "/api/backtest/grid-search":
            self._handle_grid_search()
            return
        if path == "/api/backtest/walk-forward":
            self._handle_walk_forward()
            return
        if path == "/api/admin/clear-cache":
            self._handle_admin_clear_cache()
            return
        if path == "/api/admin/test-sources":
            self._handle_admin_test_sources()
            return
        if path == "/api/admin/source-config":
            self._handle_admin_source_config_post()
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
        """POST /api/threshold — 支持全局阈值或分品种阈值。

        请求体:
          {"threshold": 0.15}                          — 设置全局默认阈值
          {"thresholds": {"hu": 0.15, "comex": 0.10}}  — 设置分品种阈值
          两者可同时传入。
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}

            valid_markets = {"hu", "comex", "hujin", "comex_gold", "btc"}

            # 全局阈值
            if "threshold" in body:
                val = float(body["threshold"])
                if val < 0.0 or val > 5.0:
                    raise ValueError("threshold must be between 0 and 5")
                state.tick_jump_threshold = round(val, 3)

            # 分品种阈值
            if "thresholds" in body:
                per = body["thresholds"]
                if not isinstance(per, dict):
                    raise ValueError("thresholds must be a dict")
                for market, v in per.items():
                    if market not in valid_markets:
                        raise ValueError(f"未知品种: {market}, 可选: {valid_markets}")
                    fv = float(v)
                    if fv < 0.0 or fv > 5.0:
                        raise ValueError(f"{market}: threshold must be between 0 and 5")
                    state.tick_jump_thresholds[market] = round(fv, 3)

            log.info(f"[Config] Alert thresholds updated: global={state.tick_jump_threshold}%, per-market={state.tick_jump_thresholds}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "threshold": state.tick_jump_threshold,
                "thresholds": state.tick_jump_thresholds,
            }, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

    def _handle_backtest(self):
        """POST /api/backtest — 执行策略回测。

        请求体字段：strategy, symbol, mode, params(可选), data_source(可选), lookback_minutes(可选)
        返回：权益曲线、成交记录、绩效指标。
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            strategy = (body.get("strategy") or "").strip().lower()
            symbol = (body.get("symbol") or "").strip().lower()
            mode = (body.get("mode") or "long_only").strip().lower()
            data_source = (body.get("data_source") or "history").strip().lower()
            lookback_minutes = int(body.get("lookback_minutes", 5))

            if strategy not in ("momentum", "reversal"):
                raise ValueError("strategy must be momentum or reversal")
            if mode not in ("long_only", "long_short"):
                raise ValueError("mode must be long_only or long_short")
            if data_source not in ("history", "realtime"):
                raise ValueError("data_source must be history or realtime")
            if lookback_minutes < 1 or lookback_minutes > 60:
                raise ValueError("lookback_minutes must be between 1 and 60")

            if data_source == "realtime":
                from backend.backtest import load_realtime_bars
                bars, interval, hist_err = load_realtime_bars(symbol, lookback_minutes)
            else:
                bars, interval, hist_err = load_history(symbol)

            if hist_err == "unknown_symbol":
                raise ValueError(f"unknown symbol: {symbol}")
            if hist_err == "no_history" or not bars:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "no_history"}).encode())
                return

            bt_cfg = backtest_config_from_body(body)
            if strategy == "reversal":
                params = reversal_params_from_body(body, symbol)
                result = run_reversal_backtest(bars, params, bt_cfg)
            else:
                params = momentum_params_from_body(body, symbol)
                result = run_momentum_backtest(bars, params, bt_cfg)
            t0 = int(bars[0]["t"])
            t1 = int(bars[-1]["t"])
            meta = {
                "symbol": symbol,
                "strategy": strategy,
                "mode": mode,
                "dataSource": data_source,
                "lookbackMinutes": lookback_minutes if data_source == "realtime" else None,
                "interval": interval,
                "bars": len(bars),
                "fromMs": t0,
                "toMs": t1,
                "from": datetime.fromtimestamp(t0 / 1000.0, tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
                "to": datetime.fromtimestamp(t1 / 1000.0, tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
                "costModel": "commission+slippage" if (bt_cfg.commission_rate > 0 or bt_cfg.slippage_pct > 0) else "none",
                "commissionRate": bt_cfg.commission_rate,
                "slippagePct": bt_cfg.slippage_pct,
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

    def _handle_config_reload(self):
        try:
            cfg = reload_runtime_config()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "config": cfg}, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:
            log.warning(f"[config/reload] {exc}")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode())

    def _handle_grid_search(self):
        """POST /api/backtest/grid-search — 参数网格搜索。
        遍历参数组合，返回每组参数的绩效摘要。
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            symbol = (body.get("symbol") or "").strip().lower()
            grid = body.get("grid", {})
            if not grid:
                raise ValueError("grid parameter is required")
            bars, interval, hist_err = load_history(symbol)
            if hist_err or not bars:
                raise ValueError(f"cannot load history: {hist_err or 'empty'}")
            base_params = body.get("base_params", {})
            bt_cfg = backtest_config_from_body(body)
            top_n = int(body.get("top_n", 10))
            results = run_grid_search(bars, grid, base_params, bt_cfg, top_n)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True, "results": results, "total_combinations": len(results),
                "symbol": symbol, "interval": interval,
            }, ensure_ascii=False, default=str).encode("utf-8"))
        except Exception as exc:
            log.warning(f"[grid-search] {exc}")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode())

    def _handle_walk_forward(self):
        """POST /api/backtest/walk-forward — Walk-Forward 分析。
        分段回测：前段优化参数，后段验证，避免过拟合。
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            symbol = (body.get("symbol") or "").strip().lower()
            bars, interval, hist_err = load_history(symbol)
            if hist_err or not bars:
                raise ValueError(f"cannot load history: {hist_err or 'empty'}")
            params = momentum_params_from_body(body, symbol)
            bt_cfg = backtest_config_from_body(body)
            train_ratio = float(body.get("train_ratio", 0.7))
            result = run_walk_forward(bars, params, bt_cfg, train_ratio)
            if "error" in result:
                raise ValueError(result["error"])
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, **result, "symbol": symbol, "interval": interval},
                                        ensure_ascii=False, default=str).encode("utf-8"))
        except Exception as exc:
            log.warning(f"[walk-forward] {exc}")
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
        """POST /api/research/monte-carlo — 蒙特卡洛模拟。
        基于历史收益分布生成随机路径，评估策略稳健性。
        """
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

    # ── Admin handlers ───────────────────────────────────────────────

    def _handle_admin_clear_cache(self):
        """POST /api/admin/clear-cache — 清理所有缓存和信号状态。"""
        try:
            with state.cache_lock:
                for c in (state.silver_cache, state.comex_silver_cache,
                          state.gold_cache, state.comex_gold_cache,
                          state.btc_cache, state.combined_cache):
                    c["data"] = None
                    c["ts"] = 0
                state.instrument_caches.clear()
                state.instrument_price_buffers.clear()
                state.instrument_signals.clear()
                state.instrument_reversal_signals.clear()
            with state.alerts_lock:
                state.silver_tick_ring.clear()
                state.comex_silver_tick_ring.clear()
                state.gold_tick_ring.clear()
                state.comex_gold_tick_ring.clear()
                state.btc_tick_ring.clear()
                state.alert_history.clear()
                state.alert_stats = {
                    k: {"surge": 0, "drop": 0, "maxJump": 0}
                    for k in state.alert_stats
                }
            state.huyin_research_samples.clear()
            log.info("[Admin] All caches cleared")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "message": "所有缓存已清除"}).encode("utf-8"))
        except Exception as exc:
            log.warning(f"[Admin] clear-cache error: {exc}")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))

    def _handle_admin_test_sources(self):
        results = []
        # --- Sina ---
        try:
            t0 = time.time()
            from backend.sources import fetch_usdcny_sina
            rate = fetch_usdcny_sina()
            elapsed = round((time.time() - t0) * 1000)
            if rate and rate > 0:
                results.append({"source": "Sina", "ok": True, "latency_ms": elapsed,
                                "detail": f"USD/CNY = {rate:.4f}"})
            else:
                results.append({"source": "Sina", "ok": False, "latency_ms": elapsed,
                                "detail": "返回数据为空"})
        except Exception as exc:
            results.append({"source": "Sina", "ok": False, "latency_ms": 0,
                            "detail": str(exc)})

        # --- iFinD ---
        try:
            from backend.ifind import client as ifind_client
            t0 = time.time()
            logged_in = ifind_client.ensure_login()
            if not logged_in:
                results.append({"source": "iFinD", "ok": False, "latency_ms": 0,
                                "detail": "登录失败"})
            else:
                row = ifind_client.realtime_quote("XAUUSD.FX", "latest;change;changeRatio")
                elapsed = round((time.time() - t0) * 1000)
                if row and row.get("latest"):
                    price = row["latest"]
                    results.append({"source": "iFinD", "ok": True, "latency_ms": elapsed,
                                    "detail": f"mode={ifind_client._mode}, XAU={price}"})
                else:
                    results.append({"source": "iFinD", "ok": True, "latency_ms": elapsed,
                                    "detail": f"mode={ifind_client._mode}, 已登录但XAU暂无数据(可能休市)"})
        except Exception as exc:
            results.append({"source": "iFinD", "ok": False, "latency_ms": 0,
                            "detail": str(exc)})

        # --- Infoway (common) ---
        try:
            is_connected = infoway_available()
            results.append({"source": "Infoway-贵金属", "ok": is_connected,
                            "latency_ms": 0,
                            "detail": "WebSocket 已连接" if is_connected else "WebSocket 未连接"})
        except Exception as exc:
            results.append({"source": "Infoway-贵金属", "ok": False,
                            "latency_ms": 0, "detail": str(exc)})

        # --- Infoway (crypto) ---
        try:
            is_connected = infoway_crypto_available()
            results.append({"source": "Infoway-加密货币", "ok": is_connected,
                            "latency_ms": 0,
                            "detail": "WebSocket 已连接" if is_connected else "WebSocket 未连接"})
        except Exception as exc:
            results.append({"source": "Infoway-加密货币", "ok": False,
                            "latency_ms": 0, "detail": str(exc)})

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "results": results}, ensure_ascii=False).encode("utf-8"))

    def _api_source_config(self):
        """GET /api/admin/source-config — 返回数据源矩阵配置。"""
        return {
            "registry": SOURCE_REGISTRY,
            "labels": SOURCE_LABELS,
            "priority": state.source_priority,
        }

    def _handle_admin_source_config_post(self):
        """POST /api/admin/source-config — 更新数据源优先级。"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            new_priority = body.get("priority")
            if not isinstance(new_priority, dict):
                raise ValueError("priority must be a dict")

            # 校验每个品种的数据源列表
            for inst_id, sources in new_priority.items():
                if inst_id not in SOURCE_REGISTRY:
                    raise ValueError(f"未知品种: {inst_id}")
                if not isinstance(sources, list) or len(sources) == 0:
                    raise ValueError(f"{inst_id}: 至少需要一个数据源")
                valid = SOURCE_REGISTRY[inst_id]["sources"]
                for s in sources:
                    if s not in valid:
                        raise ValueError(f"{inst_id}: 无效数据源 '{s}', 可选: {valid}")

            with state.cache_lock:
                state.source_priority.update(new_priority)

            log.info(f"[Admin] Source priority updated: {new_priority}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "priority": state.source_priority,
            }, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:
            log.warning(f"[Admin] source-config error: {exc}")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8"))

    # ── GET API route handlers ──────────────────────────────────────────

    def _api_status(self):
        return {
            "status": "running",
            "fastPoll": FAST_POLL,
            "slowPoll": SLOW_POLL,
            "comexCacheAge": round(time.time() - state.comex_silver_cache.get("ts", 0), 1),
            "huyinCacheAge": round(time.time() - state.silver_cache.get("ts", 0), 1),
            "hujinCacheAge": round(time.time() - state.gold_cache.get("ts", 0), 1),
            "comexGoldCacheAge": round(time.time() - state.comex_gold_cache.get("ts", 0), 1),
            "hasInfoway": infoway_available(),
            "serverTime": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _api_alerts(self):
        with state.alerts_lock:
            alerts = list(state.alert_history)
            stats = dict(state.alert_stats)
            hu_ring = list(state.silver_tick_ring)
            co_ring = list(state.comex_silver_tick_ring)
            au_ring = list(state.gold_tick_ring)
            cg_ring = list(state.comex_gold_tick_ring)
        return {
            "alerts": alerts,
            "count": len(alerts),
            "threshold": state.tick_jump_threshold,
            "thresholds": dict(state.tick_jump_thresholds),
            "stats": stats,
            "huTickRing": hu_ring,
            "comexTickRing": co_ring,
            "hujinTickRing": au_ring,
            "comexGoldTickRing": cg_ring,
        }

    def _api_instruments(self):
        sync_precious_to_instrument_caches()
        with state.cache_lock:
            caches_snap = dict(state.instrument_caches)
            signals_snap = dict(state.instrument_signals)
        instruments = []
        for inst_id, inst in REGISTRY.items():
            cache = caches_snap.get(inst_id, {})
            d = cache.get("data") or {}
            entry = {
                "id": inst_id,
                "name": inst.name,
                "category": inst.category,
                "exchange": inst.exchange,
                "currency": inst.currency,
                "unit": inst.unit,
                "decimals": inst.decimals,
                "color": inst.color,
                "price": d.get("price"),
                "prevClose": d.get("prevClose"),
                "change": d.get("change"),
                "changePercent": d.get("changePercent"),
                "open": d.get("open"),
                "high": d.get("high"),
                "low": d.get("low"),
                "volume": d.get("volume"),
                "timestamp": d.get("timestamp"),
                "datetime_cst": d.get("datetime_cst"),
                "closed": d.get("closed", False),
            }
            sig = signals_snap.get(inst_id)
            if sig:
                entry["signal"] = sig.get("signal")
                entry["signalStrength"] = sig.get("strength")
                entry["signalInfo"] = sig
            instruments.append(entry)
        return {"instruments": instruments, "categories": CATEGORIES}

    def _api_sources(self):
        return {
            "available": [
                {"id": "sina-ag0", "name": "Sina AG0", "type": "沪银实时", "authRequired": False, "status": "active"},
                {"id": "sina-xag", "name": "Sina XAG", "type": "COMEX银实时", "authRequired": False, "status": "active"},
                {"id": "sina-au0", "name": "Sina AU0", "type": "沪金实时", "authRequired": False, "status": "active"},
                {"id": "sina-xau", "name": "Sina XAU", "type": "COMEX金实时", "authRequired": False, "status": "active"},
                {
                    "id": "infoway",
                    "name": "Infoway WebSocket",
                    "type": "COMEX银/金实时推送",
                    "authRequired": True,
                    "status": "active" if infoway_available() else "disconnected",
                },
                {
                    "id": "infoway-crypto",
                    "name": "Infoway Crypto WebSocket",
                    "type": "加密货币实时推送",
                    "authRequired": True,
                    "status": "active" if infoway_crypto_available() else "disconnected",
                },
            ]
        }

    def _api_comex(self):
        return state.comex_silver_cache.get("data")

    def _api_huyin(self):
        return state.silver_cache.get("data")

    def _api_hujin(self):
        return state.gold_cache.get("data")

    def _api_comex_gold(self):
        return state.comex_gold_cache.get("data")

    def _api_btc(self):
        return state.btc_cache.get("data")

    def _api_all(self):
        """GET /api/all — 聚合所有品种的实时数据、信号和价差。

        返回：行情快照、动量信号、反转信号、价格缓冲、价差、波动率等。
        """
        data = dict(state.combined_cache.get("data") or {})
        with state.cache_lock:
            signals_snap = dict(state.instrument_signals)
            rv_signals_snap = dict(state.instrument_reversal_signals)
            price_bufs = {k: v[-60:] for k, v in state.instrument_price_buffers.items() if len(v) >= 2}
            rt_bufs = {k: v[-60:] for k, v in state.realtime_backtest_buffers.items() if len(v) >= 2}
        signals = {}
        rv_signals = {}
        for inst_id in ("ag0", "xag", "au0", "xau", "btc"):
            sig = signals_snap.get(inst_id)
            if sig:
                signals[inst_id] = sig
            rv_sig = rv_signals_snap.get(inst_id)
            if rv_sig:
                rv_signals[inst_id] = rv_sig
        if signals:
            data["signals"] = signals
        data["reversalSignals"] = rv_signals
        data["priceBuffers"] = price_bufs
        data["realtimeBacktestBuffers"] = rt_bufs
        return data

    def _api_instruments_registry(self):
        return {"registry": registry_to_json(), "categories": CATEGORIES}

    _GET_ROUTES = {
        "/api/comex": _api_comex,
        "/api/huyin": _api_huyin,
        "/api/ag": _api_huyin,
        "/api/silver": _api_huyin,
        "/api/hujin": _api_hujin,
        "/api/comex_gold": _api_comex_gold,
        "/api/btc": _api_btc,
        "/api/all": _api_all,
        "/api/status": _api_status,
        "/api/alerts": _api_alerts,
        "/api/research/huyin": _research_huyin_context,
        "/api/instruments": _api_instruments,
        "/api/instruments/registry": _api_instruments_registry,
        "/api/sources": _api_sources,
        "/api/admin/source-config": _api_source_config,
    }

    # ── GET API dispatch ─────────────────────────────────────────────

    def _send_json_api(self, path):
        handler = self._GET_ROUTES.get(path)
        if handler:
            data = handler(self)
        elif path.startswith("/api/instrument/"):
            inst_id = path.split("/")[-1]
            with state.cache_lock:
                cache = state.instrument_caches.get(inst_id, {})
                data = cache.get("data") or {"error": "not_found", "id": inst_id}
        else:
            data = {"error": "not_found", "path": path}

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def _handle_sse(self):
        """Server-Sent Events 长连接：推送实时数据变更。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")  # nginx 兼容
        super().end_headers()  # 跳过自定义 end_headers 避免重复 CORS

        q: queue.SimpleQueue = queue.SimpleQueue()
        with state.sse_lock:
            state.sse_queues.add(q)
        try:
            # 发送初始连接确认
            self.wfile.write(b"event: connected\ndata: {\"ok\":true}\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # 心跳保活
                    self.wfile.write(f": heartbeat {int(time.time())}\n\n".encode("utf-8"))
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with state.sse_lock:
                state.sse_queues.discard(q)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass
