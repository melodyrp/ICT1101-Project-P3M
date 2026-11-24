import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socket
import time
from Backend.sign_receiver import SignReceiver

received = []
r = SignReceiver(received.append, port=5561, report=lambda *_: None)
r.start()
time.sleep(0.15)
with socket.create_connection(("127.0.0.1", 5561), timeout=2) as s:
    s.sendall((json.dumps({"type":"sign_sentence","sentence":"need help","confidence":0.8})+"\n").encode())
    assert s.recv(64).startswith(b"OK")
time.sleep(0.1)
r.stop()
assert received == ["need help"], received
print("PASS: SignReceiver -> callback")
