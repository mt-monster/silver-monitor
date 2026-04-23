import json
import queue
import threading
import time
from datetime import datetime

from backend.alerts import check_tick_jump
from backend.instruments import REGISTRY, fetch_instrument, get_enabled_instruments
from backend.research.samples import append_huyin_research_sample
from backend.analytics import rebuild_all_cache
from backend.config import CST, FAST_POLL, SLOW_POLL, RUNTIME_CONFIG, log
from backend.market_hours import get_trading_status
from backend.sources import (
    fetch_comex_gold_history,
    fetch_comex_gold_sina,
    fetch_comex_history,
    fetch_comex_sina,
    fetch_hujin_history,
    fetch_hujin_sina,
    fetch_huyin_history,
    fetch_huyin_sina,
    fetch_usdcny_sina,
)
from backend.ifind import fetch_huyin_ifind, fetch_comex_silver_ifind, fetch_comex_gold_ifind
from backend.infoway import fetch_comex_silver_infoway, fetch_comex_gold_infoway, fetch_btc_infoway
from backend.state import state
from backend.strategies.momentum import calc_momentum, _apply_signal_cooldown
from backend.utils import get_conv, get_conv_gold

# 时间窗口采样：每个 bar 代表固定时长内的最新价格（毫秒）
BAR_WINDOW_MS: int = int(RUNTIME_CONFIG.get("frontend", {}).get("bar_window_ms", 30000))


# ── 数据源动态分发 ──────────────────────────────────────────────
# (instrument_id, source_key) → fetch function
_SOURCE_DISPATCH = {
    ("ag0", "ifind"): fetch_huyin_ifind,
    ("ag0", "sina"): fetch_huyin_sina,
    ("xag", "ifind"): fetch_comex_silver_ifind,
    ("xag", "infoway"): fetch_comex_silver_infoway,
    ("xag", "sina"): fetch_comex_sina,
    ("au0", "sina"): fetch_hujin_sina,
    ("xau", "ifind"): fetch_comex_gold_ifind,
    ("xau", "infoway"): fetch_comex_gold_infoway,
    ("xau", "sina"): fetch_comex_gold_sina,
    ("btc", "infoway_crypto"): fetch_btc_infoway,
}

# 可用数据源注册表（Admin UI 展示）
SOURCE_REGISTRY = {
    "ag0": {"name": "沪银 AG0", "sources": ["ifind", "sina"]},
    "xag": {"name": "COMEX 银 XAG", "sources": ["ifind", "infoway", "sina"]},
    "au0": {"name": "沪金 AU0", "sources": ["sina"]},
    "xau": {"name": "COMEX 金 XAU", "sources": ["ifind", "infoway", "sina"]},
    "btc": {"name": "BTC", "sources": ["infoway_crypto"]},
}

SOURCE_LABELS = {
    "sina": "Sina 财经",
    "ifind": "iFinD (同花顺)",
    "infoway": "Infoway WS",
    "infoway_crypto": "Infoway WS (加密)",
}


def _fetch_by_priority(inst_id: str):
    """按 state.source_priority 优先级顺序尝试获取数据，返回第一个成功的结果。"""
    priority = state.source_priority.get(inst_id, [])
    for src in priority:
        fn = _SOURCE_DISPATCH.get((inst_id, src))
        if fn:
            result = fn()
            if result:
                log.debug(f"[{inst_id.upper()}] Using source: {src}")
                return result
    return None


# 品种 ID → config key 别名（与 backtest.py / core.js 保持一致）
_SYMBOL_ALIASES = {"ag0": "huyin", "xag": "comex", "au0": "hujin", "xau": "comex_gold"}


