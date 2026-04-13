"""
Silver Monitor Server v5.0 — 生产级完整版
==========================================
快数据（3秒更新）: 东方财富沪银快照 + Stooq COMEX快照
慢数据（60秒更新）: akshare分钟线/日线 + 汇率
所有 API 立即返回缓存数据（非阻塞）
Windows IPv4 专用绑定，避免 IPv6 兼容问题

启动: python server.py
访问: http://127.0.0.1:8765/
"""

import json
import time
import math
import threading
import logging
import socketserver
from datetime import datetime, timezone, timedelta
from http.server import SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import ssl

# ── 配置 ──
PORT = 8765
FAST_POLL = 3       # 快数据轮询（秒）
SLOW_POLL = 60      # 慢数据轮询（秒）

ITICK_TOKEN = ""
METALPRICE_KEY = ""

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# ── 全局缓存 ──
cache_lock = threading.Lock()
comex_cache = {"data": None, "ts": 0}
huyin_cache = {"data": None, "ts": 0}
all_cache = {"data": None, "ts": 0}
usdcny_cache = {"rate": 7.26, "ts": 0}

# ── 预警系统 ──
TICK_JUMP_THRESHOLD = 1.0
ALERT_MAX_HISTORY = 200

hu_tick_ring = []
comex_tick_ring = []
alerts_list = []
alerts_lock = threading.Lock()

alert_stats = {
    "hu": {"surge": 0, "drop": 0, "maxJump": 0},
    "comex": {"surge": 0, "drop": 0, "maxJump": 0},
}

# akshare 初始化
HAS_AKSHARE = False
try:
    import akshare as ak
    HAS_AKSHARE = True
    log.info("akshare loaded OK")
except ImportError:
    log.warning("akshare not installed! Run: pip install akshare")

# 换算常量
OZ_TO_KG = 32.1507


def get_conv():
    """获取当前汇率换算因子（线程安全）"""
    return usdcny_cache["rate"] * OZ_TO_KG


