"""iFinD 数据源连通性测试脚本.

逐步测试:
  1. iFinDPy SDK 是否可用
  2. requests 库是否可用
  3. SDK 登录 / HTTP Token 获取
  4. COMEX 白银 (XAGUSD.FX) 实时行情
  5. COMEX 黄金 (XAUUSD.FX) 实时行情
"""

import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.config import RUNTIME_CONFIG

SEP = "-" * 50

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")


def main():
    cfg = RUNTIME_CONFIG.get("ifind") or {}
    print("=== iFinD 连通性测试 ===\n")
    print(f"  enabled       : {cfg.get('enabled')}")
    print(f"  account       : {cfg.get('account')}")
    print(f"  password      : {'***' if cfg.get('password') else '(空)'}")
    print(f"  refresh_token : {'***' + cfg['refresh_token'][-6:] if cfg.get('refresh_token') else '(空)'}")
    print(f"  silver_code   : {cfg.get('comex_silver_code')}")
    print(f"  gold_code     : {cfg.get('comex_gold_code')}")

    # --- Step 1: SDK availability ---
    section("1. 检查 iFinDPy SDK")
    try:
        from iFinDPy import THS_iFinDLogin, THS_RQ
        print("  ✓ iFinDPy SDK 已安装")
        sdk_ok = True
    except ImportError:
        print("  ✗ iFinDPy SDK 未安装 (pip install iFinDAPI)")
        sdk_ok = False

    # --- Step 2: requests availability ---
    section("2. 检查 requests 库")
    try:
        import requests
        print(f"  ✓ requests {requests.__version__}")
        req_ok = True
    except ImportError:
        print("  ✗ requests 未安装")
        req_ok = False

    # --- Step 3: Login ---
    section("3. 登录测试")
    from backend.ifind import client
    ok = client.ensure_login()
    if ok:
        print(f"  ✓ 登录成功  (mode={client._mode})")
    else:
        print(f"  ✗ 登录失败")
        if not sdk_ok and not cfg.get("refresh_token"):
            print("    → SDK 未装且 refresh_token 为空，无可用登录方式")
        elif sdk_ok:
            print("    → SDK 已装但登录返回错误，请检查 account/password")
        else:
            print("    → refresh_token 无效或网络不通")
        print("\n测试终止。")
        return

    # --- Step 4: COMEX Silver ---
    section("4. COMEX 白银行情 (XAGUSD.FX)")
    code_ag = cfg.get("comex_silver_code", "XAGUSD.FX")
    t0 = time.time()
    row_ag = client.realtime_quote(code_ag)
    elapsed_ag = (time.time() - t0) * 1000
    if row_ag:
        print(f"  ✓ 响应耗时 {elapsed_ag:.0f}ms")
        print(f"    latest    : {row_ag.get('latest')}")
        print(f"    open      : {row_ag.get('open')}")
        print(f"    high      : {row_ag.get('high')}")
        print(f"    low       : {row_ag.get('low')}")
        print(f"    preClose  : {row_ag.get('preClose')}")
        print(f"    change    : {row_ag.get('change')}")
        print(f"    changeR   : {row_ag.get('changeRatio')}")
        print(f"    datetime  : {row_ag.get('datetime')}")
        print(f"    vol       : {row_ag.get('vol')}")
    else:
        print(f"  ✗ 无数据返回 ({elapsed_ag:.0f}ms)")

    # --- Step 5: COMEX Gold ---
    section("5. COMEX 黄金行情 (XAUUSD.FX)")
    code_au = cfg.get("comex_gold_code", "XAUUSD.FX")
    t0 = time.time()
    row_au = client.realtime_quote(code_au)
    elapsed_au = (time.time() - t0) * 1000
    if row_au:
        print(f"  ✓ 响应耗时 {elapsed_au:.0f}ms")
        print(f"    latest    : {row_au.get('latest')}")
        print(f"    open      : {row_au.get('open')}")
        print(f"    high      : {row_au.get('high')}")
        print(f"    low       : {row_au.get('low')}")
        print(f"    preClose  : {row_au.get('preClose')}")
        print(f"    change    : {row_au.get('change')}")
        print(f"    changeR   : {row_au.get('changeRatio')}")
        print(f"    datetime  : {row_au.get('datetime')}")
        print(f"    vol       : {row_au.get('vol')}")
    else:
        print(f"  ✗ 无数据返回 ({elapsed_au:.0f}ms)")

    # --- Summary ---
    section("总结")
    login_str = f"✓ {client._mode}" if ok else "✗"
    ag_str = "✓" if row_ag else "✗"
    au_str = "✓" if row_au else "✗"
    print(f"  登录: {login_str}  |  XAG: {ag_str}  |  XAU: {au_str}")

    # Cleanup
    client.logout()
    print("\n已退出 iFinD 会话。")


if __name__ == "__main__":
    main()
