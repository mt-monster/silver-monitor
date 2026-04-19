"""测试 iFinD 是否提供比特币行情数据.

尝试多个可能的合约代码。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.ifind import client

def main():
    ok = client.ensure_login()
    if not ok:
        print("登录失败")
        return
    print(f"登录成功 (mode={client._mode})\n")

    codes = [
        "BTCUSD.FX",
        "BTCUSDT.FX",
        "BTC.CC",
        "BTCUSD.CC",
        "BTCUSDT.CC",
        "BITCOIN.FX",
        "XBTUSD.FX",
        "BTC-USD.FX",
        "BTCUSD.BK",
        "BTCUSD.HG",
        "CME:BTC",
    ]

    indicators = "latest;open;high;low;preClose;changeRatio;change;datetime"

    found = 0
    for code in codes:
        try:
            row = client.realtime_quote(code, indicators)
            if row:
                found += 1
                latest = row.get("latest")
                chg = row.get("change")
                chg_r = row.get("changeRatio")
                dt = row.get("datetime")
                print(f"  OK  {code:<20s}  latest={latest}  chg={chg}  chgR={chg_r}  dt={dt}")
            else:
                print(f"  --  {code:<20s}  无数据")
        except Exception as e:
            print(f"  ERR {code:<20s}  {e}")

    print(f"\n共测试 {len(codes)} 个代码，{found} 个有数据")
    client.logout()
    print("已退出")

if __name__ == "__main__":
    main()