def _momentum_params_for(inst_id: str):
    """根据品种 ID 从 RUNTIME_CONFIG 构建动量参数（轻量版，避免循环导入 backtest）。
    当存在 realtime 段时，优先加载 realtime 下的微趋势参数，使实时信号与回测保持一致。"""
    from backend.strategies.momentum import MomentumParams
    config = RUNTIME_CONFIG.get("momentum") or {}
    defaults = config.get("default") if isinstance(config.get("default"), dict) else config
    resolved = _SYMBOL_ALIASES.get(inst_id, inst_id)
    sym_cfg = config.get(resolved, {}) if isinstance(config.get(resolved), dict) else {}

    # 实时数据专用参数覆盖（与 backtest.py momentum_params_from_body 逻辑对齐）
    rt_config = {}
    rt = config.get("realtime") if isinstance(config.get("realtime"), dict) else {}
    if isinstance(rt.get("default"), dict):
        rt_config = rt["default"]
    if resolved and resolved in rt and isinstance(rt[resolved], dict):
        rt_config = {**rt_config, **rt[resolved]}

    m = {**defaults, **sym_cfg, **rt_config}
    return MomentumParams(
        short_p=int(m.get("short_p", 5)),
        long_p=int(m.get("long_p", 20)),
        spread_entry=float(m.get("spread_entry", 0.10)),
        spread_strong=float(m.get("spread_strong", 0.35)),
        slope_entry=float(m.get("slope_entry", 0.02)),
        strength_multiplier=float(m.get("strength_multiplier", 120.0)),
        cooldown_bars=int(m.get("cooldown_bars", 0)),
        bb_period=int(m.get("bb_period", 20)),
        bb_mult=float(m.get("bb_mult", 2.0)),
        rsi_period=int(m.get("rsi_period", 14)),
        bb_buy_kill=float(m.get("bb_buy_kill", 0.3)),
        bb_sell_kill=float(m.get("bb_sell_kill", 0.7)),
        min_volatility_pct=float(m.get("min_volatility_pct", 0.0)),
    )


def _recompute_signals(inst_ids: list[str]):
    """重算指定品种的动量信号，存入 state.instrument_signals。
    使用 realtime_backtest_buffers（1秒采样）以与回测口径保持一致。
    支持 cooldown_bars：方向翻转后 N 个 bar 内压制信号为 neutral。"""
    with state.cache_lock:
        for iid in inst_ids:
            rt_buf = state.realtime_backtest_buffers.get(iid, [])
            buf = [p["y"] for p in rt_buf]
            params = _momentum_params_for(iid)
            if len(buf) >= params.long_p + 2:
                raw = calc_momentum(buf, params)
                if raw:
                    sig = raw["signal"]
                    cooldown = state.instrument_momentum_cooldown.get(iid, 0)
                    last_active = state.instrument_momentum_last_active.get(iid, "neutral")

                    final_sig, new_cooldown, updated_last = _apply_signal_cooldown(
                        sig, last_active, cooldown, params.cooldown_bars
                    )

                    if final_sig != sig:
                        raw["originalSignal"] = sig
                    raw["signal"] = final_sig
                    state.instrument_momentum_cooldown[iid] = new_cooldown
                    if updated_last:
                        state.instrument_momentum_last_active[iid] = sig

                    state.instrument_signals[iid] = raw
                else:
                    state.instrument_signals[iid] = None
            else:
                state.instrument_signals[iid] = None


