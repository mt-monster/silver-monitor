import json
import time
from datetime import datetime
from urllib.request import Request, urlopen

from backend.config import CST, log
from backend.state import state
from backend.utils import get_conv, get_conv_gold


_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_huyin_sina():
    try:
        url = "https://hq.sinajs.cn/list=nf_AG0"
        headers_sina = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        req = Request(url, headers=headers_sina)
        with urlopen(req, timeout=5) as resp:
            text = resp.read().decode("gbk")

        raw = text.split("=", 1)[1].strip(';\n\r "')
        if not raw:
            return None
        parts = raw.split(",")
        if len(parts) < 15:
            return None

        price = float(parts[8])
        if price <= 0:
            return None

        open_p = float(parts[2]) if parts[2] else 0
        high_p = float(parts[3]) if parts[3] else 0
        low_p = float(parts[4]) if parts[4] else 0
        prev_close = (
            float(parts[10])
            if parts[10] and float(parts[10]) > 0
            else (float(parts[5]) if parts[5] and float(parts[5]) > 0 else price)
        )
        volume = int(float(parts[14])) if len(parts) > 14 and parts[14] else 0
        time_str = parts[1]
        date_str = parts[17] if len(parts) > 17 else datetime.now(CST).strftime("%Y-%m-%d")

        time_fmt = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}" if len(time_str) == 6 else time_str
        change = round(price - prev_close, 1)
        change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

        result = {
            "source": "Sina-AG0",
            "symbol": "AG0",
            "name": "沪银主力连续",
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
    except Exception as exc:
        log.debug(f"Sina AG0 failed: {exc}")
        return None


def fetch_comex_sina():
    try:
        conv = get_conv()
        usd_cny = state.usd_cny_cache["rate"]

        url = "https://hq.sinajs.cn/list=hf_XAG"
        headers_sina = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        req = Request(url, headers=headers_sina)
        with urlopen(req, timeout=5) as resp:
            text = resp.read().decode("gbk")

        raw = text.split("=", 1)[1].strip(';\n\r "')
        if not raw:
            return None
        parts = raw.split(",")
        if len(parts) < 13:
            return None

        price_usd = float(parts[0])
        prev_close = float(parts[1])
        open_usd = float(parts[2]) if parts[2] else price_usd
        high_usd = float(parts[3]) if parts[3] else price_usd
        low_usd = float(parts[5]) if parts[5] else price_usd
        time_str = parts[6]
        date_str = parts[12]

        if price_usd <= 0:
            return None

        price_cny = price_usd * conv
        change_usd = price_usd - prev_close
        change_pct = change_usd / prev_close * 100 if prev_close > 0 else 0

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
            "datetime_cst": date_str + " " + time_str,
            "usdCny": usd_cny,
            "convFactor": conv,
        }
        log.debug(f"[Sina/XAG] ${price_usd:.3f}/oz  chg={change_usd:+.3f}")
        return result
    except Exception as exc:
        log.debug(f"Sina XAG failed: {exc}")
        return None


def fetch_hujin_sina():
    try:
        url = "https://hq.sinajs.cn/list=nf_AU0"
        headers_sina = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        req = Request(url, headers=headers_sina)
        with urlopen(req, timeout=5) as resp:
            text = resp.read().decode("gbk")

        raw = text.split("=", 1)[1].strip(';\n\r "')
        if not raw:
            return None
        parts = raw.split(",")
        if len(parts) < 15:
            return None

        price = float(parts[8])
        if price <= 0:
            return None

        open_p = float(parts[2]) if parts[2] else 0
        high_p = float(parts[3]) if parts[3] else 0
        low_p = float(parts[4]) if parts[4] else 0
        prev_close = (
            float(parts[10])
            if parts[10] and float(parts[10]) > 0
            else (float(parts[5]) if parts[5] and float(parts[5]) > 0 else price)
        )
        volume = int(float(parts[14])) if len(parts) > 14 and parts[14] else 0
        time_str = parts[1]
        date_str = parts[17] if len(parts) > 17 else datetime.now(CST).strftime("%Y-%m-%d")

        time_fmt = f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}" if len(time_str) == 6 else time_str
        change = price - prev_close
        change_pct = change / prev_close * 100 if prev_close > 0 else 0

        result = {
            "source": "Sina-AU0",
            "symbol": "AU0",
            "name": "沪金主力连续",
            "exchange": "SHFE",
            "currency": "CNY",
            "unit": "元/克",
            "price": round(price, 2),
            "prevClose": round(prev_close, 2),
            "change": round(change, 2),
            "changePercent": round(change_pct, 2),
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "volume": volume,
            "timestamp": int(time.time() * 1000),
            "datetime_cst": f"{date_str} {time_fmt}",
        }
        log.debug(f"[Sina/AU0] ¥{price:.2f}/g  chg={change:+.2f}")
        return result
    except Exception as exc:
        log.debug(f"Sina AU0 failed: {exc}")
        return None


