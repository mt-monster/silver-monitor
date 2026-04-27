"""Infoway (infoway.io) WebSocket 数据源客户端。

提供 WebSocket 实时推送接入，订阅国际商品 trade 数据，
作为 COMEX 白银/黄金的数据源之一（优先级：iFinD > Infoway > Sina）。
同时支持 crypto 业务线（business=crypto），接入 BTC 等加密货币行情。

WebSocket URL: wss://data.infoway.io/ws?business={business}&apikey={api_key}
协议号: 10000=订阅trade, 10001=推送trade, 10002=trade push, 10010=心跳

配置项（monitor.config.json）：
  infoway_ws:        common 业务线（贵金属）
  infoway_ws_crypto: crypto 业务线（加密货币）
"""

import json
import threading
import time
from datetime import datetime

from backend.config import CST, RUNTIME_CONFIG, log

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _cfg() -> dict:
    return RUNTIME_CONFIG.get("infoway_ws") or {}

def _cfg_crypto() -> dict:
    return RUNTIME_CONFIG.get("infoway_ws_crypto") or {}


# ---------------------------------------------------------------------------
# Optional websocket-client import
# ---------------------------------------------------------------------------

_HAS_WS_CLIENT = False
try:
    import websocket
    _HAS_WS_CLIENT = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Thread-safe cache — common (precious metals)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_quotes: dict[str, dict] = {}          # Infoway symbol (upper) → latest quote
_connected = False
_stop_event = threading.Event()
_thread: threading.Thread | None = None

# 逐笔 volume 秒级聚合器：symbol → (current_second_ts, accumulated_volume)
_volume_accumulator: dict[str, tuple[int, float]] = {}

# ---------------------------------------------------------------------------
# Thread-safe cache — crypto
# ---------------------------------------------------------------------------

_crypto_lock = threading.Lock()
_crypto_quotes: dict[str, dict] = {}
_crypto_connected = False
_crypto_stop_event = threading.Event()
_crypto_thread: threading.Thread | None = None

