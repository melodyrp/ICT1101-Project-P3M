"""Backend sender for Person 1 fingerspelling mode.

This sends final text to Backend/sign_receiver.py using the same JSON protocol
as the 250-word recogniser.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "fingerspelling_config.json"


def load_config() -> dict:
    defaults = {
        "backend_host": "127.0.0.1",
        "backend_port": 5560,
        "connect_timeout_seconds": 2.0,
    }
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except Exception as exc:
            print(f"[Fingerspell] Config warning: {exc}")
    return defaults


def send_text(text: str, confidence: Optional[float] = None) -> bool:
    text = " ".join(text.strip().split())
    if not text:
        print("[Fingerspell] Nothing to send.")
        return False

    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError:
        print("[Fingerspell] Text contains unsupported non-ASCII characters.")
        return False

    if len(encoded) > 160:
        print("[Fingerspell] Text is over 160 characters. Shorten it first.")
        return False

    cfg = load_config()
    payload = {
        "type": "sign_sentence",
        "sentence": text,
        "confidence": confidence,
        "source": "person1_fingerspelling",
    }
    raw = (json.dumps(payload) + "\n").encode("utf-8")

    try:
        with socket.create_connection(
            (str(cfg["backend_host"]), int(cfg["backend_port"])),
            timeout=float(cfg.get("connect_timeout_seconds", 2.0)),
        ) as sock:
            sock.sendall(raw)
            sock.settimeout(2.0)
            try:
                reply = sock.recv(128).decode("ascii", "replace").strip()
            except OSError:
                reply = ""
        extra = f" ({confidence:.0%})" if confidence is not None else ""
        print(f"[Fingerspell] Sent: {text}{extra}" + (f" [{reply}]" if reply else ""))
        return True
    except OSError as exc:
        print(f"[Fingerspell] Backend not reachable: {exc}")
        print("[Fingerspell] Start Backend/main.py and try Enter again.")
        return False
