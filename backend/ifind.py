"""iFinD (同花顺) data source client.

Provides a singleton client that manages login state and exposes
helper functions for fetching COMEX real-time quotes.

Two modes are supported:
  1. SDK mode  — uses the ``iFinDPy`` pip package (``pip install iFinDAPI``).
  2. HTTP mode — uses the REST API at ``quantapi.51ifind.com`` with a
     refresh_token / access_token flow.

The module falls back to HTTP mode automatically if the SDK is unavailable
or fails to load.
"""

import json
import threading
import time
from datetime import datetime

from backend.config import CST, RUNTIME_CONFIG, log

# ---------------------------------------------------------------------------
# Optional iFinDPy SDK import
# ---------------------------------------------------------------------------
_HAS_SDK = False
try:
    from iFinDPy import (
        THS_iFinDLogin,
        THS_iFinDLogout,
        THS_RQ,
    )
    _HAS_SDK = True
except Exception:
    pass

# Optional requests for HTTP mode
_HAS_REQUESTS = False
try:
    import requests as _requests
    _HAS_REQUESTS = True
except Exception:
    pass


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def _ifind_cfg() -> dict:
    return RUNTIME_CONFIG.get("ifind") or {}


# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------
class _IFinDClient:
    """Thread-safe singleton that maintains a persistent iFinD session."""

    def __init__(self):
        self._lock = threading.Lock()
        self._logged_in = False
        self._mode: str | None = None          # "sdk" or "http"
        self._access_token: str | None = None
        self._token_expire: float = 0           # epoch seconds
        self._last_login_attempt: float = 0
        self._login_cooldown = 30               # seconds between retries

    # ---- public API -------------------------------------------------------

    def ensure_login(self) -> bool:
        """Ensure that we are logged in.  Returns True if ready."""
        with self._lock:
            if self._logged_in:
                # For HTTP mode, check token expiry
                if self._mode == "http" and time.time() > self._token_expire - 300:
                    self._refresh_http_token()
                return self._logged_in
            # Cooldown
            if time.time() - self._last_login_attempt < self._login_cooldown:
                return False
            self._last_login_attempt = time.time()
            return self._do_login()

    @property
    def available(self) -> bool:
        return self._logged_in

    def realtime_quote(self, code: str, indicators: str = "latest;open;high;low;preClose;vol;amount;changeRatio;change;datetime") -> dict | None:
        """Fetch a real-time quote snapshot.  Returns a dict or None."""
        if not self.ensure_login():
            return None
        try:
            if self._mode == "sdk":
                return self._rq_sdk(code, indicators)
            elif self._mode == "http":
                return self._rq_http(code, indicators)
        except Exception as exc:
            log.debug(f"[iFinD] realtime_quote({code}) failed: {exc}")
            return None

    def logout(self):
        with self._lock:
            if self._logged_in and self._mode == "sdk":
                try:
                    THS_iFinDLogout()
                except Exception:
                    pass
            self._logged_in = False
            self._mode = None

    # ---- internal ---------------------------------------------------------

    def _do_login(self) -> bool:
        cfg = _ifind_cfg()
        if not cfg.get("enabled"):
            return False

        account = cfg.get("account", "")
        password = cfg.get("password", "")

        # Try SDK first
        if _HAS_SDK and account and password:
            try:
                ret = THS_iFinDLogin(account, password)
                if ret in (0, -201):
                    self._logged_in = True
                    self._mode = "sdk"
                    log.info("[iFinD] SDK login success")
                    return True
                else:
                    log.warning(f"[iFinD] SDK login failed: code={ret}")
            except Exception as exc:
                log.warning(f"[iFinD] SDK login exception: {exc}")

        # Try HTTP mode
        refresh_token = cfg.get("refresh_token", "")
        if _HAS_REQUESTS and refresh_token:
            return self._login_http(refresh_token)

        return False

    def _login_http(self, refresh_token: str) -> bool:
        try:
            resp = _requests.post(
                "https://quantapi.51ifind.com/api/v1/get_access_token",
                headers={
                    "Content-Type": "application/json",
                    "refresh_token": refresh_token,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("errorcode") == 0:
                self._access_token = data["data"]["access_token"]
                # Token valid for 7 days, refresh at 6 days
                self._token_expire = time.time() + 6 * 86400
                self._logged_in = True
                self._mode = "http"
                log.info("[iFinD] HTTP login success (access_token obtained)")
                return True
            else:
                log.warning(f"[iFinD] HTTP token failed: {data}")
        except Exception as exc:
            log.warning(f"[iFinD] HTTP token exception: {exc}")
        return False

    def _refresh_http_token(self):
        cfg = _ifind_cfg()
        refresh_token = cfg.get("refresh_token", "")
        if refresh_token:
            self._login_http(refresh_token)

    # ---- SDK real-time quote ----------------------------------------------

    def _rq_sdk(self, code: str, indicators: str) -> dict | None:
        result = THS_RQ(code, indicators, "")
        if result.errorcode != 0:
            log.debug(f"[iFinD/SDK] THS_RQ({code}) error: {result.errorcode} {result.errmsg}")
            # If session expired, mark as logged out to trigger re-login
            if result.errorcode in (-1, -5, -10001):
                with self._lock:
                    self._logged_in = False
            return None
        # result.data is a DataFrame; convert first row to dict
        df = result.data
        if df is None or df.empty:
            return None
        row = df.iloc[0].to_dict()
        row["_code"] = code
        return row

    # ---- HTTP real-time quote ---------------------------------------------

    def _rq_http(self, code: str, indicators: str) -> dict | None:
        # Map SDK-style indicators to HTTP API format
        indi_list = indicators.replace(";", ",")
        payload = {
            "codes": code,
            "indicators": indi_list,
        }
        headers = {
            "Content-Type": "application/json",
            "access_token": self._access_token or "",
        }
        resp = _requests.post(
            "https://quantapi.51ifind.com/api/v1/real_time_quotation",
            json=payload,
            headers=headers,
            timeout=10,
        )
        data = resp.json()
        if data.get("errorcode") != 0:
            log.debug(f"[iFinD/HTTP] RQ({code}) error: {data}")
            if data.get("errorcode") in (-1, -5, -10001, -403):
                with self._lock:
                    self._logged_in = False
            return None
        tables = data.get("tables", [])
        if not tables:
            return None
        table = tables[0]
        row = {}
        for key, values in table.get("table", {}).items():
            row[key] = values[0] if values else None
        row["_code"] = table.get("thscode", code)
        return row


# Module-level singleton
client = _IFinDClient()


# ---------------------------------------------------------------------------
# High-level fetch functions for COMEX data
# ---------------------------------------------------------------------------

def fetch_comex_silver_ifind() -> dict | None:
    """Fetch COMEX silver (XAG) real-time quote via iFinD.

    Returns a dict compatible with the existing fetch_comex_sina() format,
    or None on failure.
    """
    cfg = _ifind_cfg()
    code = cfg.get("comex_silver_code", "XAGUSD.FX")

    row = client.realtime_quote(code)
    if not row:
        return None

    try:
        from backend.state import state
        from backend.utils import get_conv

        price_usd = _float(row.get("latest"))
        if not price_usd or price_usd <= 0:
            return None

        conv = get_conv()
        usd_cny = state.usd_cny_cache["rate"]
        prev_close = _float(row.get("preClose")) or price_usd
        open_usd = _float(row.get("open")) or price_usd
        high_usd = _float(row.get("high")) or price_usd
        low_usd = _float(row.get("low")) or price_usd
        change = _float(row.get("change")) or round(price_usd - prev_close, 3)
        change_pct = _float(row.get("changeRatio")) or (
            round(change / prev_close * 100, 2) if prev_close else 0
        )

        price_cny = price_usd * conv
        dt_str = row.get("datetime", "")
        if not dt_str:
            dt_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

        result = {
            "source": "iFinD-XAG",
            "symbol": "XAG/USD",
            "name": "伦敦银 (XAG Spot)",
            "exchange": "CME/COMEX",
            "currency": "USD",
            "unit": "$/oz",
            "price": round(price_usd, 3),
            "priceCny": round(price_cny, 1),
            "prevClose": round(prev_close, 3),
            "change": round(change, 3),
            "changePercent": round(change_pct, 2),
            "open": round(open_usd, 3),
            "high": round(high_usd, 3),
            "low": round(low_usd, 3),
            "volume": 0,
            "timestamp": int(time.time() * 1000),
            "datetime_cst": dt_str,
            "usdCny": usd_cny,
            "convFactor": conv,
        }
        log.debug(f"[iFinD/XAG] ${price_usd:.3f}/oz  chg={change:+.3f}")
        return result
    except Exception as exc:
        log.debug(f"[iFinD] fetch_comex_silver failed: {exc}")
        return None


def fetch_huyin_ifind() -> dict | None:
    """Fetch 沪银主力 (AG0) real-time quote via iFinD.

    Returns a dict compatible with the existing fetch_huyin_sina() format,
    or None on failure.
    """
    cfg = _ifind_cfg()
    code = cfg.get("huyin_code", "AG00.SHF")

    row = client.realtime_quote(code)
    if not row:
        return None

    try:
        price = _float(row.get("latest"))
        if not price or price <= 0:
            return None

        prev_close = _float(row.get("preClose")) or price
        open_p = _float(row.get("open")) or price
        high_p = _float(row.get("high")) or price
        low_p = _float(row.get("low")) or price
        change = _float(row.get("change")) or round(price - prev_close, 1)
        change_pct = _float(row.get("changeRatio")) or (
            round(change / prev_close * 100, 2) if prev_close else 0
        )
        vol = _float(row.get("vol"))
        volume = int(vol) if vol else 0

        dt_str = row.get("datetime", "")
        if not dt_str:
            dt_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

        result = {
            "source": "iFinD-AG0",
            "symbol": "AG0",
            "name": "沪银主力连续",
            "exchange": "SHFE",
            "currency": "CNY",
            "unit": "元/kg",
            "price": round(price, 1),
            "prevClose": round(prev_close, 1),
            "change": round(change, 1),
            "changePercent": round(change_pct, 2),
            "open": round(open_p, 1),
            "high": round(high_p, 1),
            "low": round(low_p, 1),
            "volume": volume,
            "timestamp": int(time.time() * 1000),
            "datetime_cst": dt_str,
        }
        log.debug(f"[iFinD/AG0] {price:.1f} 元/kg  chg={change:+.1f}")
        return result
    except Exception as exc:
        log.debug(f"[iFinD] fetch_huyin failed: {exc}")
        return None


def fetch_comex_gold_ifind() -> dict | None:
    """Fetch COMEX gold (XAU) real-time quote via iFinD.

    Returns a dict compatible with the existing fetch_comex_gold_sina() format,
    or None on failure.
    """
    cfg = _ifind_cfg()
    code = cfg.get("comex_gold_code", "XAUUSD.FX")

    row = client.realtime_quote(code)
    if not row:
        return None

    try:
        from backend.state import state
        from backend.utils import get_conv_gold

        price_usd = _float(row.get("latest"))
        if not price_usd or price_usd <= 0:
            return None

        conv = get_conv_gold()
        usd_cny = state.usd_cny_cache["rate"]
        prev_close = _float(row.get("preClose")) or price_usd
        open_usd = _float(row.get("open")) or price_usd
        high_usd = _float(row.get("high")) or price_usd
        low_usd = _float(row.get("low")) or price_usd
        change = _float(row.get("change")) or round(price_usd - prev_close, 2)
        change_pct = _float(row.get("changeRatio")) or (
            round(change / prev_close * 100, 2) if prev_close else 0
        )

        price_cny_g = price_usd * conv
        dt_str = row.get("datetime", "")
        if not dt_str:
            dt_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

        result = {
            "source": "iFinD-XAU",
            "symbol": "XAU/USD",
            "name": "伦敦金 (XAU Spot)",
            "exchange": "CME/COMEX",
            "currency": "USD",
            "unit": "$/oz",
            "price": round(price_usd, 2),
            "priceCnyG": round(price_cny_g, 2),
            "prevClose": round(prev_close, 2),
            "change": round(change, 2),
            "changePercent": round(change_pct, 2),
            "open": round(open_usd, 2),
            "high": round(high_usd, 2),
            "low": round(low_usd, 2),
            "volume": 0,
            "timestamp": int(time.time() * 1000),
            "datetime_cst": dt_str,
            "usdCny": usd_cny,
            "convFactor": conv,
        }
        log.debug(f"[iFinD/XAU] ${price_usd:.2f}/oz  chg={change:+.2f}")
        return result
    except Exception as exc:
        log.debug(f"[iFinD] fetch_comex_gold failed: {exc}")
        return None


def _float(v) -> float | None:
    """Safely convert a value to float."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None  # NaN check
    except (ValueError, TypeError):
        return None