# ══════════════════════════════════════════════════════════
# 快数据源: 东方财富实时快照
# ══════════════════════════════════════════════════════════
def fetch_huyin_eastmoney():
    """东方财富沪银2606实时快照（~200ms）"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Referer': 'https://quote.eastmoney.com/',
    }

    url = ("https://push2.eastmoney.com/api/qt/stock/get?"
           "secid=113.AG2606&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f170,f171"
           "&ut=fa5fd1943c7b386f172d6893dbbd1")

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=5, context=ctx) as resp:
            d = json.loads(resp.read().decode('utf-8'))
            q = d.get('data', {})
            if not q or not q.get('f43'):
                return None

            p = q.get('f43', 0)
            pc = q.get('f60', 0) or p
            open_p = q.get('f46', 0)
            high_p = q.get('f44', 0)
            low_p = q.get('f45', 0)

            change = round(p - pc, 1)
            chg_pct = round((change / pc * 100) if pc else 0, 2)

            return {
                "source": "EM-snapshot",
                "symbol": "AG2606",
                "name": "沪银主力",
                "exchange": "SHFE",
                "currency": "CNY",
                "unit": "元/kg",
                "price": round(p, 1),
                "prevClose": round(pc, 1),
                "change": change,
                "changePercent": chg_pct,
                "open": round(open_p, 1) if open_p else None,
                "high": round(high_p, 1) if high_p else None,
                "low": round(low_p, 1) if low_p else None,
                "volume": q.get('f47', 0),
                "oi": q.get('f48', 0),
                "timestamp": int(time.time() * 1000),
                "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            }
    except Exception as e:
        log.debug(f"EM snapshot failed: {e}")
        return None


# ══════════════════════════════════════════════════════════
# 快数据源: Stooq COMEX 银快照
# ══════════════════════════════════════════════════════════
def fetch_stooq_comex():
    """Stooq COMEX 快照 — SI.F → XAGUSD → fallback"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conv = get_conv()
    usd_cny = usdcny_cache["rate"]

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    # 尝试1: COMEX 银期货 SI.F
    try:
        url = 'https://stooq.com/q/l/?s=si.f&f=sd2t2ohlcv&h&e=csv'
        req = Request(url, headers=headers)
        with urlopen(req, timeout=8, context=ctx) as resp:
            text = resp.read().decode('utf-8')
        if 'Exceeded' not in text:
            lines = text.strip().split('\n')
            if len(lines) >= 2:
                fields = lines[1].strip().split(',')
                if len(fields) >= 7:
                    price_usd = float(fields[6]) / 100.0
                    open_usd = float(fields[3]) / 100.0
                    high_usd = float(fields[4]) / 100.0
                    low_usd = float(fields[5]) / 100.0
                    price_cny = price_usd * conv
                    return _comex_result("Stooq-COMEX", "SI=F", "COMEX Silver Futures",
                                         price_usd, price_cny, open_usd * conv,
                                         high_usd * conv, low_usd * conv,
                                         fields[1], fields[2] if len(fields) > 2 else '',
                                         usd_cny, conv)
        log.info("[Stooq] SI.F rate limited, trying XAGUSD...")
    except Exception as e:
        log.debug(f"Stooq SI.F failed: {e}")

    # 尝试2: XAG/USD 现货
    try:
        url = 'https://stooq.com/q/l/?s=xagusd&f=sd2t2ohlcv&h&e=csv'
        req = Request(url, headers=headers)
        with urlopen(req, timeout=8, context=ctx) as resp:
            text = resp.read().decode('utf-8')
        if 'Exceeded' not in text:
            lines = text.strip().split('\n')
            if len(lines) >= 2:
                fields = lines[1].strip().split(',')
                if len(fields) >= 7:
                    price_usd = float(fields[6])
                    open_usd = float(fields[3])
                    high_usd = float(fields[4])
                    low_usd = float(fields[5])
                    price_cny = price_usd * conv
                    return _comex_result("Stooq-XAG", "XAGUSD", "COMEX Silver (XAG Spot)",
                                         price_usd, price_cny, open_usd * conv,
                                         high_usd * conv, low_usd * conv,
                                         fields[1], fields[2] if len(fields) > 2 else '',
                                         usd_cny, conv)
        log.warning("[Stooq] Both SI.F and XAGUSD rate limited!")
    except Exception as e:
        log.debug(f"Stooq XAGUSD failed: {e}")

    # 尝试3: MetalpriceAPI
    if METALPRICE_KEY:
        try:
            url = f"https://api.metalpriceapi.com/v1/latest?api_key={METALPRICE_KEY}&base=USD&currencies=XAG,CNY"
            req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, timeout=10) as resp:
                d = json.loads(resp.read())
                if d.get('success'):
                    rates = d.get('rates', {})
                    xag_usd = 1.0 / rates.get('XAG', 0) if rates.get('XAG', 0) > 0 else 0
                    cny = rates.get('CNY', 7.26)
                    if xag_usd > 0:
                        price_cny = xag_usd * cny * OZ_TO_KG
                        return {
                            "source": "MetalpriceAPI",
                            "symbol": "XAGUSD", "name": "COMEX Silver (XAG Spot)",
                            "exchange": "Global", "currency": "CNY", "unit": "元/kg",
                            "price": round(price_cny, 1),
                            "priceUsd": round(xag_usd, 3),
                            "timestamp": int(time.time() * 1000),
                            "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
                            "usdCny": cny, "convFactor": cny * OZ_TO_KG,
                        }
        except Exception as e:
            log.debug(f"MetalpriceAPI failed: {e}")

    return None


def _comex_result(source, symbol, name, price_usd, price_cny, open_cny, high_cny, low_cny,
                  date_str, time_str, usd_cny, conv):
    """构建 COMEX 数据字典"""
    change = price_cny - open_cny
    return {
        "source": source,
        "symbol": symbol, "name": name,
        "exchange": "CME/COMEX", "currency": "CNY", "unit": "元/kg",
        "price": round(price_cny, 1),
        "priceUsd": round(price_usd, 3),
        "prevClose": round(open_cny, 1),
        "change": round(change, 1),
        "changePercent": round(change / open_cny * 100, 2) if open_cny else 0,
        "open": round(open_cny, 1),
        "high": round(high_cny, 1),
        "low": round(low_cny, 1),
        "volume": 0,
        "timestamp": int(time.time() * 1000),
        "datetime_cst": date_str + ' ' + time_str,
        "usdCny": usd_cny,
        "convFactor": conv,
    }


