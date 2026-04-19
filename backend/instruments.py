"""商品全品类注册表 + 通用 Sina 实时行情获取。

每个品种由 Instrument 描述，注册到 REGISTRY 后即自动纳入轮询和前端看板。
国内期货统一解析 nf_{SYMBOL}0 格式，国际品种解析 hf_{SYMBOL} 格式。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen

from backend.config import CST, log


# ── 品种定义 ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Instrument:
    id: str             # 唯一键: "ag0", "cu0", "xag" …
    name: str           # 显示名: "沪银主力"
    category: str       # 分类键: "precious_metals" | "base_metals" …
    exchange: str       # "SHFE" | "DCE" | "ZCE" | "INE" | "COMEX" | "NYMEX"
    currency: str       # "CNY" | "USD"
    unit: str           # "元/kg" | "元/吨" | "$/oz" …
    decimals: int       # 价格精度
    sina_code: str      # "nf_AG0" | "hf_XAG"
    is_intl: bool       # True → hf_ 国际格式
    color: str = "#888"
    market_hours: str = "shfe"  # "shfe" | "comex"


# ── 分类元数据 ────────────────────────────────────────────────────

CATEGORIES: dict[str, dict[str, Any]] = {
    "precious_metals": {"name": "贵金属", "icon": "💎", "order": 0},
    "base_metals":     {"name": "有色金属", "icon": "🔩", "order": 1},
    "ferrous":         {"name": "黑色系", "icon": "⚙️", "order": 2},
    "energy":          {"name": "能源化工", "icon": "🛢️", "order": 3},
    "agriculture":     {"name": "农产品", "icon": "🌾", "order": 4},
    "international":   {"name": "国际", "icon": "🌍", "order": 5},
}


# ── 注册表 ────────────────────────────────────────────────────────

REGISTRY: dict[str, Instrument] = {}


def _r(id_: str, name: str, cat: str, exch: str, ccy: str, unit: str,
       dec: int, sina: str, intl: bool = False, color: str = "#888",
       hours: str = "shfe") -> Instrument:
    inst = Instrument(id_, name, cat, exch, ccy, unit, dec, sina, intl, color, hours)
    REGISTRY[id_] = inst
    return inst


# ── 贵金属 ────────────────────────────────────────────────────────
_r("ag0",  "沪银主力", "precious_metals", "SHFE",  "CNY", "元/kg", 1, "nf_AG0", color="#e74c3c")
_r("au0",  "沪金主力", "precious_metals", "SHFE",  "CNY", "元/克", 2, "nf_AU0", color="#f1c40f")
_r("xag",  "伦敦银",   "precious_metals", "COMEX", "USD", "$/oz",  3, "hf_XAG", True, "#27ae60", "comex")
_r("xau",  "伦敦金",   "precious_metals", "COMEX", "USD", "$/oz",  2, "hf_XAU", True, "#e67e22", "comex")

# ── 有色金属 ──────────────────────────────────────────────────────
_r("cu0",  "沪铜", "base_metals", "SHFE", "CNY", "元/吨", 0, "nf_CU0", color="#e67e22")
_r("al0",  "沪铝", "base_metals", "SHFE", "CNY", "元/吨", 0, "nf_AL0", color="#95a5a6")
_r("zn0",  "沪锌", "base_metals", "SHFE", "CNY", "元/吨", 0, "nf_ZN0", color="#3498db")
_r("pb0",  "沪铅", "base_metals", "SHFE", "CNY", "元/吨", 0, "nf_PB0", color="#7f8c8d")
_r("ni0",  "沪镍", "base_metals", "SHFE", "CNY", "元/吨", 0, "nf_NI0", color="#1abc9c")
_r("sn0",  "沪锡", "base_metals", "SHFE", "CNY", "元/吨", 0, "nf_SN0", color="#8e44ad")
_r("bc0",  "国际铜", "base_metals", "INE",  "CNY", "元/吨", 0, "nf_BC0", color="#d35400")

# ── 黑色系 ────────────────────────────────────────────────────────
_r("rb0",  "螺纹钢",  "ferrous", "SHFE", "CNY", "元/吨", 0, "nf_RB0", color="#2c3e50")
_r("hc0",  "热卷",    "ferrous", "SHFE", "CNY", "元/吨", 0, "nf_HC0", color="#34495e")
_r("i0",   "铁矿石",  "ferrous", "DCE",  "CNY", "元/吨", 1, "nf_I0",  color="#c0392b")
_r("j0",   "焦炭",    "ferrous", "DCE",  "CNY", "元/吨", 1, "nf_J0",  color="#7f8c8d")
_r("jm0",  "焦煤",    "ferrous", "DCE",  "CNY", "元/吨", 1, "nf_JM0", color="#6c757d")
_r("sf0",  "硅铁",    "ferrous", "ZCE",  "CNY", "元/吨", 0, "nf_SF0", color="#16a085")
_r("sm0",  "锰硅",    "ferrous", "ZCE",  "CNY", "元/吨", 0, "nf_SM0", color="#27ae60")
_r("ss0",  "不锈钢",  "ferrous", "SHFE", "CNY", "元/吨", 0, "nf_SS0", color="#bdc3c7")

# ── 能源化工 ──────────────────────────────────────────────────────
_r("sc0",  "原油",     "energy", "INE",  "CNY", "元/桶", 1, "nf_SC0", color="#2c3e50")
_r("fu0",  "燃油",     "energy", "SHFE", "CNY", "元/吨", 0, "nf_FU0", color="#e74c3c")
_r("bu0",  "沥青",     "energy", "SHFE", "CNY", "元/吨", 0, "nf_BU0", color="#95a5a6")
_r("ta0",  "PTA",      "energy", "ZCE",  "CNY", "元/吨", 0, "nf_TA0", color="#e67e22")
_r("ma0",  "甲醇",     "energy", "ZCE",  "CNY", "元/吨", 0, "nf_MA0", color="#f39c12")
_r("eg0",  "乙二醇",   "energy", "DCE",  "CNY", "元/吨", 0, "nf_EG0", color="#1abc9c")
_r("pp0",  "聚丙烯",   "energy", "DCE",  "CNY", "元/吨", 0, "nf_PP0", color="#3498db")
_r("l0",   "塑料",     "energy", "DCE",  "CNY", "元/吨", 0, "nf_L0",  color="#2980b9")
_r("v0",   "PVC",      "energy", "DCE",  "CNY", "元/吨", 0, "nf_V0",  color="#8e44ad")
_r("eb0",  "苯乙烯",   "energy", "DCE",  "CNY", "元/吨", 0, "nf_EB0", color="#9b59b6")
_r("lu0",  "低硫燃油", "energy", "INE",  "CNY", "元/吨", 0, "nf_LU0", color="#d35400")
_r("pg0",  "液化气",   "energy", "DCE",  "CNY", "元/吨", 0, "nf_PG0", color="#c0392b")
_r("sa0",  "纯碱",     "energy", "ZCE",  "CNY", "元/吨", 0, "nf_SA0", color="#bdc3c7")
_r("ur0",  "尿素",     "energy", "ZCE",  "CNY", "元/吨", 0, "nf_UR0", color="#27ae60")

# ── 农产品 ────────────────────────────────────────────────────────
_r("m0",   "豆粕",   "agriculture", "DCE", "CNY", "元/吨",    0, "nf_M0",  color="#f1c40f")
_r("y0",   "豆油",   "agriculture", "DCE", "CNY", "元/吨",    0, "nf_Y0",  color="#f39c12")
_r("p0",   "棕榈油", "agriculture", "DCE", "CNY", "元/吨",    0, "nf_P0",  color="#d35400")
_r("rm0",  "菜粕",   "agriculture", "ZCE", "CNY", "元/吨",    0, "nf_RM0", color="#27ae60")
_r("oi0",  "菜油",   "agriculture", "ZCE", "CNY", "元/吨",    0, "nf_OI0", color="#2ecc71")
_r("sr0",  "白糖",   "agriculture", "ZCE", "CNY", "元/吨",    0, "nf_SR0", color="#ecf0f1")
_r("cf0",  "棉花",   "agriculture", "ZCE", "CNY", "元/吨",    0, "nf_CF0", color="#bdc3c7")
_r("c0",   "玉米",   "agriculture", "DCE", "CNY", "元/吨",    0, "nf_C0",  color="#f1c40f")
_r("cs0",  "淀粉",   "agriculture", "DCE", "CNY", "元/吨",    0, "nf_CS0", color="#e67e22")
_r("ap0",  "苹果",   "agriculture", "ZCE", "CNY", "元/吨",    0, "nf_AP0", color="#e74c3c")
_r("jd0",  "鸡蛋",   "agriculture", "DCE", "CNY", "元/500kg", 0, "nf_JD0", color="#f39c12")
_r("sp0",  "纸浆",   "agriculture", "SHFE","CNY", "元/吨",    0, "nf_SP0", color="#95a5a6")
_r("lh0",  "生猪",   "agriculture", "DCE", "CNY", "元/吨",    0, "nf_LH0", color="#e74c3c")

# ── 国际 ─────────────────────────────────────────────────────────
_r("cl",   "WTI原油",  "international", "NYMEX", "USD", "$/桶",    2, "hf_CL", True, "#2c3e50", "comex")
_r("ng",   "天然气",   "international", "NYMEX", "USD", "$/mmBtu", 3, "hf_NG", True, "#3498db", "comex")
_r("hg",   "COMEX铜",  "international", "COMEX", "USD", "¢/磅",    4, "hf_HG", True, "#e67e22", "comex")


# ── 通用 Sina 获取 ───────────────────────────────────────────────

_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_instrument(inst: Instrument) -> dict[str, Any] | None:
    """通用 Sina 行情获取，根据 is_intl 自动选择解析格式。"""
    try:
        url = f"https://hq.sinajs.cn/list={inst.sina_code}"
        req = Request(url, headers=_SINA_HEADERS)
        with urlopen(req, timeout=5) as resp:
            text = resp.read().decode("gbk")

        raw = text.split("=", 1)[1].strip(';\n\r "')
        if not raw:
            return None
        parts = raw.split(",")

        if inst.is_intl:
            return _parse_intl(inst, parts)
        else:
            return _parse_domestic(inst, parts)
    except Exception as exc:
        log.debug(f"[{inst.id}] Sina fetch failed: {exc}")
        return None


def _parse_domestic(inst: Instrument, parts: list[str]) -> dict[str, Any] | None:
    """解析国内期货 nf_ 格式。"""
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
    change = round(price - prev_close, inst.decimals + 1)
    change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

    d = inst.decimals
    return {
        "id": inst.id,
        "source": f"Sina-{inst.sina_code}",
        "symbol": inst.sina_code.replace("nf_", ""),
        "name": inst.name,
        "exchange": inst.exchange,
        "currency": inst.currency,
        "unit": inst.unit,
        "price": round(price, d),
        "prevClose": round(prev_close, d),
        "change": change,
        "changePercent": change_pct,
        "open": round(open_p, d) if open_p else None,
        "high": round(high_p, d) if high_p else None,
        "low": round(low_p, d) if low_p else None,
        "volume": volume,
        "timestamp": int(time.time() * 1000),
        "datetime_cst": f"{date_str} {time_fmt}",
        "closed": False,
    }


def _parse_intl(inst: Instrument, parts: list[str]) -> dict[str, Any] | None:
    """解析国际品种 hf_ 格式。"""
    if len(parts) < 13:
        return None
    price = float(parts[0])
    if price <= 0:
        return None
    prev_close = float(parts[1])
    open_p = float(parts[2]) if parts[2] else price
    high_p = float(parts[3]) if parts[3] else price
    low_p = float(parts[5]) if parts[5] else price
    time_str = parts[6]
    date_str = parts[12]
    change = round(price - prev_close, inst.decimals + 1)
    change_pct = round(change / prev_close * 100, 2) if prev_close > 0 else 0

    d = inst.decimals
    return {
        "id": inst.id,
        "source": f"Sina-{inst.sina_code}",
        "symbol": inst.sina_code.replace("hf_", ""),
        "name": inst.name,
        "exchange": inst.exchange,
        "currency": inst.currency,
        "unit": inst.unit,
        "price": round(price, d),
        "prevClose": round(prev_close, d),
        "change": change,
        "changePercent": change_pct,
        "open": round(open_p, d),
        "high": round(high_p, d),
        "low": round(low_p, d),
        "volume": 0,
        "timestamp": int(time.time() * 1000),
        "datetime_cst": f"{date_str} {time_str}",
        "closed": False,
    }


def get_enabled_instruments() -> list[Instrument]:
    """返回所有注册品种。"""
    return list(REGISTRY.values())


def get_instruments_by_category() -> dict[str, list[Instrument]]:
    """按分类分组返回品种。"""
    grouped: dict[str, list[Instrument]] = {}
    for inst in REGISTRY.values():
        grouped.setdefault(inst.category, []).append(inst)
    return grouped


def registry_to_json() -> list[dict[str, Any]]:
    """注册表序列化为 JSON（供前端 /api/instruments/registry）。"""
    result = []
    for inst in REGISTRY.values():
        result.append({
            "id": inst.id,
            "name": inst.name,
            "category": inst.category,
            "exchange": inst.exchange,
            "currency": inst.currency,
            "unit": inst.unit,
            "decimals": inst.decimals,
            "color": inst.color,
            "marketHours": inst.market_hours,
        })
    return result
