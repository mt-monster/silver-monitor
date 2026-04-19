"""Infoway WebSocket 数据源验证脚本 — 以 BTCUSDT 为例。

用法:  python tests/verify_infoway_btc.py
功能:  连接 Infoway WS → 订阅 BTCUSDT trade → 打印前 N 条推送 → 退出

验证结论 (2026-04-20):
  - business=crypto 适用于加密货币 (BTCUSDT)
  - business=common 适用于商品 (XAGUSD, XAUUSD)
  - 订阅 ACK: code=10001, 无 data.s 字段
  - Trade 推送: code=10002, data 含 p/s/t/td/v/vw 字段
  - 符号用 BTCUSDT (非 BTCUSD)
"""

import asyncio
import json
import sys
import time
import uuid

try:
    import websockets
except ImportError:
    sys.exit("ERROR: websockets not installed.  Run: pip install websockets")

API_KEY = "3f909f6f2c5d434ebfee71a05b74de51-infoway"
BUSINESS = "crypto"           # crypto=加密货币, common=商品/外汇
SYMBOL = "BTCUSDT"
MAX_TRADES = 10               # 收到 N 条 trade 后自动退出
TIMEOUT = 30                  # 秒，超时无数据则退出


def _trace():
    return uuid.uuid4().hex[:12]


async def main():
    url = f"wss://data.infoway.io/ws?business={BUSINESS}&apikey={API_KEY}"
    print(f"[*] Connecting: {url}")
    print(f"[*] Subscribing symbol: {SYMBOL}")
    print(f"[*] Will exit after {MAX_TRADES} trades or {TIMEOUT}s timeout\n")

    trade_count = 0
    start_ts = time.time()

    async with websockets.connect(url, close_timeout=5) as ws:
        # 1) Read greeting / initial message
        try:
            init_msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"[INIT] {str(init_msg)[:300]}")
        except asyncio.TimeoutError:
            print("[INIT] (no greeting received)")

        # 2) Subscribe trade (code=10000)
        sub = {"code": 10000, "trace": _trace(), "data": {"codes": SYMBOL}}
        await ws.send(json.dumps(sub))
        print(f"[SUB]  Sent: {json.dumps(sub)}\n")

        # 3) Read response + trade pushes
        while trade_count < MAX_TRADES:
            elapsed = time.time() - start_ts
            if elapsed > TIMEOUT:
                print(f"\n[!] Timeout ({TIMEOUT}s) reached, exiting.")
                break

            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT - elapsed + 1)
            except asyncio.TimeoutError:
                print(f"\n[!] No message for {TIMEOUT}s, exiting.")
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[RAW] (non-json) {str(raw)[:200]}")
                continue

            code = msg.get("code")

            if code == 10002:  # TRADE PUSH
                trade_count += 1
                data = msg.get("data")
                if not isinstance(data, dict):
                    continue
                sym = data.get("s", "?")
                price = data.get("p", "?")
                ts = data.get("t", "")
                td = data.get("td", "")       # 1=buy, 2=sell
                vol = data.get("v", "")
                vw = data.get("vw", "")
                t_str = ""
                try:
                    t_str = time.strftime("%H:%M:%S", time.localtime(float(ts) / 1000))
                except Exception:
                    pass
                direction = {1: "BUY", 2: "SELL"}.get(td, str(td))
                print(
                    f"  [{trade_count:>3}] {sym:<10} "
                    f"price={price:<12} dir={direction:<5} vol={vol:<12} "
                    f"vw={vw:<16} time={t_str}"
                )
                # Print raw of first push for field inspection
                if trade_count == 1:
                    print(f"\n  [RAW first push] {json.dumps(data, ensure_ascii=False)}\n")

            elif code == 10001:  # SUBSCRIBE ACK
                print(f"[ACK]  Subscribe response: {json.dumps(msg, ensure_ascii=False)[:300]}")
            elif code == 10010:  # HEARTBEAT
                print(f"[HB]   Heartbeat response")
            else:
                print(f"[MSG]  code={code}  {json.dumps(msg, ensure_ascii=False)[:300]}")

    print(f"\n[*] Done. Received {trade_count} trade pushes in {time.time() - start_ts:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
