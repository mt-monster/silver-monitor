import threading
import time
from datetime import datetime

from backend.alerts import check_tick_jump
from backend.analytics import rebuild_all_cache
from backend.config import CST, FAST_POLL, SLOW_POLL, log
from backend.market_hours import get_trading_status
from backend.sources import (
    fetch_comex_akshare_realtime,
    fetch_comex_gold_akshare_realtime,
    fetch_comex_gold_history,
    fetch_comex_gold_sina,
    fetch_comex_history,
    fetch_comex_sina,
    fetch_hujin_akshare_realtime,
    fetch_hujin_history,
    fetch_hujin_sina,
    fetch_huyin_akshare_realtime,
    fetch_huyin_history,
    fetch_huyin_sina,
    fetch_usdcny_sina,
)
from backend.state import state
from backend.utils import get_conv, get_conv_gold


class FastDataPoller(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        log.info(f"Fast poller started ({FAST_POLL}s interval)")
        while not self._stop.is_set():
            try:
                hu_status, hu_desc = get_trading_status("huyin")
                co_status, co_desc = get_trading_status("comex")

                if hu_status == "open":
                    em = fetch_huyin_sina()
                    if not em:
                        em = fetch_huyin_akshare_realtime()
                        if em:
                            log.warning("[HuYin] Using akshare 1min as fallback")
                else:
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
                    if em.get("closed"):
                        with state.cache_lock:
                            hu = state.silver_cache.get("data") or {}
                            hu.update(
                                {
                                    "closed": True,
                                    "status_desc": em["status_desc"],
                                    "timestamp": em["timestamp"],
                                    "datetime_cst": em["datetime_cst"],
                                }
                            )
                            if not hu.get("name"):
                                hu.update({k: em[k] for k in ["symbol", "name", "exchange", "currency", "unit"] if k in em})
                            state.silver_cache["data"] = hu
                            state.silver_cache["ts"] = time.time()
                    elif em.get("price", 0) > 0:
                        with state.cache_lock:
                            hu = state.silver_cache.get("data") or {}
                            prev_close = em.get("prevClose")
                            if not prev_close and hu.get("prevClose"):
                                prev_close = hu["prevClose"]
                            elif not prev_close:
                                prev_close = em.get("price")

                            change = em.get("change")
                            if change is None:
                                change = round(em["price"] - prev_close, 1) if prev_close else 0

                            change_pct = em.get("changePercent")
                            if change_pct is None:
                                change_pct = round(change / prev_close * 100, 2) if prev_close and prev_close != 0 else 0

                            hu.update(
                                {
                                    "price": em["price"],
                                    "prevClose": prev_close,
                                    "change": change,
                                    "changePercent": change_pct,
                                    "open": em.get("open") or hu.get("open"),
                                    "high": em.get("high") or hu.get("high"),
                                    "low": em.get("low") or hu.get("low"),
                                    "volume": em.get("volume", 0),
                                    "oi": em.get("oi", 0),
                                    "timestamp": em["timestamp"],
                                    "datetime_cst": em["datetime_cst"],
                                    "source": em.get("source", "Sina-AG0"),
                                    "closed": False,
                                }
                            )
                            if not hu.get("name"):
                                hu.update(em)
                            state.silver_cache["data"] = hu
                            state.silver_cache["ts"] = time.time()
                        check_tick_jump("hu", em["price"], em.get("source", "Sina-AG0"))

                if co_status == "open":
                    co_fast = fetch_comex_sina()
                    if not co_fast:
                        co_fast = fetch_comex_akshare_realtime()
                        if co_fast:
                            log.warning("[COMEX] Using akshare daily as fallback")
                else:
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
                    if co_fast.get("closed"):
                        with state.cache_lock:
                            co = state.comex_silver_cache.get("data") or {}
                            co.update(
                                {
                                    "closed": True,
                                    "status_desc": co_fast["status_desc"],
                                    "timestamp": co_fast["timestamp"],
                                    "datetime_cst": co_fast["datetime_cst"],
                                }
                            )
                            if not co.get("name"):
                                co.update({k: co_fast[k] for k in ["symbol", "name", "exchange", "currency", "unit"] if k in co_fast})
                            state.comex_silver_cache["data"] = co
                            state.comex_silver_cache["ts"] = time.time()
                    elif co_fast.get("price", 0) > 0:
                        with state.cache_lock:
                            co = state.comex_silver_cache.get("data") or {}
                            co.update(
                                {
                                    "price": co_fast["price"],
                                    "priceCny": co_fast.get("priceCny"),
                                    "prevClose": co_fast.get("prevClose"),
                                    "change": co_fast.get("change"),
                                    "changePercent": co_fast.get("changePercent"),
                                    "open": co_fast.get("open"),
                                    "high": co_fast.get("high"),
                                    "low": co_fast.get("low"),
                                    "timestamp": co_fast["timestamp"],
                                    "datetime_cst": co_fast.get("datetime_cst", ""),
                                    "usdCny": co_fast.get("usdCny", state.usd_cny_cache["rate"]),
                                    "convFactor": co_fast.get("convFactor", get_conv()),
                                    "source": co_fast.get("source", "unknown"),
                                    "closed": False,
                                }
                            )
                            if not co.get("name"):
                                co.update(co_fast)
                            state.comex_silver_cache["data"] = co
                            state.comex_silver_cache["ts"] = time.time()
                        check_tick_jump("comex", co_fast["price"], co_fast.get("source", "unknown"))
                else:
                    with state.cache_lock:
                        co = state.comex_silver_cache.get("data") or {}
                        hist = co.get("history", [])
                        if hist and not co.get("price"):
                            last_hist = hist[-1]
                            co["price"] = last_hist.get("y", 0)
                            co["source"] = co.get("source", "") + "+hist-fallback"
                            co["timestamp"] = int(time.time() * 1000)
                            co["datetime_cst"] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
                            state.comex_silver_cache["data"] = co
                            state.comex_silver_cache["ts"] = time.time()
                            log.info(f"[COMEX/fallback] price={co['price']} from history")

                if hu_status == "open":
                    au = fetch_hujin_sina()
                    if not au:
                        au = fetch_hujin_akshare_realtime()
                        if au:
                            log.warning("[HuJin] Using akshare 1min as fallback")
                else:
                    au = {
                        "symbol": "AU2606",
                        "name": "沪金主力",
                        "exchange": "SHFE",
                        "currency": "CNY",
                        "unit": "元/克",
                        "closed": True,
                        "status_desc": hu_desc,
                        "timestamp": int(time.time() * 1000),
                        "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
                    }

                if au:
                    if au.get("closed"):
                        with state.cache_lock:
                            gd = state.gold_cache.get("data") or {}
                            gd.update(
                                {
                                    "closed": True,
                                    "status_desc": au["status_desc"],
                                    "timestamp": au["timestamp"],
                                    "datetime_cst": au["datetime_cst"],
                                }
                            )
                            if not gd.get("name"):
                                gd.update({k: au[k] for k in ["symbol", "name", "exchange", "currency", "unit"] if k in au})
                            state.gold_cache["data"] = gd
                            state.gold_cache["ts"] = time.time()
                    elif au.get("price", 0) > 0:
                        with state.cache_lock:
                            gd = state.gold_cache.get("data") or {}
                            prev_close = au.get("prevClose") or gd.get("prevClose") or au.get("price")
                            change = au.get("change")
                            if change is None:
                                change = round(au["price"] - prev_close, 2) if prev_close else 0
                            change_pct = au.get("changePercent")
                            if change_pct is None:
                                change_pct = round(change / prev_close * 100, 2) if prev_close and prev_close != 0 else 0
                            gd.update(
                                {
                                    "price": au["price"],
                                    "prevClose": prev_close,
                                    "change": change,
                                    "changePercent": change_pct,
                                    "open": au.get("open") or gd.get("open"),
                                    "high": au.get("high") or gd.get("high"),
                                    "low": au.get("low") or gd.get("low"),
                                    "volume": au.get("volume", 0),
                                    "timestamp": au["timestamp"],
                                    "datetime_cst": au["datetime_cst"],
                                    "source": au.get("source", "Sina-AU0"),
                                    "closed": False,
                                }
                            )
                            if not gd.get("name"):
                                gd.update(au)
                            state.gold_cache["data"] = gd
                            state.gold_cache["ts"] = time.time()
                        check_tick_jump("hujin", au["price"], au.get("source", "Sina-AU0"))

                if co_status == "open":
                    co_gold = fetch_comex_gold_sina()
                    if not co_gold:
                        co_gold = fetch_comex_gold_akshare_realtime()
                        if co_gold:
                            log.warning("[COMEX-Gold] Using akshare daily as fallback")
                else:
                    co_gold = {
                        "symbol": "GC=F",
                        "name": "COMEX Gold Futures",
                        "exchange": "CME/COMEX",
                        "currency": "USD",
                        "unit": "$/oz",
                        "closed": True,
                        "status_desc": co_desc,
                        "timestamp": int(time.time() * 1000),
                        "datetime_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
                    }

                if co_gold:
                    if co_gold.get("closed"):
                        with state.cache_lock:
                            cg = state.comex_gold_cache.get("data") or {}
                            cg.update(
                                {
                                    "closed": True,
                                    "status_desc": co_gold["status_desc"],
                                    "timestamp": co_gold["timestamp"],
                                    "datetime_cst": co_gold["datetime_cst"],
                                }
                            )
                            if not cg.get("name"):
                                cg.update({k: co_gold[k] for k in ["symbol", "name", "exchange", "currency", "unit"] if k in co_gold})
                            state.comex_gold_cache["data"] = cg
                            state.comex_gold_cache["ts"] = time.time()
                    elif co_gold.get("price", 0) > 0:
                        with state.cache_lock:
                            cg = state.comex_gold_cache.get("data") or {}
                            cg.update(
                                {
                                    "price": co_gold["price"],
                                    "priceCnyG": co_gold.get("priceCnyG"),
                                    "prevClose": co_gold.get("prevClose"),
                                    "change": co_gold.get("change"),
                                    "changePercent": co_gold.get("changePercent"),
                                    "open": co_gold.get("open"),
                                    "high": co_gold.get("high"),
                                    "low": co_gold.get("low"),
                                    "timestamp": co_gold["timestamp"],
                                    "datetime_cst": co_gold.get("datetime_cst", ""),
                                    "usdCny": co_gold.get("usdCny", state.usd_cny_cache["rate"]),
                                    "convFactor": co_gold.get("convFactor", get_conv_gold()),
                                    "source": co_gold.get("source", "unknown"),
                                    "closed": False,
                                }
                            )
                            if not cg.get("name"):
                                cg.update(co_gold)
                            state.comex_gold_cache["data"] = cg
                            state.comex_gold_cache["ts"] = time.time()
                        check_tick_jump("comex_gold", co_gold["price"], co_gold.get("source", "unknown"))

                rebuild_all_cache()
            except Exception as exc:
                log.error(f"Fast poll error: {exc}")

            self._stop.wait(FAST_POLL)


class SlowDataPoller(threading.Thread):
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
            hu_hist = fetch_huyin_history()
            if hu_hist:
                with state.cache_lock:
                    hu = state.silver_cache.get("data") or {}
                    hu["history"] = hu_hist
                    hu["historyCount"] = len(hu_hist)
                    if not hu.get("source"):
                        hu["source"] = "akshare-sina"
                    elif "akshare" not in hu.get("source", ""):
                        hu["source"] = hu.get("source", "") + "+akshare"
                    if not hu.get("name"):
                        hu.update({"name": "沪银主力", "symbol": "AG0", "exchange": "SHFE", "currency": "CNY", "unit": "元/kg"})
                    state.silver_cache["data"] = hu
                    state.silver_cache["ts"] = time.time()
                log.info(f"[HuYin/history] {len(hu_hist)} bars loaded")

            co_hist = fetch_comex_history()
            if co_hist:
                with state.cache_lock:
                    co = state.comex_silver_cache.get("data") or {}
                    co["history"] = co_hist
                    if not co.get("source"):
                        co["source"] = "akshare-XAG"
                    elif "akshare" not in co.get("source", ""):
                        co["source"] = co.get("source", "") + "+akshare"
                    if not co.get("name"):
                        co.update({"name": "COMEX Silver Futures", "symbol": "SI=F", "exchange": "CME/COMEX", "currency": "CNY", "unit": "元/kg"})
                    state.comex_silver_cache["data"] = co
                    state.comex_silver_cache["ts"] = time.time()
                log.info(f"[COMEX/history] {len(co_hist)} bars loaded")

            au_hist = fetch_hujin_history()
            if au_hist:
                with state.cache_lock:
                    gd = state.gold_cache.get("data") or {}
                    gd["history"] = au_hist
                    gd["historyCount"] = len(au_hist)
                    if not gd.get("source"):
                        gd["source"] = "akshare-sina"
                    elif "akshare" not in gd.get("source", ""):
                        gd["source"] = gd.get("source", "") + "+akshare"
                    if not gd.get("name"):
                        gd.update({"name": "沪金主力", "symbol": "AU0", "exchange": "SHFE", "currency": "CNY", "unit": "元/克"})
                    state.gold_cache["data"] = gd
                    state.gold_cache["ts"] = time.time()
                log.info(f"[HuJin/history] {len(au_hist)} bars loaded")

            cg_hist = fetch_comex_gold_history()
            if cg_hist:
                with state.cache_lock:
                    cg = state.comex_gold_cache.get("data") or {}
                    cg["history"] = cg_hist
                    if not cg.get("source"):
                        cg["source"] = "akshare-XAU"
                    elif "akshare" not in cg.get("source", ""):
                        cg["source"] = cg.get("source", "") + "+akshare"
                    if not cg.get("name"):
                        cg.update({"name": "COMEX Gold Futures", "symbol": "GC=F", "exchange": "CME/COMEX", "currency": "USD", "unit": "$/oz"})
                    state.comex_gold_cache["data"] = cg
                    state.comex_gold_cache["ts"] = time.time()
                log.info(f"[COMEX-Gold/history] {len(cg_hist)} bars loaded")

            rate = fetch_usdcny_sina()
            if not rate:
                log.warning("[USD/CNY] Sina failed, keeping cached rate")
                rate = state.usd_cny_cache["rate"]
            state.usd_cny_cache["rate"] = rate
            state.usd_cny_cache["ts"] = time.time()
            log.info(f"[USD/CNY] rate={rate}")

            rebuild_all_cache()
        except Exception as exc:
            log.error(f"Slow poll error: {exc}")
