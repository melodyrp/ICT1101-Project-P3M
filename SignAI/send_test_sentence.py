"""Send a fake Person 1 sentence to Backend/main.py without opening the webcam."""
import argparse
import json
import socket

p = argparse.ArgumentParser()
p.add_argument("text", nargs="?", default="I need help")
p.add_argument("--host", default="127.0.0.1")
p.add_argument("--port", type=int, default=5560)
a = p.parse_args()

payload = {"type": "sign_sentence", "sentence": a.text, "confidence": 0.99, "source": "person1_test"}
with socket.create_connection((a.host, a.port), timeout=3) as s:
    s.sendall((json.dumps(payload) + "\n").encode())
    s.settimeout(2)
    try:
        print("Backend reply:", s.recv(128).decode().strip())
    except OSError:
        print("Sent (no reply received)")
