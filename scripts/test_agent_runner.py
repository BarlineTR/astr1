import subprocess
import time
import urllib.request
import json

# Start astro_web_agent.py
proc = subprocess.Popen(
    ["python3", "/home/okistech/Desktop/astr1/scripts/astro_web_agent.py", "--dashboard-port", "8080"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)

time.sleep(2.5)

# Test 1: GET /api/telemetry
print("=== TEST 1: GET /api/telemetry ===")
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/api/telemetry", timeout=3) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"HTTP Status: {resp.status}")
        print("Telemetry JSON keys:", list(data.keys()))
        print("Robot State:", data.get("robot_state"))
        print("Visual Tracking:", data.get("visual_tracking"))
        print("Identity:", data.get("identity"))
        print("Audio & Speech:", data.get("audio_speech"))
        print("AI Conversation:", data.get("ai_conversation"))
        print("Safety:", data.get("safety"))
except Exception as e:
    print(f"Error: {e}")

# Test 2: GET /camera/snapshot.jpg
print("\n=== TEST 2: GET /camera/snapshot.jpg ===")
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/camera/snapshot.jpg", timeout=3) as resp:
        content = resp.read()
        print(f"HTTP Status: {resp.status} | Content-Type: {resp.headers.get('Content-Type')} | Size: {len(content)} bytes")
except Exception as e:
    print(f"Error: {e}")

# Test 3: POST /api/head
print("\n=== TEST 3: POST /api/head (Kafa Acisi Komutu) ===")
try:
    req = urllib.request.Request(
        "http://127.0.0.1:8080/api/head",
        data=json.dumps({"yaw_deg": 25.0}).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        res = json.loads(resp.read().decode())
        print("Response:", res)
except Exception as e:
    print(f"Error: {e}")

# Test 4: POST /api/estop
print("\n=== TEST 4: POST /api/estop (Acil Durdurma) ===")
try:
    req = urllib.request.Request(
        "http://127.0.0.1:8080/api/estop",
        data=json.dumps({"engaged": True}).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        res = json.loads(resp.read().decode())
        print("Response:", res)
except Exception as e:
    print(f"Error: {e}")

# Test 5: GET / (Dashboard HTML)
print("\n=== TEST 5: GET / (Dashboard HTML) ===")
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=3) as resp:
        html = resp.read().decode("utf-8")
        print(f"HTTP Status: {resp.status} | Title present: {'Bilinç & Telemetri Kontrol Paneli' in html} | Size: {len(html)} bytes")
except Exception as e:
    print(f"Error: {e}")

proc.terminate()
print("\n✅ Tum Dashboard & Telemetri Testleri Tamamlandi!")
