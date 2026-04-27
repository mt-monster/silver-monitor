#!/usr/bin/env python3
import json
import threading
import time

API_KEY = "51cd45a09dc7433c876f22f3281617c4-infoway"
URL = f"wss://data.infoway.io/ws?business=common&apikey={API_KEY}"

messages = []
lock = threading.Lock()

def ws_thread():
    import websocket

    def on_message(ws, message):
        with lock:
            messages.append(message)
        print(f"[MSG] {message[:120]}")

    def on_open(ws):
        print("[OPEN] Connected")
        ws.send(json.dumps({"code": 10000, "trace": "t", "data": {"codes": "XAGUSD"}}))
        print("[SENT] Subscribed")
        
        def hb():
            while True:
                time.sleep(30)
                try:
                    ws.send(json.dumps({"code": 10010, "trace": "t"}))
                except:
                    return
        threading.Thread(target=hb, daemon=True).start()

    def on_close(ws, code, msg):
        print(f"[CLOSE] {code} {msg}")

    def on_error(ws, err):
        print(f"[ERROR] {err}")

    ws = websocket.WebSocketApp(URL, on_open=on_open, on_message=on_message,
                                on_close=on_close, on_error=on_error)
    ws.run_forever()

t = threading.Thread(target=ws_thread, daemon=True)
t.start()

for i in range(15):
    with lock:
        count = len(messages)
    print(f"[MAIN] {count} messages")
    time.sleep(1)