def _reversal_params_for(inst_id: str):
    """根据品种 ID 从 RUNTIME_CONFIG 构建反转参数（轻量版）。"""
    from backend.strategies.reversal import ReversalParams
    config = RUNTIME_CONFIG.get("reversal") or {}
    defaults = config.get("default") if isinstance(config.get("default"), dict) else config
    resolved = _SYMBOL_ALIASES.get(inst_id, inst_id)
    sym_cfg = config.get(resolved, {}) if isinstance(config.get(resolved), dict) else {}

    # 实时数据专用参数覆盖
    rt_config = {}
    rt = config.get("realtime") if isinstance(config.get("realtime"), dict) else {}
    if isinstance(rt.get("default"), dict):
        rt_config = rt["default"]
    if resolved and resolved in rt and isinstance(rt[resolved], dict):
        rt_config = {**rt_config, **rt[resolved]}

    m = {**defaults, **sym_cfg, **rt_config}
    return ReversalParams(
        rsi_period=int(m.get("rsi_period", 14)),
        rsi_oversold=float(m.get("rsi_oversold", 30.0)),
        rsi_overbought=float(m.get("rsi_overbought", 70.0)),
        rsi_extreme_low=float(m.get("rsi_extreme_low", 20.0)),
        rsi_extreme_high=float(m.get("rsi_extreme_high", 80.0)),
        bb_period=int(m.get("bb_period", 20)),
        bb_mult=float(m.get("bb_mult", 2.0)),
        pctb_low=float(m.get("pctb_low", 0.05)),
        pctb_high=float(m.get("pctb_high", 0.95)),
        pctb_extreme_low=float(m.get("pctb_extreme_low", -0.05)),
        pctb_extreme_high=float(m.get("pctb_extreme_high", 1.05)),
        ema_period=int(m.get("ema_period", 20)),
        deviation_entry=float(m.get("deviation_entry", 1.5)),
        deviation_strong=float(m.get("deviation_strong", 2.5)),
        rsi_weight=float(m.get("rsi_weight", 0.4)),
        bb_weight=float(m.get("bb_weight", 0.35)),
        deviation_weight=float(m.get("deviation_weight", 0.25)),
        min_score=float(m.get("min_score", 0.5)),
        strong_score=float(m.get("strong_score", 0.8)),
        cooldown_bars=int(m.get("cooldown_bars", 2)),
    )


def _recompute_reversal_signals(inst_ids: list[str]):
    """重算指定品种的反转信号，存入 state.instrument_reversal_signals。
    使用 realtime_backtest_buffers（1秒采样）而非 instrument_price_buffers（30秒bar），
    使反转信号能在秒级响应，与回测的高频数据口径一致。
    支持 cooldown_bars：方向翻转后 N 个 bar 内压制信号为 neutral。
    """
    from backend.strategies.reversal import calc_reversal
    with state.cache_lock:
        for iid in inst_ids:
            rt_buf = state.realtime_backtest_buffers.get(iid, [])
            buf = [p["y"] for p in rt_buf]
            params = _reversal_params_for(iid)
            min_len = max(params.rsi_period + 1, params.bb_period, params.ema_period) + 2
            if len(buf) >= min_len:
                try:
                    raw = calc_reversal(buf, params)
                    if raw:
                        sig = raw["signal"]
                        cooldown = state.instrument_reversal_cooldown.get(iid, 0)
                        last_active = state.instrument_reversal_last_active.get(iid, "neutral")

                        final_sig, new_cooldown, updated_last = _apply_signal_cooldown(
                            sig, last_active, cooldown, params.cooldown_bars
                        )

                        if final_sig != sig:
                            raw["originalSignal"] = sig
                        raw["signal"] = final_sig
                        state.instrument_reversal_cooldown[iid] = new_cooldown
                        if updated_last:
                            state.instrument_reversal_last_active[iid] = sig

                        state.instrument_reversal_signals[iid] = raw
                    else:
                        state.instrument_reversal_signals[iid] = None
                except Exception as e:
                    log.error(f"[_recompute_reversal_signals] {iid} error: {e}")
                    state.instrument_reversal_signals[iid] = None
            else:
                state.instrument_reversal_signals[iid] = None


def _recompute_mtf_and_combined(inst_ids: list[str]):
    """重算 MTF 趋势和组合信号。
    使用 instrument_price_buffers（30s bar）计算大局趋势，
    再结合动量/反转信号生成组合决策。
    """
    from backend.strategies.mtf import calc_mtf_from_buffer
    from backend.strategies.combined import calc_combined_signal, CombinedSignalParams

    with state.cache_lock:
        for iid in inst_ids:
            buf_30s = state.instrument_price_buffers.get(iid, [])
            if len(buf_30s) >= 40:
                try:
                    mtf = calc_mtf_from_buffer(buf_30s)
                    state.instrument_mtf_trends[iid] = mtf
                except Exception as e:
                    log.error(f"[_recompute_mtf] {iid} error: {e}")
                    state.instrument_mtf_trends[iid] = None
            else:
                state.instrument_mtf_trends[iid] = None

            mom = state.instrument_signals.get(iid)
            rev = state.instrument_reversal_signals.get(iid)
            mtf_trend = state.instrument_mtf_trends.get(iid, {}).get("trend", "sideways") if state.instrument_mtf_trends.get(iid) else "sideways"

            try:
                combined = calc_combined_signal(mom, rev, mtf_trend, CombinedSignalParams())
                state.instrument_combined_signals[iid] = combined
            except Exception as e:
                log.error(f"[_recompute_combined] {iid} error: {e}")
                state.instrument_combined_signals[iid] = None


