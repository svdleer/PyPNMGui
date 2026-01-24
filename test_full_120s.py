#!/usr/bin/env python3
import requests
import websocket
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:5050"
MAC = "e4:57:40:0b:db:b9"
count = 0

def on_msg(ws, msg):
    global count
    try:
        data = json.loads(msg)
        if data.get('type') in ['spectrum', 'spectrum_data']:
            count += 1
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Sample #{count}")
    except: pass

def on_close(ws, code, msg):
    print(f"\n{'='*50}\nTOTAL SAMPLES RECEIVED: {count}\n{'='*50}")

print("Starting UTSC...")
requests.post(f"{BASE_URL}/api/pypnm/upstream/utsc/start/{MAC}", json={
    "cmts_ip": "172.16.6.212", "rf_port_ifindex": 1078534144,
    "community": "Z1gg0Sp3c1@l", "tftp_ip": "172.16.6.101",
    "repeat_period_ms": 1000, "freerun_duration_ms": 60000
})
time.sleep(3)

print("Connecting WebSocket (120s duration)...")
ws = websocket.WebSocketApp(
    f"ws://localhost:5050/ws/utsc/{MAC}?refresh=500&duration=120&rf_port=1078534144&cmts_ip=172.16.6.212&community=Z1gg0Sp3c1%40l",
    on_message=on_msg, on_close=on_close)
ws.run_forever()

print(f"\nFinal count: {count} samples")