def fetch_comex_gold_sina():
    try:
        conv = get_conv_gold()
        usd_cny = state.usd_cny_cache["rate"]

        url = "https://hq.sinajs.cn/list=hf_XAU"
        headers_sina = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        req = Request(url, headers=headers_sina)
        with urlopen(req, timeout=5) as resp:
            text = resp.read().decode("gbk")

        raw = text.split("=", 1)[1].strip(';\n\r "')
        if not raw:
            return None
        parts = raw.split(",")
        if len(parts) < 13:
            return None

        price_usd = float(parts[0])
        prev_close = float(parts[1])
        open_usd = float(parts[2]) if parts[2] else price_usd
        high_usd = float(parts[3]) if parts[3] else price_usd
        low_usd = float(parts[5]) if parts[5] else price_usd
        time_str = parts[6]
        date_str = parts[12]

        if price_usd <= 0:
            return None

        price_cny_g = price_usd * conv
        change_usd = price_usd - prev_close
        change_pct = change_usd / prev_close * 100 if prev_close > 0 else 0

        result = {
            "source": "Sina-XAU",
            "symbol": "XAU/USD",
            "name": "伦敦金 (XAU Spot)",
            "exchange": "CME/COMEX",
            "currency": "USD",
            "unit": "$/oz",
            "price": round(price_usd, 2),
            "priceCnyG": round(price_cny_g, 2),
            "prevClose": round(prev_close, 2),
            "change": round(change_usd, 2),
            "changePercent": round(change_pct, 2),
            "open": round(open_usd, 2),
            "high": round(high_usd, 2),
            "low": round(low_usd, 2),
            "volume": 0,
            "timestamp": int(time.time() * 1000),
            "datetime_cst": date_str + " " + time_str,
            "usdCny": usd_cny,
            "convFactor": conv,
        }
        log.debug(f"[Sina/XAU] ${price_usd:.2f}/oz  chg={change_usd:+.2f}")
        return result
    except Exception as exc:
        log.debug(f"Sina XAU failed: {exc}")
        return None


def fetch_huyin_history():
    """沪银60分钟K线 — Sina InnerFutures API。"""
    return _fetch_sina_minute_kline("AG0", decimals=1, max_bars=200)


def fetch_comex_history():
    """COMEX白银日K线 — Sina GlobalFutures API。"""
    return _fetch_sina_intl_daily_kline("XAG", decimals=3, max_bars=60)


def fetch_hujin_history():
    """沪金60分钟K线 — Sina InnerFutures API。"""
    return _fetch_sina_minute_kline("AU0", decimals=2, max_bars=200)


def fetch_comex_gold_history():
    """COMEX黄金日K线 — Sina GlobalFutures API。"""
    return _fetch_sina_intl_daily_kline("XAU", decimals=2, max_bars=60)


def fetch_generic_domestic_history(symbol: str, decimals: int = 1, max_bars: int = 200):
    """通用国内期货60分钟K线 — Sina InnerFutures API。
    symbol: 品种代码，如 "CU0", "RB0", "AG0"。
    """
    return _fetch_sina_minute_kline(symbol, decimals=decimals, max_bars=max_bars)


def fetch_generic_intl_history(symbol: str, decimals: int = 2, max_bars: int = 60):
    """通用国际期货日K线 — Sina GlobalFutures API。
    symbol: 国际品种代码，如 "XAG", "CL", "NG", "HG"。
    """
    return _fetch_sina_intl_daily_kline(symbol, decimals=decimals, max_bars=max_bars)


# ── 直接 Sina K 线 API（替代 akshare）───────────────────────────

def _fetch_sina_minute_kline(symbol: str, period: int = 60, decimals: int = 1, max_bars: int = 200):
    """国内期货分钟K线 — 直接调用 Sina InnerFuturesNewService。"""
    try:
        url = (
            "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
            "var%20_t=/InnerFuturesNewService.getFewMinLine?"
            f"symbol={symbol}&type={period}"
        )
        req = Request(url, headers=_SINA_HEADERS)
        with urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")

        idx_start = text.index("[")
        idx_end = text.rindex("]") + 1
        rows = json.loads(text[idx_start:idx_end])

        history = []
        for row in rows:
            dt_str = row.get("d", "")
            close_str = row.get("c", "")
            try:
                close_val = float(close_str)
                if close_val <= 0:
                    continue
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                ts = int(dt.timestamp() * 1000)
                history.append({"t": ts, "y": round(close_val, decimals)})
            except (ValueError, TypeError):
                continue
        return history[-max_bars:] if history else None
    except Exception as exc:
        log.warning(f"Sina {symbol} minute kline failed: {exc}")
        return None


def _fetch_sina_intl_daily_kline(symbol: str, decimals: int = 2, max_bars: int = 60):
    """国际期货日K线 — 直接调用 Sina GlobalFuturesService。"""
    try:
        ts_ms = int(time.time() * 1000)
        url = (
            "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
            "var%20_t=/GlobalFuturesService.getGlobalFuturesDailyKLine?"
            f"symbol={symbol}&_={ts_ms}"
        )
        req = Request(url, headers=_SINA_HEADERS)
        with urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")

        idx_start = text.index("[")
        idx_end = text.rindex("]") + 1
        rows = json.loads(text[idx_start:idx_end])

        history = []
        for row in rows[-max_bars:]:
            date_str = row.get("date", "")
            close_str = row.get("close", "")
            try:
                close_val = float(close_str)
                if close_val <= 0:
                    continue
                if " " in date_str:
                    dt = datetime.strptime(date_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                else:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                ts = int(dt.replace(tzinfo=CST).timestamp() * 1000)
                history.append({"t": ts, "y": round(close_val, decimals)})
            except (ValueError, TypeError):
                continue
        return history[-max_bars:] if history else None
    except Exception as exc:
        log.warning(f"Sina {symbol} intl daily kline failed: {exc}")
        return None


def fetch_usdcny_sina():
    try:
        url = "https://hq.sinajs.cn/list=fx_susdcny"
        headers_sina = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        req = Request(url, headers=headers_sina)
        with urlopen(req, timeout=5) as resp:
            text = resp.read().decode("gbk")

        raw = text.split("=", 1)[1].strip(';\n\r "')
        if not raw:
            return None
        parts = raw.split(",")
        if len(parts) < 4:
            return None
        rate = float(parts[1])
        if rate <= 0:
            return None
        log.debug(f"[Sina/USDCNY] rate={rate:.4f}")
        return rate
    except Exception as exc:
        log.debug(f"Sina USDCNY failed: {exc}")
        return None
