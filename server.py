"""
Silver Monitor Server v5.2 — 生产级完整版
==========================================
快数据（3秒更新）: 新浪沪银 + 新浪XAG/USD
慢数据（60秒更新）: akshare分钟线/日线 + 新浪汇率
所有 API 立即返回缓存数据（非阻塞）
Windows IPv4 专用绑定，避免 IPv6 兼容问题

启动: python server.py
访问: http://127.0.0.1:8765/

数据源分布：
- 沪银实时: 新浪 nf_AG0 (~60ms) → 东方财富 → akshare 1min
- COMEX实时: 新浪 hf_XAG (~60ms) → Yahoo → Stooq → akshare daily
- 沪银历史: akshare 60min 分钟线
- COMEX历史: akshare XAG/USD 日线
- 汇率: 新浪 fx_susdcny (~50ms) → Stooq
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

# ── 配置 ──
PORT = 8765
FAST_POLL = 3       # 快数据轮询（秒）
SLOW_POLL = 60      # 慢数据轮询（秒）


logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# ── 全局缓存 ──
cache_lock = threading.Lock()
comex_cache = {"data": None, "ts": 0}
huyin_cache = {"data": None, "ts": 0}
all_cache = {"data": None, "ts": 0}
usdcny_cache = {"rate": 6.83, "ts": 0}

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
# 交易时间检查
# ══════════════════════════════════════════════════════════
def is_huyin_trading():
    """检查沪银是否在交易时段（CST 时区）"""
    now = datetime.now(CST)
    weekday = now.weekday()  # 0=周一, 6=周日
    hour = now.hour
    minute = now.minute
    
    # 周末休市
    if weekday >= 5:
        return False
    
    # 工作日
    # 早盘: 09:00-11:30
    if 9 <= hour < 11:
        return True
    if hour == 11 and minute <= 30:
        return True
    
    # 午盘: 13:30-15:00
    if 13 <= hour < 15:
        return True
    if hour == 13 and minute < 30:
        return False
    
    # 夜盘: 21:00-02:30
    if hour >= 21:
        return True
    if hour < 2 and hour >= 0:
        return True
    if hour == 2 and minute <= 30:
        return True
    
    return False


def is_comex_trading():
    """检查 COMEX 是否在交易时段
    
    COMEX SI=F 交易时间：美东 18:00-17:00（跨日）
    等同于 CST 时间：每天 06:00（前一天）至 07:00（同日）
    
    简化处理：
    - 周一至周五白天和晚上都算活跃
    - 周六早上 06:00 前还在交易
    - 周六 07:00 后至周日 18:00 前算休盘
    - 周日 18:00 后待开盘（实际 COMEX 已开始新一周交易）
    """
    now = datetime.now(CST)
    weekday = now.weekday()  # 0=周一, 6=周日
    hour = now.hour
    
    # 周一至周五全天有流动性
    if weekday < 5:
        return True
    
    # 周六
    if weekday == 5:
        if hour < 6:  # 周六凌晨 00:00-06:00
            return True  # 继续交易中
        if hour >= 7:
            return False  # 已关闭
        # 06:00-07:00 边界情况，算做有流动性
        return True
    
    # 周日
    if weekday == 6:
        if hour >= 18:  # 周日 18:00 后，美东周五 18:00 开市
            return True
        return False
    
    return False


def get_trading_status(market):
    """获取市场状态描述
    
    返回值:
    - ('open', description): 市场开放，含时间段描述
    - ('closed', description): 市场关闭，含原因
    """
    now = datetime.now(CST)
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    
    if market == 'huyin':
        if weekday >= 5:
            return ('closed', '周末休市')
        
        # 工作日交易时段检查
        # 早盘: 09:00-11:30
        if (hour == 9 and minute >= 0) or (9 < hour < 11) or (hour == 11 and minute < 31):
            return ('open', '早盘交易')
        # 午盘: 13:30-15:00
        if (hour == 13 and minute >= 30) or (13 < hour < 15):
            return ('open', '午盘交易')
        # 夜盘: 21:00-02:30 (跨日)
        if hour >= 21 or hour < 2 or (hour == 2 and minute < 30):
            return ('open', '夜盘交易')
        
        # 非交易时段，确定最近的开盘时间
        if hour < 9:
            return ('closed', '待早盘开盘 09:00')
        elif hour < 13 or (hour == 13 and minute < 30):
            return ('closed', '午盘 13:30 开盘')
        else:
            return ('closed', '夜盘 21:00 开盘')
    
    elif market == 'comex':
        if weekday < 5:
            return ('open', 'SI=F 活跃交易')
        elif weekday == 5:
            if hour < 6:
                return ('open', 'SI=F 交易中')
            elif hour >= 7:
                return ('closed', '下周一开盘')
            else:
                return ('open', 'SI=F 交易中')
        elif weekday == 6:
            if hour >= 18:
                return ('open', 'SI=F 开市')
            else:
                return ('closed', '待周日晚开市')
    
    return ('unknown', 'Unknown status')



# 快数据源: 新浪沪银实时快照
# ══════════════════════════════════════════════════════════
def fetch_huyin_sina():
    """新浪期货 nf_AG0 沪银连续实时报价（~60ms）"""
    try:
        url = 'https://hq.sinajs.cn/list=nf_AG0'
        headers_sina = {
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        req = Request(url, headers=headers_sina)
        with urlopen(req, timeout=5) as resp:
            text = resp.read().decode('gbk')

        raw = text.split('=', 1)[1].strip(';\n\r "')
        if not raw:
            return None
        parts = raw.split(',')
        if len(parts) < 15:
            return None

        # [0]名称 [1]时间HHMMSS [2]开盘 [3]最高 [4]最低 [5]昨结
        # [6]买价 [7]卖价 [8]最新价 [10]昨收盘 [13]成交额 [14]成交量
        # [17]日期
        price = float(parts[8])
        if price <= 0:
            return None

        open_p = float(parts[2]) if parts[2] else 0
        high_p = float(parts[3]) if parts[3] else 0
        low_p = float(parts[4]) if parts[4] else 0
        prev_close = float(parts[10]) if parts[10] and float(parts[10]) > 0 else (float(parts[5]) if parts[5] and float(parts[5]) > 0 else price)
        volume = int(float(parts[14])) if len(parts) > 14 and parts[14] else 0
        time_str = parts[1]  # HHMMSS
        date_str = parts[17] if len(parts) > 17 else datetime.now(CST).strftime('%Y-%m-%d')

        # 格式化时间 HHMMSS → HH:MM:SS
        if len(time_str) == 6:
            time_fmt = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
        else:
            time_fmt = time_str

        change = round(price - prev_close, 1)
        change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

        result = {
            "source": "Sina-AG0",
            "symbol": "AG2606",
            "name": "沪银主力",
            "exchange": "SHFE",
            "currency": "CNY",
            "unit": "元/kg",
            "price": round(price, 1),
            "prevClose": round(prev_close, 1),
            "change": change,
            "changePercent": change_pct,
            "open": round(open_p, 1) if open_p else None,
            "high": round(high_p, 1) if high_p else None,
            "low": round(low_p, 1) if low_p else None,
            "volume": volume,
            "timestamp": int(time.time() * 1000),
            "datetime_cst": f"{date_str} {time_fmt}",
        }
        log.debug(f"[Sina/AG0] {price:.1f} 元/kg  chg={change:+.1f}")
        return result
    except Exception as e:
        log.debug(f"Sina AG0 failed: {e}")
        return None


def fetch_comex_sina():
    """新浪实时贵金属 XAG/USD — 国内可用、更新频繁"""
    try:
        conv = get_conv()
        usd_cny = usdcny_cache["rate"]

        url = 'https://hq.sinajs.cn/list=hf_XAG'
        headers_sina = {
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        req = Request(url, headers=headers_sina)
        with urlopen(req, timeout=5) as resp:
            text = resp.read().decode('gbk')

        # 格式: var hq_str_hf_XAG="最新,昨收,今开,最高,...,时间,...,日期,名称";
        raw = text.split('=', 1)[1].strip(';\n\r "')
        if not raw or raw == '':
            return None
        parts = raw.split(',')
        if len(parts) < 13:
            return None

        price_usd = float(parts[0])
        prev_close = float(parts[1])
        open_usd = float(parts[2]) if parts[2] else price_usd
        high_usd = float(parts[3]) if parts[3] else price_usd
        low_usd = float(parts[5]) if parts[5] else price_usd
        time_str = parts[6]     # HH:MM:SS
        date_str = parts[12]    # YYYY-MM-DD

        if price_usd <= 0:
            return None

        price_cny = price_usd * conv
        change_usd = price_usd - prev_close
        change_pct = (change_usd / prev_close * 100) if prev_close > 0 else 0

        result = {
            "source": "Sina-XAG",
            "symbol": "XAG/USD",
            "name": "伦敦银 (XAG Spot)",
            "exchange": "CME/COMEX",
            "currency": "USD",
            "unit": "$/oz",
            "price": round(price_usd, 3),
            "priceCny": round(price_cny, 1),
            "prevClose": round(prev_close, 3),
            "change": round(change_usd, 3),
            "changePercent": round(change_pct, 2),
            "open": round(open_usd, 3),
            "high": round(high_usd, 3),
            "low": round(low_usd, 3),
            "volume": 0,
            "timestamp": int(time.time() * 1000),
            "datetime_cst": date_str + ' ' + time_str,
            "usdCny": usd_cny,
            "convFactor": conv,
        }
        log.debug(f"[Sina/XAG] ${price_usd:.3f}/oz  chg={change_usd:+.3f}")
        return result
    except Exception as e:
        log.debug(f"Sina XAG failed: {e}")
        return None


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
    """akshare XAG 日线（USD/oz）"""
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.futures_foreign_hist(symbol='XAG')
        if df is None or df.empty:
            return None
        history = []
        for _, row in df.tail(60).iterrows():
            try:
                dt_str = str(row['date']).strip()
                close_val = float(row['close'])
                if close_val <= 0:
                    continue
                if ' ' in dt_str:
                    dt_obj = datetime.strptime(dt_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
                else:
                    dt_obj = datetime.strptime(dt_str, '%Y-%m-%d')
                ts = int(dt_obj.replace(tzinfo=CST).timestamp() * 1000)
                history.append({"t": ts, "y": round(close_val, 3)})
            except (ValueError, KeyError, TypeError):
                continue
        return history[-60:]
    except Exception as e:
        log.warning(f"akshare XAG history failed: {e}")
        return None


def fetch_usdcny_sina():
    """新浪外汇 USD/CNY 在岸汇率（~50ms）"""
    try:
        url = 'https://hq.sinajs.cn/list=fx_susdcny'
        headers_sina = {
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        req = Request(url, headers=headers_sina)
        with urlopen(req, timeout=5) as resp:
            text = resp.read().decode('gbk')

        # [0]时间 [1]买入 [2]卖出 [3]最新 [5]开盘 [6]最高 [7]最低 [8]昨收
        raw = text.split('=', 1)[1].strip(';\n\r "')
        if not raw:
            return None
        parts = raw.split(',')
        if len(parts) < 4:
            return None
        rate = float(parts[1])  # 买入价
        if rate <= 0:
            return None
        log.debug(f"[Sina/USDCNY] rate={rate:.4f}")
        return rate
    except Exception as e:
        log.debug(f"Sina USDCNY failed: {e}")
        return None


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
# 快速备用: akshare 实时数据
# ══════════════════════════════════════════════════════════
def fetch_huyin_akshare_realtime():
    """akshare 沪银实时数据（作为快速备用源）"""
    if not HAS_AKSHARE:
        return None
    try:
        # 获取最新的分钟线数据（通常包含当前未平仓价格）
        df = ak.futures_zh_minute_sina(symbol='AG0', period='1')
        if df is None or df.empty:
            return None
        
        # 取最后一条记录
        last_row = df.iloc[-1]
        price = float(last_row['close'])
        
        if price <= 0:
            return None
        
        return {
            "source": "akshare-realtime",
            "symbol": "AG0",
            "name": "沪银主力",
            "exchange": "SHFE",
            "currency": "CNY",
            "unit": "元/kg",
            "price": round(price, 1),
            "timestamp": int(time.time() * 1000),
            "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        log.debug(f"akshare realtime HuYin failed: {e}")
        return None


def fetch_comex_akshare_realtime():
    """akshare XAG/USD 最新数据（作为最后备用源）"""
    if not HAS_AKSHARE:
        return None
    try:
        conv = get_conv()
        # 获取最新一条日线数据
        df = ak.futures_foreign_hist(symbol='XAG')
        if df is None or df.empty:
            return None
        
        last_row = df.iloc[-1]
        close_usd = float(last_row['close'])
        
        if close_usd <= 0:
            return None
        
        price_cny = close_usd * conv
        
        return {
            "source": "akshare-latest",
            "symbol": "XAG",
            "name": "COMEX Silver (XAG/USD)",
            "exchange": "CME/COMEX",
            "currency": "USD",
            "unit": "$/oz",
            "price": round(close_usd, 3),
            "priceCny": round(price_cny, 1),
            "timestamp": int(time.time() * 1000),
            "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            "convFactor": conv,
            "usdCny": usdcny_cache["rate"],
        }
    except Exception as e:
        log.debug(f"akshare realtime XAG failed: {e}")
        return None


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
                # 首先检查是否在交易时段
                hu_status, hu_desc = get_trading_status('huyin')
                co_status, co_desc = get_trading_status('comex')
                
                # 沪银数据获取 — Sina 主力 + akshare 备用
                if hu_status == 'open':
                    em = fetch_huyin_sina()
                    if not em:
                        em = fetch_huyin_akshare_realtime()
                        if em:
                            log.warning("[HuYin] Using akshare 1min as fallback")
                else:
                    # 休市时返回提示
                    em = {
                        "symbol": "AG2606",
                        "name": "沪银主力",
                        "exchange": "SHFE",
                        "currency": "CNY",
                        "unit": "元/kg",
                        "closed": True,
                        "status_desc": hu_desc,
                        "timestamp": int(time.time() * 1000),
                        "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    log.debug(f"[HuYin] {hu_desc}，跳过数据获取")
                
                if em:
                    if em.get('closed'):
                        # 休市时直接保存休市信息到缓存
                        with cache_lock:
                            hu = huyin_cache.get('data') or {}
                            hu.update({
                                'closed': True,
                                'status_desc': em['status_desc'],
                                'timestamp': em['timestamp'],
                                'datetime_cst': em['datetime_cst'],
                            })
                            # 保留历史数据
                            if not hu.get('name'):
                                hu.update({k: em[k] for k in ['symbol', 'name', 'exchange', 'currency', 'unit'] if k in em})
                            huyin_cache['data'] = hu
                            huyin_cache['ts'] = time.time()
                    elif em.get('price', 0) > 0:
                        with cache_lock:
                            hu = huyin_cache.get('data') or {}
                            
                            # 计算缺失的字段（来自 akshare 时需要）
                            prev_close = em.get('prevClose')
                            if not prev_close and hu.get('prevClose'):
                                prev_close = hu['prevClose']
                            elif not prev_close:
                                prev_close = em.get('price')
                            
                            change = em.get('change')
                            if change is None:
                                change = round(em['price'] - prev_close, 1) if prev_close else 0
                            
                            change_pct = em.get('changePercent')
                            if change_pct is None:
                                change_pct = round(change / prev_close * 100, 2) if prev_close and prev_close != 0 else 0
                            
                            hu.update({
                                'price': em['price'],
                                'prevClose': prev_close,
                                'change': change,
                                'changePercent': change_pct,
                                'open': em.get('open') or hu.get('open'),
                                'high': em.get('high') or hu.get('high'),
                                'low': em.get('low') or hu.get('low'),
                                'volume': em.get('volume', 0),
                                'oi': em.get('oi', 0),
                                'timestamp': em['timestamp'],
                                'datetime_cst': em['datetime_cst'],
                                'source': em.get('source', 'Sina-AG0'),
                                'closed': False,
                            })
                            if not hu.get('name'):
                                hu.update(em)
                            huyin_cache['data'] = hu
                            huyin_cache['ts'] = time.time()
                        check_tick_jump('hu', em['price'], em.get('source', 'Sina-AG0'))

                # COMEX 快照 — Sina 主力 + akshare 备用
                if co_status == 'open':
                    co_fast = fetch_comex_sina()
                    if not co_fast:
                        co_fast = fetch_comex_akshare_realtime()
                        if co_fast:
                            log.warning("[COMEX] Using akshare daily as fallback")
                else:
                    # 休市时返回提示
                    co_fast = {
                        "symbol": "SI=F",
                        "name": "COMEX Silver Futures",
                        "exchange": "CME/COMEX",
                        "currency": "USD",
                        "unit": "$/oz",
                        "closed": True,
                        "status_desc": co_desc,
                        "timestamp": int(time.time() * 1000),
                        "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    log.debug(f"[COMEX] {co_desc}，跳过数据获取")
                
                if co_fast:
                    if co_fast.get('closed'):
                        # 休市时直接保存休市信息到缓存
                        with cache_lock:
                            co = comex_cache.get('data') or {}
                            co.update({
                                'closed': True,
                                'status_desc': co_fast['status_desc'],
                                'timestamp': co_fast['timestamp'],
                                'datetime_cst': co_fast['datetime_cst'],
                            })
                            # 保留历史数据
                            if not co.get('name'):
                                co.update({k: co_fast[k] for k in ['symbol', 'name', 'exchange', 'currency', 'unit'] if k in co_fast})
                            comex_cache['data'] = co
                            comex_cache['ts'] = time.time()
                    elif co_fast.get('price', 0) > 0:
                        with cache_lock:
                            co = comex_cache.get('data') or {}
                            co.update({
                                'price': co_fast['price'],
                                'priceCny': co_fast.get('priceCny'),
                                'prevClose': co_fast.get('prevClose'),
                                'change': co_fast.get('change'),
                                'changePercent': co_fast.get('changePercent'),
                                'open': co_fast.get('open'),
                                'high': co_fast.get('high'),
                                'low': co_fast.get('low'),
                                'timestamp': co_fast['timestamp'],
                                'datetime_cst': co_fast.get('datetime_cst', ''),
                                'usdCny': co_fast.get('usdCny', usdcny_cache["rate"]),
                                'convFactor': co_fast.get('convFactor', get_conv()),
                                'source': co_fast.get('source', 'unknown'),
                                'closed': False,
                            })
                            if not co.get('name'):
                                co.update(co_fast)
                            comex_cache['data'] = co
                            comex_cache['ts'] = time.time()
                        check_tick_jump('comex', co_fast['price'], co_fast.get('source', 'unknown'))
                else:
                    # 所有源都失败 fallback
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
            rate = fetch_usdcny_sina()
            if not rate:
                log.warning("[USD/CNY] Sina failed, keeping cached rate")
                rate = usdcny_cache['rate']
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
        # COMEX price 现在是 USD/oz，换算为 CNY/kg 用于比价
        comex_in_cny = comex.get('priceCny') or (comex['price'] * get_conv())
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

    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/api/threshold':
            self._handle_threshold()
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":"not_found"}')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _handle_threshold(self):
        global TICK_JUMP_THRESHOLD
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            val = float(body.get('threshold', 0))
            if val < 1.0 or val > 10.0:
                raise ValueError('threshold must be between 1 and 10')
            TICK_JUMP_THRESHOLD = round(val, 1)
            log.info(f'[Config] Alert threshold changed to {TICK_JUMP_THRESHOLD}%')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True, 'threshold': TICK_JUMP_THRESHOLD}).encode())
        except Exception as e:
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())

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
                    {"id": "yahoo-comex", "name": "Yahoo Finance COMEX", "type": "SI=F fast (15-20min delay)",
                     "authRequired": False, "status": "active" if HAS_YFINANCE else "not_installed"},
                    {"id": "stooq-comex", "name": "Stooq COMEX", "type": "SI=F/XAGUSD fallback",
                     "authRequired": False, "status": "backup"},
                    {"id": "akshare", "name": "AKShare History", "type": "HuYin AG + XAG/USD history",
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
       Silver Monitor Server v5.2 (Production)
       COMEX Silver (SI=F) + HuYin (SHFE AG2606)
    ──────────────────────────────────────────────────────
       Fast poll: %ds (Sina AG0/XAG → akshare)
       Slow poll: %ds (akshare history + Sina USDCNY)
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
    em = fetch_huyin_sina()
    if not em:
        log.warning("[Startup] Sina AG0 failed, trying akshare...")
        em = fetch_huyin_akshare_realtime()
    if em:
        huyin_cache['data'] = em
        huyin_cache['ts'] = time.time()
        log.info(f"[HuYin/{em.get('source','?')}] price={em['price']}")
    else:
        log.warning("[Startup] HuYin: all sources failed")

    co = fetch_comex_sina()
    if not co:
        log.warning("[Startup] Sina XAG failed, trying akshare...")
        co = fetch_comex_akshare_realtime()
    
    if co:
        comex_cache['data'] = co
        comex_cache['ts'] = time.time()
        log.info(f"[COMEX/{co.get('source', 'unknown')}] price=${co['price']}/oz (≈¥{co.get('priceCny', '?')}/kg)")
    else:
        log.warning("[Startup] COMEX: all sources failed")

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
