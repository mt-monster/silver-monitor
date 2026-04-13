import time

from backend.analytics import rebuild_all_cache
from backend.config import log
from backend.sources import (
    fetch_comex_akshare_realtime,
    fetch_comex_gold_akshare_realtime,
    fetch_comex_gold_sina,
    fetch_comex_sina,
    fetch_hujin_akshare_realtime,
    fetch_hujin_sina,
    fetch_huyin_akshare_realtime,
    fetch_huyin_sina,
)
from backend.state import state


def prime_caches():
    log.info("Initial fast data fetch...")

    em = fetch_huyin_sina()
    if not em:
        log.warning("[Startup] Sina AG0 failed, trying akshare...")
        em = fetch_huyin_akshare_realtime()
    if em:
        state.silver_cache["data"] = em
        state.silver_cache["ts"] = time.time()
        log.info(f"[HuYin/{em.get('source', '?')}] price={em['price']}")

    co = fetch_comex_sina()
    if not co:
        log.warning("[Startup] Sina XAG failed, trying akshare...")
        co = fetch_comex_akshare_realtime()
    if co:
        state.comex_silver_cache["data"] = co
        state.comex_silver_cache["ts"] = time.time()
        log.info(f"[COMEX/{co.get('source', 'unknown')}] price=${co['price']}/oz")

    au = fetch_hujin_sina()
    if not au:
        log.warning("[Startup] Sina AU0 failed, trying akshare...")
        au = fetch_hujin_akshare_realtime()
    if au:
        state.gold_cache["data"] = au
        state.gold_cache["ts"] = time.time()
        log.info(f"[HuJin/{au.get('source', '?')}] price={au['price']}")

    cg = fetch_comex_gold_sina()
    if not cg:
        log.warning("[Startup] Sina XAU failed, trying akshare...")
        cg = fetch_comex_gold_akshare_realtime()
    if cg:
        state.comex_gold_cache["data"] = cg
        state.comex_gold_cache["ts"] = time.time()
        log.info(f"[COMEX-Gold/{cg.get('source', 'unknown')}] price=${cg['price']}/oz")

    rebuild_all_cache()
