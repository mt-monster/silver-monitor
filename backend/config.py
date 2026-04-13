import logging
from datetime import timedelta, timezone

PORT = 8765
FAST_POLL = 3
SLOW_POLL = 60

OZ_TO_KG = 32.1507
OZ_TO_G = 31.1035

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("silver_monitor")

CST = timezone(timedelta(hours=8))

HAS_AKSHARE = False
ak = None
try:
    import akshare as ak  # type: ignore

    HAS_AKSHARE = True
    log.info("akshare loaded OK")
except ImportError:
    log.warning("akshare not installed! Run: pip install akshare")
