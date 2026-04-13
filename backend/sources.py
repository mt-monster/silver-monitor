import time
from datetime import datetime
from urllib.request import Request, urlopen

from backend.config import CST, HAS_AKSHARE, ak, log
from backend.state import state
from backend.utils import get_conv, get_conv_gold


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
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.futures_zh_minute_sina(symbol="AG0", period="60")
        if df is None or df.empty:
            return None
        history = []
        for _, row in df.iterrows():
            dt_str = str(row["datetime"])
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                except Exception:
                    continue
            ts = int(dt.timestamp() * 1000)
            close_val = float(row["close"])
            if close_val > 0:
                history.append({"t": ts, "y": round(close_val, 1)})
        return history[-200:]
    except Exception as exc:
        log.warning(f"akshare huyin history failed: {exc}")
        return None


def fetch_comex_history():
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.futures_foreign_hist(symbol="XAG")
        if df is None or df.empty:
            return None
        history = []
        for _, row in df.tail(60).iterrows():
            try:
                dt_str = str(row["date"]).strip()
                close_val = float(row["close"])
                if close_val <= 0:
                    continue
                if " " in dt_str:
                    dt_obj = datetime.strptime(dt_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                else:
                    dt_obj = datetime.strptime(dt_str, "%Y-%m-%d")
                ts = int(dt_obj.replace(tzinfo=CST).timestamp() * 1000)
                history.append({"t": ts, "y": round(close_val, 3)})
            except (ValueError, KeyError, TypeError):
                continue
        return history[-60:]
    except Exception as exc:
        log.warning(f"akshare XAG history failed: {exc}")
        return None


def fetch_hujin_history():
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.futures_zh_minute_sina(symbol="AU0", period="60")
        if df is None or df.empty:
            return None
        history = []
        for _, row in df.iterrows():
            dt_str = str(row["datetime"])
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                except Exception:
                    continue
            ts = int(dt.timestamp() * 1000)
            close_val = float(row["close"])
            if close_val > 0:
                history.append({"t": ts, "y": round(close_val, 2)})
        return history[-200:]
    except Exception as exc:
        log.warning(f"akshare hujin history failed: {exc}")
        return None


def fetch_comex_gold_history():
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.futures_foreign_hist(symbol="XAU")
        if df is None or df.empty:
            return None
        history = []
        for _, row in df.tail(60).iterrows():
            try:
                dt_str = str(row["date"]).strip()
                close_val = float(row["close"])
                if close_val <= 0:
                    continue
                if " " in dt_str:
                    dt_obj = datetime.strptime(dt_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                else:
                    dt_obj = datetime.strptime(dt_str, "%Y-%m-%d")
                ts = int(dt_obj.replace(tzinfo=CST).timestamp() * 1000)
                history.append({"t": ts, "y": round(close_val, 2)})
            except (ValueError, KeyError, TypeError):
                continue
        return history[-60:]
    except Exception as exc:
        log.warning(f"akshare XAU history failed: {exc}")
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


def fetch_huyin_akshare_realtime():
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.futures_zh_minute_sina(symbol="AG0", period="1")
        if df is None or df.empty:
            return None

        last_row = df.iloc[-1]
        price = float(last_row["close"])
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
    except Exception as exc:
        log.debug(f"akshare realtime HuYin failed: {exc}")
        return None


def fetch_comex_akshare_realtime():
    if not HAS_AKSHARE:
        return None
    try:
        conv = get_conv()
        df = ak.futures_foreign_hist(symbol="XAG")
        if df is None or df.empty:
            return None

        last_row = df.iloc[-1]
        close_usd = float(last_row["close"])
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
            "usdCny": state.usd_cny_cache["rate"],
        }
    except Exception as exc:
        log.debug(f"akshare realtime XAG failed: {exc}")
        return None


def fetch_hujin_akshare_realtime():
    if not HAS_AKSHARE:
        return None
    try:
        df = ak.futures_zh_minute_sina(symbol="AU0", period="1")
        if df is None or df.empty:
            return None
        last_row = df.iloc[-1]
        price = float(last_row["close"])
        if price <= 0:
            return None
        return {
            "source": "akshare-realtime",
            "symbol": "AU0",
            "name": "沪金主力",
            "exchange": "SHFE",
            "currency": "CNY",
            "unit": "元/克",
            "price": round(price, 2),
            "timestamp": int(time.time() * 1000),
            "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as exc:
        log.debug(f"akshare realtime HuJin failed: {exc}")
        return None


def fetch_comex_gold_akshare_realtime():
    if not HAS_AKSHARE:
        return None
    try:
        conv_g = get_conv_gold()
        df = ak.futures_foreign_hist(symbol="XAU")
        if df is None or df.empty:
            return None
        last_row = df.iloc[-1]
        close_usd = float(last_row["close"])
        if close_usd <= 0:
            return None
        price_cny_g = close_usd * conv_g
        return {
            "source": "akshare-latest",
            "symbol": "XAU",
            "name": "COMEX Gold (XAU/USD)",
            "exchange": "CME/COMEX",
            "currency": "USD",
            "unit": "$/oz",
            "price": round(close_usd, 2),
            "priceCnyG": round(price_cny_g, 2),
            "timestamp": int(time.time() * 1000),
            "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            "convFactor": conv_g,
            "usdCny": state.usd_cny_cache["rate"],
        }
    except Exception as exc:
        log.debug(f"akshare realtime XAU failed: {exc}")
        return None
