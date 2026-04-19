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

import asyncio
import json
import threading
import time
import uuid
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
# Optional websockets import
# ---------------------------------------------------------------------------

_HAS_WEBSOCKETS = False
try:
    import websockets
    _HAS_WEBSOCKETS = True
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

# ---------------------------------------------------------------------------
# Thread-safe cache — crypto
# ---------------------------------------------------------------------------

_crypto_lock = threading.Lock()
_crypto_quotes: dict[str, dict] = {}
_crypto_connected = False
_crypto_stop_event = threading.Event()
_crypto_thread: threading.Thread | None = None

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
# WebSocket background runner
# ---------------------------------------------------------------------------

async def _ws_loop(url: str, symbols: list[str], stop_event: threading.Event,
                   on_trade, set_connected):
    backoff = 1.0

    def _trace():
        return uuid.uuid4().hex[:12]

    while not stop_event.is_set():
        try:
            async with websockets.connect(url, close_timeout=5) as ws:
                set_connected(True)
                backoff = 1.0
                log.info(f"[Infoway] WebSocket connected: {url[:60]}...")

                # drain greeting
                try:
                    init = await asyncio.wait_for(ws.recv(), timeout=5)
                    log.debug(f"[Infoway/init] {str(init)[:200]}")
                except asyncio.TimeoutError:
                    pass

                # subscribe trade
                codes = ",".join(symbols)
                await ws.send(json.dumps({
                    "code": 10000,
                    "trace": _trace(),
                    "data": {"codes": codes},
                }))
                log.info(f"[Infoway] Subscribed trade: {codes}")

                # heartbeat + message loop
                async def _heartbeat():
                    while not stop_event.is_set():
                        try:
                            await ws.send(json.dumps({"code": 10010, "trace": _trace()}))
                        except Exception:
                            return
                        await asyncio.sleep(30)

                async def _recv():
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            code = msg.get("code")
                            if code in (10001, 10002):  # 10001=SUB_ACK/TRADE, 10002=TRADE_PUSH
                                on_trade(msg)
                            elif code == 10010:     # HEARTBEAT
                                pass
                            else:
                                log.debug(f"[Infoway/WS] code={code}")
                        except json.JSONDecodeError:
                            pass

                await asyncio.gather(_heartbeat(), _recv())
        except Exception as exc:
            set_connected(False)
            if stop_event.is_set():
                break
            log.warning(f"[Infoway] WS error: {exc}, reconnecting in {backoff:.0f}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    set_connected(False)


def _make_on_trade(lock: threading.Lock, quotes: dict):
    """创建 trade 处理回调，绑定到指定的 lock 和 quotes 缓存。"""
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
            if not symbol or not price or price <= 0:
                continue
            quote = {
                "symbol": symbol,
                "price": price,
                "high": _flt(item.get("h") or item.get("high")),
                "low": _flt(item.get("l") or item.get("low")),
                "open": _flt(item.get("o") or item.get("open")),
                "prev_close": _flt(item.get("pc") or item.get("preClose")),
                "volume": _flt(item.get("v") or item.get("volume")),
                "timestamp": int(_flt(item.get("t") or item.get("time")) or time.time() * 1000),
                "_raw_ts": time.time(),
            }
            with lock:
                quotes[symbol.upper()] = quote
            log.debug(f"[Infoway/trade] {symbol}={price}")
    return _on_trade


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
    on_trade = _make_on_trade(_lock, _quotes)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_ws_loop(url, symbols, _stop_event, on_trade,
                                         lambda v: _set_connected("common", v)))
    finally:
        loop.close()


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
    on_trade = _make_on_trade(_crypto_lock, _crypto_quotes)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_ws_loop(url, symbols, _crypto_stop_event, on_trade,
                                         lambda v: _set_connected("crypto", v)))
    finally:
        loop.close()


def _set_connected(which: str, value: bool):
    global _connected, _crypto_connected
    if which == "common":
        _connected = value
    else:
        _crypto_connected = value


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def infoway_start():
    global _thread
    cfg = _cfg()
    if not cfg.get("enabled"):
        log.info("[Infoway] Disabled in config")
        return
    if not _HAS_WEBSOCKETS:
        log.warning("[Infoway] websockets not installed, run: pip install websockets")
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
    if not _HAS_WEBSOCKETS:
        log.warning("[Infoway/crypto] websockets not installed")
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
        "volume": 0,
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