def _notify_sse(event: str, payload: dict):
    """向所有 SSE 客户端广播事件。"""
    msg = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
    with state.sse_lock:
        dead: list[queue.SimpleQueue] = []
        for q in state.sse_queues:
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(q)
        for q in dead:
            state.sse_queues.discard(q)


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

                # ── 沪银 (AG0) ──
                if hu_status == "open":
                    em = _fetch_by_priority("ag0")
                else:
                    em = {
                        "symbol": "AG0",
                        "name": "沪银主力连续",
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
                        append_huyin_research_sample(em["timestamp"], em["price"])
                        check_tick_jump("hu", em["price"], em.get("source", "Sina-AG0"))

                # ── COMEX 银 (XAG) ──
                if co_status == "open":
                    co_fast = _fetch_by_priority("xag")
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

                # ── 沪金 (AU0) ──
                if hu_status == "open":
                    au = _fetch_by_priority("au0")
                else:
                    au = {
                        "symbol": "AU0",
                        "name": "沪金主力连续",
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

                # ── COMEX 金 (XAU) ──
                if co_status == "open":
                    co_gold = _fetch_by_priority("xau")
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

                # ── BTC (24/7, priority-based) ──
                btc_data = _fetch_by_priority("btc")
                if btc_data and btc_data.get("price", 0) > 0:
                    with state.cache_lock:
                        bt = state.btc_cache.get("data") or {}
                        bt.update(
                            {
                                "price": btc_data["price"],
                                "priceCny": btc_data.get("priceCny"),
                                "prevClose": btc_data.get("prevClose"),
                                "change": btc_data.get("change"),
                                "changePercent": btc_data.get("changePercent"),
                                "open": btc_data.get("open"),
                                "high": btc_data.get("high"),
                                "low": btc_data.get("low"),
                                "volume": btc_data.get("volume", 0),
                                "timestamp": btc_data["timestamp"],
                                "datetime_cst": btc_data.get("datetime_cst", ""),
                                "usdCny": btc_data.get("usdCny", state.usd_cny_cache["rate"]),
                                "source": btc_data.get("source", "Infoway-BTC"),
                                "closed": False,
                            }
                        )
                        if not bt.get("name"):
                            bt.update({k: btc_data[k] for k in ["symbol", "name", "exchange", "currency", "unit"] if k in btc_data})
                        state.btc_cache["data"] = bt
                        state.btc_cache["ts"] = time.time()
                    check_tick_jump("btc", btc_data["price"], btc_data.get("source", "Infoway-BTC"))

                _buffer_precious_prices()
                _recompute_signals(["ag0", "xag", "au0", "xau", "btc"])
                _recompute_reversal_signals(["ag0", "xag", "au0", "xau", "btc"])
                _recompute_mtf_and_combined(["ag0", "xag", "au0", "xau", "btc"])
                rebuild_all_cache()
                state.data_version += 1
                _notify_sse("data", _build_sse_snapshot())
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
                        hu["source"] = "Sina-history"
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
                        co["source"] = "Sina-history"
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
                        gd["source"] = "Sina-history"
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
                        cg["source"] = "Sina-history"
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


# 跟踪每个品种最后持久化到 SQLite 的价格和时间戳，避免写入重复 tick
_last_persisted_tick: dict[str, tuple[int, float]] = {}

# ── 通用商品全品类轮询 ─────────────────────────────────────────────

# 已由 FastDataPoller 处理的品种（避免重复获取）
_FAST_COVERED = {"ag0", "au0", "xag", "xau"}


class CommodityPoller(threading.Thread):
    """轮询 REGISTRY 中除贵金属外的所有品种，存入 state.instrument_caches。"""

    def __init__(self, interval: int | None = None):
        super().__init__(daemon=True)
        self._stop = threading.Event()
        self._interval = interval or FAST_POLL

    def stop(self):
        self._stop.set()

    def run(self):
        instruments = [i for i in get_enabled_instruments() if i.id not in _FAST_COVERED]
        log.info(f"CommodityPoller started: {len(instruments)} instruments, {self._interval}s interval")
        while not self._stop.is_set():
            try:
                for inst in instruments:
                    if self._stop.is_set():
                        break
                    data = fetch_instrument(inst)
                    if data and data.get("price", 0) > 0:
                        with state.cache_lock:
                            existing = state.instrument_caches.get(inst.id, {}).get("data") or {}
                            existing.update(data)
                            state.instrument_caches[inst.id] = {"data": existing, "ts": time.time()}
                            # 时间窗口采样 price buffer
                            _buf = state.instrument_price_buffers.get(inst.id, [])
                            _last_ts = state.instrument_bar_timestamps.get(inst.id, 0)
                            _ts_ms = data.get("timestamp") or int(time.time() * 1000)
                            if not _buf or _ts_ms - _last_ts >= BAR_WINDOW_MS:
                                _buf.append(data["price"])
                                state.instrument_bar_timestamps[inst.id] = _ts_ms
                                if len(_buf) > 200:
                                    _buf = _buf[-200:]
                            else:
                                _buf[-1] = data["price"]
                            state.instrument_price_buffers[inst.id] = _buf
                updated_ids = [inst.id for inst in instruments]
                _recompute_signals(updated_ids)
                _recompute_reversal_signals(updated_ids)
                _recompute_mtf_and_combined(updated_ids)
                state.data_version += 1
            except Exception as exc:
                log.error(f"CommodityPoller error: {exc}")
            self._stop.wait(self._interval)


def _build_sse_snapshot() -> dict:
    """构建 SSE 推送的精简数据快照（只含价格/涨幅/信号，不含 history 等大字段）。"""
    snapshot: dict = {"v": state.data_version, "ts": int(time.time() * 1000)}

    # 贵金属四品种 + BTC
    for key, cache in [("huyin", state.silver_cache), ("comex", state.comex_silver_cache),
                       ("hujin", state.gold_cache), ("comexGold", state.comex_gold_cache),
                       ("btc", state.btc_cache)]:
        d = cache.get("data") or {}
        snapshot[key] = {
            "price": d.get("price"),
            "change": d.get("change"),
            "changePercent": d.get("changePercent"),
            "closed": d.get("closed", False),
            "timestamp": d.get("timestamp"),
            "datetime_cst": d.get("datetime_cst"),
            "source": d.get("source"),
        }

    # 全品种信号（包含动量信号与反转信号）
    sigs = {}
    rv_sigs = {}
    mtf_trends = {}
    combined_sigs = {}
    with state.cache_lock:
        for iid, sig in state.instrument_signals.items():
            if sig:
                sigs[iid] = sig
        for iid, rsig in state.instrument_reversal_signals.items():
            if rsig:
                rv_sigs[iid] = rsig
        for iid, mtf in state.instrument_mtf_trends.items():
            if mtf:
                mtf_trends[iid] = mtf
        for iid, cmb in state.instrument_combined_signals.items():
            if cmb:
                combined_sigs[iid] = cmb
    snapshot["signals"] = sigs
    snapshot["reversalSignals"] = rv_sigs
    snapshot["mtfTrends"] = mtf_trends
    snapshot["combinedSignals"] = combined_sigs

    # 价格序列（供前端与后端使用同一输入，消除 RSI 不一致）
    with state.cache_lock:
        snapshot["priceBuffers"] = {
            iid: buf[-60:] for iid, buf in state.instrument_price_buffers.items() if len(buf) >= 2
        }
        snapshot["realtimeBacktestBuffers"] = {
            iid: buf[-60:] for iid, buf in state.realtime_backtest_buffers.items() if len(buf) >= 2
        }
    return snapshot


def _buffer_precious_prices():
    """将贵金属/BTC 最新价格按时间窗口（BAR_WINDOW_MS）采样到 instrument_price_buffers。
    同一时间窗口内覆写末条（取最新价），跨窗口时追加新 bar，最多保留 200 条。
    同时写入 realtime_backtest_buffers（每秒一个点，最多300点≈5分钟），用于短周期回测。
    并将 tick 数据持久化到 SQLite，供历史 5 分钟窗口扫描使用。
    """
    mapping = {
        "ag0": state.silver_cache,
        "xag": state.comex_silver_cache,
        "au0": state.gold_cache,
        "xau": state.comex_gold_cache,
        "btc": state.btc_cache,
    }
    now_ms = int(time.time() * 1000)
    now_date = datetime.now(CST).strftime("%Y-%m-%d")
    tick_batch = []
    with state.cache_lock:
        for inst_id, cache in mapping.items():
            d = cache.get("data")
            if not d or not d.get("price"):
                continue
            px = d["price"]
            ts_ms = d.get("timestamp") or now_ms

            # ── 时间窗口 bar（用于信号计算）
            buf = state.instrument_price_buffers.get(inst_id, [])
            last_bar_ts = state.instrument_bar_timestamps.get(inst_id, 0)
            if not buf or ts_ms - last_bar_ts >= BAR_WINDOW_MS:
                buf.append(px)
                state.instrument_bar_timestamps[inst_id] = ts_ms
                if len(buf) > 200:
                    buf = buf[-200:]
            else:
                buf[-1] = px  # 同一窗口：更新末条为最新价格
            state.instrument_price_buffers[inst_id] = buf

            # ── 高频实时采样（用于短周期回测）
            rt_buf = state.realtime_backtest_buffers.get(inst_id, [])
            rt_buf.append({"t": ts_ms, "y": px})
            if len(rt_buf) > 300:
                rt_buf = rt_buf[-300:]
            state.realtime_backtest_buffers[inst_id] = rt_buf

            # ── 持久化 tick 到 SQLite（只在价格变化时写入，避免重复）
            last_ts, last_px = _last_persisted_tick.get(inst_id, (0, 0.0))
            if px != last_px or ts_ms - last_ts > 60_000:  # 价格变化 或 超过 1 分钟强制写入
                tick_batch.append((inst_id, ts_ms, px, now_date))
                _last_persisted_tick[inst_id] = (ts_ms, px)

    # 批量写入 SQLite（在锁外执行，避免阻塞）
    if tick_batch:
        try:
            from backend.tick_storage import save_ticks_batch
            save_ticks_batch(tick_batch)
        except Exception as exc:
            log.debug(f"[tick_storage] batch write error: {exc}")


def sync_precious_to_instrument_caches():
    """将 FastDataPoller 的贵金属数据同步到 instrument_caches，供统一 API 使用。"""
    mapping = {
        "ag0": state.silver_cache,
        "xag": state.comex_silver_cache,
        "au0": state.gold_cache,
        "xau": state.comex_gold_cache,
    }
    for inst_id, cache in mapping.items():
        d = cache.get("data")
        if d and d.get("price"):
            inst = REGISTRY.get(inst_id)
            if inst:
                merged = {
                    "id": inst_id,
                    "name": inst.name,
                    "exchange": inst.exchange,
                    "currency": inst.currency,
                    "unit": inst.unit,
                    "price": d.get("price"),
                    "prevClose": d.get("prevClose"),
                    "change": d.get("change"),
                    "changePercent": d.get("changePercent"),
                    "open": d.get("open"),
                    "high": d.get("high"),
                    "low": d.get("low"),
                    "volume": d.get("volume", 0),
                    "timestamp": d.get("timestamp"),
                    "datetime_cst": d.get("datetime_cst"),
                    "source": d.get("source"),
                    "closed": d.get("closed", False),
                }
                state.instrument_caches[inst_id] = {"data": merged, "ts": cache.get("ts", 0)}
                # Buffer price for signal computation
                _buf = state.instrument_price_buffers.get(inst_id, [])
                px = d["price"]
                if not _buf or _buf[-1] != px:
                    _buf.append(px)
                    if len(_buf) > 200:
                        _buf = _buf[-200:]
                    state.instrument_price_buffers[inst_id] = _buf