# Crypto 逐笔 volume 秒级聚合器
_crypto_volume_accumulator: dict[str, tuple[int, float]] = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flt(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# WebSocket background runner (同步 websocket-client)
# ---------------------------------------------------------------------------

def _ws_loop_sync(url: str, symbols: list[str], stop_event: threading.Event,
                  on_trade, set_connected):
    """同步 WebSocket 消息循环，使用 websocket-client 库。"""
    import websocket

    def on_message(ws, message):
        try:
            msg = json.loads(message)
            code = msg.get("code")
            if code in (10001, 10002):
                on_trade(msg)
            elif code == 10010:
                pass
            else:
                log.debug(f"[Infoway/WS] code={code}")
        except json.JSONDecodeError:
            pass

    def on_open(ws):
        set_connected(True)
        codes = ",".join(symbols)
        ws.send(json.dumps({
            "code": 10000,
            "trace": "trace",
            "data": {"codes": codes},
        }))
        log.info(f"[Infoway] Subscribed trade: {codes}")

        # 启动心跳线程
        def heartbeat():
            while not stop_event.is_set():
                time.sleep(30)
                try:
                    if ws.sock and ws.sock.connected:
                        ws.send(json.dumps({"code": 10010, "trace": "trace"}))
                except Exception:
                    return
        threading.Thread(target=heartbeat, daemon=True, name="infoway-hb").start()

    def on_close(ws, close_status_code, close_msg):
        set_connected(False)
        log.info(f"[Infoway] Connection closed: {close_status_code} {close_msg}")

    def on_error(ws, error):
        log.warning(f"[Infoway] WS error: {error}")

    backoff = 1.0
    while not stop_event.is_set():
        set_connected(False)
        try:
            ws = websocket.WebSocketApp(
                url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(ping_interval=0)
        except Exception as exc:
            log.warning(f"[Infoway] run_forever error: {exc}")

        if stop_event.is_set():
            break

        log.warning(f"[Infoway] Reconnecting in {backoff:.0f}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, 30.0)

    set_connected(False)


# ---------------------------------------------------------------------------
# Trade callbacks
# ---------------------------------------------------------------------------

def _make_on_trade(lock: threading.Lock, quotes: dict,
                    accumulator: dict[str, tuple[int, float]]):
    """创建 trade 处理回调，绑定到指定的 lock、quotes 缓存和 volume 聚合器。"""
    def _on_trade(msg: dict):
        data = msg.get("data")
        if data is None:
            return
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = item.get("s") or item.get("symbol") or item.get("S", "")
            price = _flt(item.get("p") or item.get("price") or item.get("c"))
            if not symbol or price is None or price <= 0:
                continue
            vol = _flt(item.get("v") or item.get("volume"))
            ts_ms = int(_flt(item.get("t") or item.get("time")) or time.time() * 1000)
            ts_sec = int(ts_ms / 1000)
            sym_upper = symbol.upper()
            # 秒级 volume 聚合
            last_sec, acc = accumulator.get(sym_upper, (0, 0.0))
            if ts_sec != last_sec:
                acc = 0.0
            if vol:
                acc += vol
            accumulator[sym_upper] = (ts_sec, acc)
            quote = {
                "symbol": symbol,
                "price": price,
                "high": _flt(item.get("h") or item.get("high")),
                "low": _flt(item.get("l") or item.get("low")),
                "open": _flt(item.get("o") or item.get("open")),
                "prev_close": _flt(item.get("pc") or item.get("preClose")),
                "volume": acc,   # 当前秒累计成交量
                "timestamp": ts_ms,
                "_raw_ts": time.time(),
            }
            with lock:
                quotes[sym_upper] = quote
            log.debug(f"[Infoway/trade] {symbol}={price} vol={acc}")
    return _on_trade


# symbol_upper -> (lock, quotes, accumulator, which)
_SymbolRegistry = dict[str, tuple[threading.Lock, dict, dict, str]]


def _make_merged_on_trade(registry: _SymbolRegistry):
    """创建合并连接的 trade 回调，按 symbol 分发到对应缓存。"""
    def _on_trade(msg: dict):
        data = msg.get("data")
        if data is None:
            return
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = item.get("s") or item.get("symbol") or item.get("S", "")
            price = _flt(item.get("p") or item.get("price") or item.get("c"))
            if not symbol or price is None or price <= 0:
                continue
            sym_upper = symbol.upper()
            reg = registry.get(sym_upper)
            if not reg:
                continue
            lock, quotes, accumulator, which = reg
            vol = _flt(item.get("v") or item.get("volume"))
            ts_ms = int(_flt(item.get("t") or item.get("time")) or time.time() * 1000)
            ts_sec = int(ts_ms / 1000)
            last_sec, acc = accumulator.get(sym_upper, (0, 0.0))
            if ts_sec != last_sec:
                acc = 0.0
            if vol:
                acc += vol
            accumulator[sym_upper] = (ts_sec, acc)
            quote = {
                "symbol": symbol,
                "price": price,
                "high": _flt(item.get("h") or item.get("high")),
                "low": _flt(item.get("l") or item.get("low")),
                "open": _flt(item.get("o") or item.get("open")),
                "prev_close": _flt(item.get("pc") or item.get("preClose")),
                "volume": acc,
                "timestamp": ts_ms,
                "_raw_ts": time.time(),
            }
            with lock:
                quotes[sym_upper] = quote
            log.debug(f"[Infoway/trade] {symbol}={price} vol={acc}")
    return _on_trade


# ---------------------------------------------------------------------------
# Thread targets
# ---------------------------------------------------------------------------

def _merged_ws_thread_target():
    """合并 common + crypto 的 WebSocket 连接（API key 相同时使用）。"""
    global _connected, _crypto_connected
    cfg_common = _cfg()
    cfg_crypto = _cfg_crypto()
    api_key = cfg_common.get("api_key", "")
    business = cfg_common.get("business", "common")
    sym_common: dict = cfg_common.get("symbols") or {}
    sym_crypto: dict = cfg_crypto.get("symbols") or {}

    # 合并 symbols（去重）— 只使用 common 业务线的 symbols，
    # 因为 Infoway 服务器不支持跨业务线订阅，混用会导致无数据推送。
    all_symbols = list(dict.fromkeys(list(sym_common.values())))
    if not api_key or not all_symbols:
        log.warning("[Infoway] Missing api_key or symbols, merged WS not started")
        return

    # 构建 symbol -> 缓存的映射
    registry: _SymbolRegistry = {}
    for sym in sym_common.values():
        registry[sym.upper()] = (_lock, _quotes, _volume_accumulator, "common")
    for sym in sym_crypto.values():
        registry[sym.upper()] = (_crypto_lock, _crypto_quotes, _crypto_volume_accumulator, "crypto")

    url = f"wss://data.infoway.io/ws?business={business}&apikey={api_key}"
    on_trade = _make_merged_on_trade(registry)

    def set_both(v: bool):
        global _connected, _crypto_connected
        _connected = v
        _crypto_connected = v

    _ws_loop_sync(url, all_symbols, _stop_event, on_trade, set_both)


def _ws_thread_target():
    global _connected
    cfg = _cfg()
    api_key = cfg.get("api_key", "")
    business = cfg.get("business", "common")
    symbol_map: dict = cfg.get("symbols") or {}
    symbols = list(symbol_map.values())

    if not api_key or not symbols:
        log.warning("[Infoway] Missing api_key or symbols, WS not started")
        return

    url = f"wss://data.infoway.io/ws?business={business}&apikey={api_key}"
    on_trade = _make_on_trade(_lock, _quotes, _volume_accumulator)
    _ws_loop_sync(url, symbols, _stop_event, on_trade,
                  lambda v: _set_connected("common", v))


def _crypto_ws_thread_target():
    global _crypto_connected
    cfg = _cfg_crypto()
    api_key = cfg.get("api_key", "")
    business = cfg.get("business", "crypto")
    symbol_map: dict = cfg.get("symbols") or {}
    symbols = list(symbol_map.values())

    if not api_key or not symbols:
        log.warning("[Infoway/crypto] Missing api_key or symbols, crypto WS not started")
        return

    url = f"wss://data.infoway.io/ws?business={business}&apikey={api_key}"
    on_trade = _make_on_trade(_crypto_lock, _crypto_quotes, _crypto_volume_accumulator)
    _ws_loop_sync(url, symbols, _crypto_stop_event, on_trade,
                  lambda v: _set_connected("crypto", v))


def _set_connected(which: str, value: bool):
    global _connected, _crypto_connected
    if which == "common":
        _connected = value
    else:
        _crypto_connected = value


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def _need_merged() -> bool:
    """检测 common 和 crypto 是否使用相同 API key，需要合并连接。"""
    cfg_c = _cfg()
    cfg_cr = _cfg_crypto()
    if not cfg_c.get("enabled") or not cfg_cr.get("enabled"):
        return False
    return cfg_c.get("api_key") == cfg_cr.get("api_key")


def infoway_start():
    global _thread
    cfg = _cfg()
    if not cfg.get("enabled"):
        log.info("[Infoway] Disabled in config")
        return
    if not _HAS_WS_CLIENT:
        log.warning("[Infoway] websocket-client not installed, run: pip install websocket-client")
        return

    if _need_merged():
        if _thread and _thread.is_alive():
            log.info("[Infoway] Merged thread already running")
            return
        _stop_event.clear()
        _crypto_stop_event.clear()
        _thread = threading.Thread(target=_merged_ws_thread_target, daemon=True, name="infoway-merged-ws")
        _thread.start()
        log.info("[Infoway] Merged WebSocket thread started (common+crypto)")
        return

    _stop_event.clear()
    _thread = threading.Thread(target=_ws_thread_target, daemon=True, name="infoway-ws")
    _thread.start()
    log.info("[Infoway] WebSocket thread started (common)")


def infoway_crypto_start():
    global _crypto_thread
    cfg = _cfg_crypto()
    if not cfg.get("enabled"):
        log.info("[Infoway/crypto] Disabled in config")
        return
    if not _HAS_WS_CLIENT:
        log.warning("[Infoway/crypto] websocket-client not installed")
        return

    if _need_merged():
        # 合并模式下由 infoway_start 启动唯一连接
        log.info("[Infoway/crypto] Using merged connection")
        return

    _crypto_stop_event.clear()
    _crypto_thread = threading.Thread(target=_crypto_ws_thread_target, daemon=True, name="infoway-crypto-ws")
    _crypto_thread.start()
    log.info("[Infoway] WebSocket thread started (crypto)")


def infoway_stop():
    global _thread, _crypto_thread
    _stop_event.set()
    _crypto_stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=3)
    _thread = None
    if _crypto_thread and _crypto_thread.is_alive():
        _crypto_thread.join(timeout=3)
    _crypto_thread = None
    # 清空缓存避免 stale 数据
    with _lock:
        _quotes.clear()
        _volume_accumulator.clear()
    with _crypto_lock:
        _crypto_quotes.clear()
        _crypto_volume_accumulator.clear()
    log.info("[Infoway] Stopped (all)")


def infoway_available() -> bool:
    return _connected


def infoway_crypto_available() -> bool:
    return _crypto_connected


# ---------------------------------------------------------------------------
# High-level fetch functions (called by pollers)
# ---------------------------------------------------------------------------

def _get_quote(infoway_symbol: str) -> dict | None:
    with _lock:
        q = _quotes.get(infoway_symbol.upper())
    if not q:
        return None
    # Stale check — 60s
    if time.time() - q.get("_raw_ts", 0) > 60:
        return None
    return q


def _get_crypto_quote(infoway_symbol: str) -> dict | None:
    with _crypto_lock:
        q = _crypto_quotes.get(infoway_symbol.upper())
    if not q:
        return None
    # Stale check — 120s (crypto has lower frequency sometimes)
    if time.time() - q.get("_raw_ts", 0) > 120:
        return None
    return q


def fetch_comex_silver_infoway() -> dict | None:
    cfg = _cfg()
    symbol_map: dict = cfg.get("symbols") or {}
    iw_sym = symbol_map.get("xag", "XAGUSD")
    q = _get_quote(iw_sym)
    if not q:
        return None

    from backend.state import state
    from backend.utils import get_conv

    price_usd = q["price"]
    conv = get_conv()
    usd_cny = state.usd_cny_cache["rate"]
    prev_close = q.get("prev_close") or price_usd
    change = round(price_usd - prev_close, 3)
    change_pct = round(change / prev_close * 100, 2) if prev_close else 0

    return {
        "source": "Infoway-XAG",
        "symbol": "XAG/USD",
        "name": "伦敦银 (XAG Spot)",
        "exchange": "CME/COMEX",
        "currency": "USD",
        "unit": "$/oz",
        "price": round(price_usd, 3),
        "priceCny": round(price_usd * conv, 1),
        "prevClose": round(prev_close, 3),
        "change": change,
        "changePercent": change_pct,
        "open": round(q["open"], 3) if q.get("open") else None,
        "high": round(q["high"], 3) if q.get("high") else None,
        "low": round(q["low"], 3) if q.get("low") else None,
        "volume": int(q.get("volume") or 0),
        "timestamp": q.get("timestamp", int(time.time() * 1000)),
        "datetime_cst": datetime.fromtimestamp(
            q.get("timestamp", time.time() * 1000) / 1000, tz=CST
        ).strftime("%Y-%m-%d %H:%M:%S"),
        "usdCny": usd_cny,
        "convFactor": conv,
    }


def fetch_comex_gold_infoway() -> dict | None:
    cfg = _cfg()
    symbol_map: dict = cfg.get("symbols") or {}
    iw_sym = symbol_map.get("xau", "XAUUSD")
    q = _get_quote(iw_sym)
    if not q:
        return None

    from backend.state import state
    from backend.utils import get_conv_gold

    price_usd = q["price"]
    conv = get_conv_gold()
    usd_cny = state.usd_cny_cache["rate"]
    prev_close = q.get("prev_close") or price_usd
    change = round(price_usd - prev_close, 2)
    change_pct = round(change / prev_close * 100, 2) if prev_close else 0

    return {
        "source": "Infoway-XAU",
        "symbol": "XAU/USD",
        "name": "伦敦金 (XAU Spot)",
        "exchange": "CME/COMEX",
        "currency": "USD",
        "unit": "$/oz",
        "price": round(price_usd, 2),
        "priceCnyG": round(price_usd * conv, 2),
        "prevClose": round(prev_close, 2),
        "change": change,
        "changePercent": change_pct,
        "open": round(q["open"], 2) if q.get("open") else None,
        "high": round(q["high"], 2) if q.get("high") else None,
        "low": round(q["low"], 2) if q.get("low") else None,
        "volume": 0,
        "timestamp": q.get("timestamp", int(time.time() * 1000)),
        "datetime_cst": datetime.fromtimestamp(
            q.get("timestamp", time.time() * 1000) / 1000, tz=CST
        ).strftime("%Y-%m-%d %H:%M:%S"),
        "usdCny": usd_cny,
        "convFactor": conv,
    }


def fetch_btc_infoway() -> dict | None:
    """从 Infoway crypto WS 获取 BTC 最新行情。"""
    cfg = _cfg_crypto()
    symbol_map: dict = cfg.get("symbols") or {}
    iw_sym = symbol_map.get("btc", "BTCUSDT")
    q = _get_crypto_quote(iw_sym)
    if not q:
        return None

    from backend.state import state

    price = q["price"]
    usd_cny = state.usd_cny_cache["rate"]
    prev_close = q.get("prev_close") or price
    change = round(price - prev_close, 2)
    change_pct = round(change / prev_close * 100, 2) if prev_close else 0

    return {
        "source": "Infoway-BTC",
        "symbol": "BTC/USDT",
        "name": "比特币 (BTC)",
        "exchange": "Crypto",
        "currency": "USDT",
        "unit": "$/BTC",
        "price": round(price, 2),
        "priceCny": round(price * usd_cny, 2),
        "prevClose": round(prev_close, 2),
        "change": change,
        "changePercent": change_pct,
        "open": round(q["open"], 2) if q.get("open") else None,
        "high": round(q["high"], 2) if q.get("high") else None,
        "low": round(q["low"], 2) if q.get("low") else None,
        "volume": q.get("volume") or 0,
        "timestamp": q.get("timestamp", int(time.time() * 1000)),
        "datetime_cst": datetime.fromtimestamp(
            q.get("timestamp", time.time() * 1000) / 1000, tz=CST
        ).strftime("%Y-%m-%d %H:%M:%S"),
        "usdCny": usd_cny,
    }
