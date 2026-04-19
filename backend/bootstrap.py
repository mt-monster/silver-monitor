import time

from backend.analytics import rebuild_all_cache
from backend.config import log
from backend.sources import (
    fetch_comex_gold_sina,
    fetch_comex_sina,
    fetch_hujin_sina,
    fetch_huyin_sina,
)
from backend.infoway import fetch_comex_silver_infoway, fetch_comex_gold_infoway, fetch_btc_infoway
from backend.state import state


def prime_caches():
    log.info("Initial fast data fetch...")

    em = fetch_huyin_sina()
    if em:
        state.silver_cache["data"] = em
        state.silver_cache["ts"] = time.time()
        log.info(f"[HuYin/{em.get('source', '?')}] price={em['price']}")

    co = fetch_comex_sina()
    if not co:
        co = fetch_comex_silver_infoway()
        if co:
            log.info("[Startup] Using Infoway for COMEX silver")
    if co:
        state.comex_silver_cache["data"] = co
        state.comex_silver_cache["ts"] = time.time()
        log.info(f"[COMEX/{co.get('source', 'unknown')}] price=${co['price']}/oz")

    au = fetch_hujin_sina()
    if au:
        state.gold_cache["data"] = au
        state.gold_cache["ts"] = time.time()
        log.info(f"[HuJin/{au.get('source', '?')}] price={au['price']}")

    cg = fetch_comex_gold_sina()
    if not cg:
        cg = fetch_comex_gold_infoway()
        if cg:
            log.info("[Startup] Using Infoway for COMEX gold")
    if cg:
        state.comex_gold_cache["data"] = cg
        state.comex_gold_cache["ts"] = time.time()
        log.info(f"[COMEX-Gold/{cg.get('source', 'unknown')}] price=${cg['price']}/oz")

    btc = fetch_btc_infoway()
    if btc:
        state.btc_cache["data"] = btc
        state.btc_cache["ts"] = time.time()
        log.info(f"[BTC/{btc.get('source', '?')}] price=${btc['price']}")

    rebuild_all_cache()
