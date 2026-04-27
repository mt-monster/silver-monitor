#!/usr/bin/env python3
"""白银品种（沪银 AG0 / COMEX银 XAG）数据源连通性验证脚本。

用法:  python tests/verify_silver_sources.py
功能:  不依赖 server.py，直接测试 Sina / iFinD / Infoway 对沪银和 COMEX 银的数据获取能力。
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.config import RUNTIME_CONFIG, log

SEP = "-" * 60


def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")


def _test(label, fetch_fn, instrument, has_vol=True):
    """执行单次数据源测试，返回结果字典。"""
    result = {
        "instrument": instrument,
        "source": label,
        "ok": False,
        "price": None,
        "volume": None,
        "latency_ms": 0,
        "detail": "",
    }
    try:
        t0 = time.time()
        data = fetch_fn()
        elapsed = round((time.time() - t0) * 1000)
        result["latency_ms"] = elapsed
        if data and data.get("price"):
            result["ok"] = True
            result["price"] = data["price"]
            result["volume"] = data.get("volume")
            vol_str = f" vol={result['volume']}" if has_vol and result["volume"] is not None else ""
            result["detail"] = f"price={data['price']}{vol_str}"
        else:
            result["detail"] = "返回数据为空"
    except Exception as exc:
        result["detail"] = str(exc)
    return result


def main():
    print("=== 白银品种数据源连通性验证 ===")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    results = []

    # --- Sina 沪银 ---
    section("Sina — 沪银主力 (nf_AG0)")
    from backend.sources import fetch_huyin_sina
    r = _test("Sina", fetch_huyin_sina, "ag0")
    results.append(r)
    print(json.dumps(r, ensure_ascii=False, indent=2))

    # --- Sina COMEX银 ---
    section("Sina — COMEX银 (hf_XAG)")
    from backend.sources import fetch_comex_sina
    r = _test("Sina", fetch_comex_sina, "xag", has_vol=False)
    results.append(r)
    print(json.dumps(r, ensure_ascii=False, indent=2))

    # --- iFinD 沪银 ---
    section("iFinD — 沪银主力 (AGZL.SHF)")
    cfg = RUNTIME_CONFIG.get("ifind") or {}
    if not cfg.get("enabled"):
        print("[SKIP] iFinD enabled=false")
        r = {"instrument": "ag0", "source": "iFinD", "ok": False, "detail": "iFinD disabled in config"}
    else:
        try:
            import iFinDAPI
        except ImportError:
            print("[SKIP] iFinDAPI not installed")
            r = {"instrument": "ag0", "source": "iFinD", "ok": False, "detail": "iFinDAPI not installed"}
        else:
            from backend.ifind import fetch_huyin_ifind
            r = _test("iFinD", fetch_huyin_ifind, "ag0")
    results.append(r)
    print(json.dumps(r, ensure_ascii=False, indent=2))

    # --- iFinD COMEX银 ---
    section("iFinD — COMEX银 (XAGUSD.FX)")
    if not cfg.get("enabled"):
        print("[SKIP] iFinD enabled=false")
        r = {"instrument": "xag", "source": "iFinD", "ok": False, "detail": "iFinD disabled in config"}
    else:
        try:
            import iFinDAPI
        except ImportError:
            print("[SKIP] iFinDAPI not installed")
            r = {"instrument": "xag", "source": "iFinD", "ok": False, "detail": "iFinDAPI not installed"}
        else:
            from backend.ifind import fetch_comex_silver_ifind
            r = _test("iFinD", fetch_comex_silver_ifind, "xag")
    results.append(r)
    print(json.dumps(r, ensure_ascii=False, indent=2))

    # --- Infoway COMEX银 ---
    section("Infoway — COMEX银 (XAGUSD)")
    iw_cfg = RUNTIME_CONFIG.get("infoway_ws") or {}
    if not iw_cfg.get("enabled"):
        print("[SKIP] Infoway WS enabled=false")
        r = {"instrument": "xag", "source": "Infoway", "ok": False, "detail": "Infoway disabled in config"}
    else:
        from backend.infoway import fetch_comex_silver_infoway
        r = _test("Infoway", fetch_comex_silver_infoway, "xag")
        if not r["ok"]:
            r["detail"] += " (需先启动 server.py 建立 WS 连接)"
    results.append(r)
    print(json.dumps(r, ensure_ascii=False, indent=2))

    # --- Summary ---
    section("Summary")
    ok_count = sum(1 for r in results if r.get("ok"))
    total = len(results)
    for r in results:
        status = "OK" if r.get("ok") else "FAIL"
        inst = r.get("instrument", "?")
        src = r.get("source", "?")
        detail = r.get("detail", "")
        print(f"  [{status}] {inst:<10} {src:<12} {detail}")
    print(f"\n  总计: {ok_count}/{total} 通过")


if __name__ == "__main__":
    main()