# ══════════════════════════════════════════════════════════
# 慢数据源: akshare 分钟线/日线
# ══════════════════════════════════════════════════════════
def fetch_huyin_history():
    """akshare 沪银主力分钟线"""
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.futures_zh_minute_sina(symbol='AG0', period='60')
        if df is None or df.empty:
            return None
        history = []
        for _, row in df.iterrows():
            dt_str = str(row['datetime'])
            try:
                dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            except Exception:
                try:
                    dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
                except Exception:
                    continue
            ts = int(dt.timestamp() * 1000)
            c = float(row['close'])
            if c > 0:
                history.append({"t": ts, "y": round(c, 1)})
        return history[-200:]
    except Exception as e:
        log.warning(f"akshare huyin history failed: {e}")
        return None


def fetch_comex_history():
    """akshare XAG 日线"""
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.futures_foreign_hist(symbol='XAG')
        if df is None or df.empty:
            return None
        conv = get_conv()
        history = []
        for _, row in df.tail(60).iterrows():
            try:
                dt_str = str(row['date']).strip()
                close_val = float(row['close'])
                if close_val <= 0:
                    continue
                close_cny = close_val * conv
                if ' ' in dt_str:
                    dt_obj = datetime.strptime(dt_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
                else:
                    dt_obj = datetime.strptime(dt_str, '%Y-%m-%d')
                ts = int(dt_obj.replace(tzinfo=CST).timestamp() * 1000)
                history.append({"t": ts, "y": round(close_cny, 1)})
            except (ValueError, KeyError, TypeError):
                continue
        return history[-60:]
    except Exception as e:
        log.warning(f"akshare XAG history failed: {e}")
        return None


def fetch_usdcny():
    """Stooq USD/CNY 汇率"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        url = 'https://stooq.com/q/l/?s=usdcny&f=sd2t2c&h&e=csv'
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req, timeout=8, context=ctx) as resp:
            text = resp.read().decode('utf-8')
        lines = text.strip().split('\n')
        if len(lines) >= 2:
            fields = lines[1].strip().split(',')
            if len(fields) >= 6:
                return float(fields[5])
    except Exception:
        pass
    return 7.26


# ══════════════════════════════════════════════════════════
# 预警检测
# ══════════════════════════════════════════════════════════
def check_tick_jump(market, price, source='unknown'):
    global hu_tick_ring, comex_tick_ring

    tick_ring = hu_tick_ring if market == 'hu' else comex_tick_ring
    market_name = "沪银" if market == 'hu' else "COMEX"
    unit = "元/kg"

    now_ms = int(time.time() * 1000)
    now_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    tick_ring.append({"price": price, "ts": now_ms, "time": now_str, "source": source})
    while len(tick_ring) > 5:
        tick_ring.pop(0)

    if market == 'hu':
        hu_tick_ring = tick_ring
    else:
        comex_tick_ring = tick_ring

    if len(tick_ring) < 3:
        return None

    first = tick_ring[-3]
    last = tick_ring[-1]
    if first['price'] <= 0:
        return None

    change_pct = (last['price'] - first['price']) / first['price'] * 100

    one_tick_pct = 0
    if len(tick_ring) >= 2:
        prev = tick_ring[-2]['price']
        if prev > 0:
            one_tick_pct = (last['price'] - prev) / prev * 100

    if abs(change_pct) >= TICK_JUMP_THRESHOLD:
        direction = "急涨" if change_pct > 0 else "急跌"
        severity = "HIGH" if abs(change_pct) >= 3.0 else "MEDIUM" if abs(change_pct) >= 2.0 else "LOW"

        alert = {
            "id": f"alert_{market}_{now_ms}",
            "market": market,
            "marketName": market_name,
            "type": f"{market_name}_3TICK_JUMP",
            "direction": direction,
            "threshold": TICK_JUMP_THRESHOLD,
            "changePercent": round(change_pct, 3),
            "changeAbs": round(last['price'] - first['price'], 3),
            "fromPrice": first['price'],
            "toPrice": last['price'],
            "fromTime": first['time'],
            "toTime": now_str,
            "oneTickPct": round(one_tick_pct, 3),
            "twoTickPct": round(change_pct, 3),
            "tickCount": len(tick_ring),
            "source": source,
            "timestamp": now_ms,
            "datetime": now_str,
            "severity": severity,
            "unit": unit,
        }

        with alerts_lock:
            alerts_list.insert(0, alert)
            if len(alerts_list) > ALERT_MAX_HISTORY:
                alerts_list.pop()
            if direction == "急涨":
                alert_stats[market]["surge"] += 1
            else:
                alert_stats[market]["drop"] += 1
            alert_stats[market]["maxJump"] = max(alert_stats[market]["maxJump"], abs(change_pct))

        log.info(f"[ALERT] {market_name} 3-Tick {direction}: {change_pct:+.3f}% [{severity}]")
        return alert

    return None


# ══════════════════════════════════════════════════════════
# 波动率预计算
# ══════════════════════════════════════════════════════════
def compute_rolling_hv(history_list, window=20):
    if len(history_list) < window + 1:
        return []
    prices = [h['y'] for h in history_list]
    result = []
    for i in range(window, len(prices)):
        window_prices = prices[i - window:i + 1]
        log_returns = [math.log(window_prices[j + 1] / window_prices[j])
                       for j in range(len(window_prices) - 1)
                       if window_prices[j + 1] > 0 and window_prices[j] > 0]
        if len(log_returns) < 5:
            continue
        mean_r = sum(log_returns) / len(log_returns)
        var = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
        hv = math.sqrt(max(0, var)) * math.sqrt(252) * 100
        ts = history_list[i]['t']
        result.append({"t": int(ts), "y": round(hv, 3)})
    return result


# ══════════════════════════════════════════════════════════
# 快轮询线程
# ══════════════════════════════════════════════════════════
class FastPoller(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        log.info(f"Fast poller started ({FAST_POLL}s interval)")
        while not self._stop.is_set():
            try:
                # 沪银快照
                em = fetch_huyin_eastmoney()
                if em and em.get('price', 0) > 0:
                    with cache_lock:
                        hu = huyin_cache.get('data') or {}
                        hu.update({
                            'price': em['price'],
                            'prevClose': em.get('prevClose'),
                            'change': em['change'],
                            'changePercent': em['changePercent'],
                            'open': em.get('open') or hu.get('open'),
                            'high': em.get('high') or hu.get('high'),
                            'low': em.get('low') or hu.get('low'),
                            'volume': em.get('volume', 0),
                            'oi': em.get('oi', 0),
                            'timestamp': em['timestamp'],
                            'datetime_cst': em['datetime_cst'],
                            'source': em.get('source', 'EM-snapshot'),
                        })
                        if not hu.get('name'):
                            hu.update(em)
                        huyin_cache['data'] = hu
                        huyin_cache['ts'] = time.time()
                    check_tick_jump('hu', em['price'], 'EM-snapshot')

                # COMEX 快照
                co_fast = fetch_stooq_comex()
                if co_fast and co_fast.get('price', 0) > 0:
                    with cache_lock:
                        co = comex_cache.get('data') or {}
                        co.update({
                            'price': co_fast['price'],
                            'priceUsd': co_fast.get('priceUsd'),
                            'prevClose': co_fast.get('prevClose'),
                            'change': co_fast['change'],
                            'changePercent': co_fast['changePercent'],
                            'open': co_fast.get('open'),
                            'high': co_fast.get('high'),
                            'low': co_fast.get('low'),
                            'timestamp': co_fast['timestamp'],
                            'datetime_cst': co_fast.get('datetime_cst', ''),
                            'usdCny': co_fast.get('usdCny', usdcny_cache["rate"]),
                            'convFactor': co_fast.get('convFactor', get_conv()),
                            'source': co_fast.get('source', 'Stooq'),
                        })
                        if not co.get('name'):
                            co.update(co_fast)
                        comex_cache['data'] = co
                        comex_cache['ts'] = time.time()
                    check_tick_jump('comex', co_fast['price'], co_fast.get('source', 'Stooq'))
                else:
                    # Stooq 限流时 fallback
                    with cache_lock:
                        co = comex_cache.get('data') or {}
                        hist = co.get('history', [])
                        if hist and not co.get('price'):
                            last_hist = hist[-1]
                            co['price'] = last_hist.get('y', 0)
                            co['source'] = co.get('source', '') + '+hist-fallback'
                            co['timestamp'] = int(time.time() * 1000)
                            co['datetime_cst'] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
                            comex_cache['data'] = co
                            comex_cache['ts'] = time.time()
                            log.info(f"[COMEX/fallback] price={co['price']} from history")

                # 合并
                _rebuild_all_cache()

            except Exception as e:
                log.error(f"Fast poll error: {e}")

            self._stop.wait(FAST_POLL)


# ══════════════════════════════════════════════════════════
# 慢轮询线程
# ══════════════════════════════════════════════════════════
class SlowPoller(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        log.info(f"Slow poller started ({SLOW_POLL}s interval)")
        self._do_poll()
        while not self._stop.is_set():
            self._stop.wait(SLOW_POLL)
            if not self._stop.is_set():
                self._do_poll()

    def _do_poll(self):
        try:
            # 沪银历史
            hu_hist = fetch_huyin_history()
            if hu_hist:
                with cache_lock:
                    hu = huyin_cache.get('data') or {}
                    hu['history'] = hu_hist
                    hu['historyCount'] = len(hu_hist)
                    if not hu.get('source'):
                        hu['source'] = 'akshare-sina'
                    elif 'akshare' not in hu.get('source', ''):
                        hu['source'] = hu.get('source', '') + '+akshare'
                    if not hu.get('name'):
                        hu.update({'name': '沪银主力', 'symbol': 'AG0',
                                   'exchange': 'SHFE', 'currency': 'CNY', 'unit': '元/kg'})
                    huyin_cache['data'] = hu
                    huyin_cache['ts'] = time.time()
                log.info(f"[HuYin/history] {len(hu_hist)} bars loaded")

            # COMEX 历史
            co_hist = fetch_comex_history()
            if co_hist:
                with cache_lock:
                    co = comex_cache.get('data') or {}
                    co['history'] = co_hist
                    if not co.get('source'):
                        co['source'] = 'akshare-XAG'
                    elif 'akshare' not in co.get('source', ''):
                        co['source'] = co.get('source', '') + '+akshare'
                    if not co.get('name'):
                        co.update({'name': 'COMEX Silver Futures', 'symbol': 'SI=F',
                                   'exchange': 'CME/COMEX', 'currency': 'CNY', 'unit': '元/kg'})
                    comex_cache['data'] = co
                    comex_cache['ts'] = time.time()
                log.info(f"[COMEX/history] {len(co_hist)} bars loaded")

            # 汇率
            rate = fetch_usdcny()
            usdcny_cache['rate'] = rate
            usdcny_cache['ts'] = time.time()
            log.info(f"[USD/CNY] rate={rate}")

            _rebuild_all_cache()

        except Exception as e:
            log.error(f"Slow poll error: {e}")


# ══════════════════════════════════════════════════════════
# 合并缓存 + 价差 + 波动率
# ══════════════════════════════════════════════════════════
def _rebuild_all_cache():
    with cache_lock:
        huyin = huyin_cache.get('data')
        comex = comex_cache.get('data')

    spread_data = {}
    active_sources = []
    hv_series = {"hu": [], "comex": []}

    if comex and 'error' not in comex:
        active_sources.append(comex.get('source', '?'))
    if huyin and 'error' not in huyin:
        active_sources.append(huyin.get('source', '?'))

    if (comex and 'error' not in comex and comex.get('price', 0) > 0 and
            huyin and 'error' not in huyin and huyin.get('price', 0) > 0):
        usd_cny = usdcny_cache.get('rate', 7.26)
        comex_in_cny = comex['price']
        ratio = huyin['price'] / comex_in_cny if comex_in_cny > 0 else 0
        cny_spread = huyin['price'] - comex_in_cny

        if ratio > 1.06:
            status = "溢价偏高"
        elif ratio > 1.03:
            status = "轻度溢价"
        elif ratio > 0.98:
            status = "基本均衡"
        else:
            status = "折价"
        dev = (ratio - 1.0) * 100

        co_hist = comex.get('history', [])
        if len(co_hist) > 20:
            hv_series['comex'] = compute_rolling_hv(co_hist, window=20)

        hu_hist = huyin.get('history', [])
        if len(hu_hist) > 20:
            hv_series['hu'] = compute_rolling_hv(hu_hist, window=20)

        spread_data = {
            "ratio": round(ratio, 4),
            "cnySpread": round(cny_spread, 1),
            "comexInCNY": round(comex_in_cny, 1),
            "usdCNY": round(usd_cny, 4),
            "convFactor": round(usd_cny * OZ_TO_KG, 2),
            "status": status,
            "deviation": round(dev, 2),
        }

    all_data = {
        "comex": comex if comex else {"error": "comex_no_data"},
        "huyin": huyin if huyin else {"error": "huyin_no_data"},
        "spread": spread_data,
        "hvSeries": hv_series,
        "timestamp": int(time.time() * 1000),
        "datetime_utc": datetime.now(timezone.utc).isoformat(),
        "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "activeSources": active_sources,
    }

    with cache_lock:
        all_cache['data'] = all_data
        all_cache['ts'] = time.time()


# ══════════════════════════════════════════════════════════
# HTTP Server — Windows IPv4 专用
# ══════════════════════════════════════════════════════════
class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class SilverHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=".", **kwargs)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path.startswith('/api/'):
            self._send_json_api(path)
            return
        super().do_GET()

    def _send_json_api(self, path):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()

        if path == '/api/comex':
            data = comex_cache.get('data')
        elif path in ('/api/huyin', '/api/ag', '/api/silver'):
            data = huyin_cache.get('data')
        elif path == '/api/all':
            data = all_cache.get('data')
        elif path == '/api/status':
            data = {
                "status": "running",
                "fastPoll": FAST_POLL,
                "slowPoll": SLOW_POLL,
                "comexCacheAge": round(time.time() - comex_cache.get('ts', 0), 1),
                "huyinCacheAge": round(time.time() - huyin_cache.get('ts', 0), 1),
                "hasAkshare": HAS_AKSHARE,
                "serverTime": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            }
        elif path == '/api/alerts':
            with alerts_lock:
                alerts = list(alerts_list)
                stats = dict(alert_stats)
                hu_ring = list(hu_tick_ring)
                co_ring = list(comex_tick_ring)
            data = {
                "alerts": alerts,
                "count": len(alerts),
                "threshold": TICK_JUMP_THRESHOLD,
                "stats": stats,
                "huTickRing": hu_ring,
                "comexTickRing": co_ring,
            }
        elif path == '/api/sources':
            data = {
                "available": [
                    {"id": "eastmoney", "name": "EastMoney Snapshot", "type": "HuYin AG2606 fast",
                     "authRequired": False, "status": "active"},
                    {"id": "stooq-comex", "name": "Stooq COMEX", "type": "SI=F fast",
                     "authRequired": False, "status": "active"},
                    {"id": "akshare", "name": "AKShare History", "type": "HuYin + XAG history",
                     "authRequired": False, "status": "active" if HAS_AKSHARE else "not_installed"},
                ]
            }
        else:
            data = {"error": "not_found", "path": path}

        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode('utf-8'))

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


# ══════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════
if __name__ == '__main__':
    banner = """
    ══════════════════════════════════════════════════════
       Silver Monitor Server v5.0 (Production)
       COMEX Silver (SI=F) + HuYin (SHFE AG2606)
    ──────────────────────────────────────────────────────
       Fast poll: %ds (EM snapshot + Stooq snapshot)
       Slow poll: %ds (akshare history + USD/CNY)
    ──────────────────────────────────────────────────────
       Alert: HuYin + COMEX 3-Tick jump > %.1f%%
       Endpoints:
       GET /            Frontend
       GET /api/all     Combined + Spread + HV
       GET /api/huyin   HuYin AG JSON
       GET /api/comex   COMEX Silver JSON
       GET /api/alerts  Alert History
       GET /api/status  Service Status
    ══════════════════════════════════════════════════════
    """ % (FAST_POLL, SLOW_POLL, TICK_JUMP_THRESHOLD)
    print(banner)

    # 首次快数据拉取
    log.info("Initial fast data fetch...")
    em = fetch_huyin_eastmoney()
    if em:
        huyin_cache['data'] = em
        huyin_cache['ts'] = time.time()
        log.info(f"[HuYin/EM] price={em['price']}")

    co = fetch_stooq_comex()
    if co:
        comex_cache['data'] = co
        comex_cache['ts'] = time.time()
        log.info(f"[COMEX/Stooq] price={co['price']} CNY/kg (${co.get('priceUsd', '?')}/oz)")

    _rebuild_all_cache()

    # 启动线程
    fast_poller = FastPoller()
    fast_poller.start()
    slow_poller = SlowPoller()
    slow_poller.start()

    # 启动 HTTP 服务器 — IPv4 only（Windows 兼容）
    try:
        server = ThreadingHTTPServer(('0.0.0.0', PORT), SilverHandler)
        log.info(f"Server started: http://127.0.0.1:{PORT}/")
    except OSError as e:
        log.error(f"Failed to bind port {PORT}: {e}")
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
