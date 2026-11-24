"""Backend sender for Person 1 fingerspelling mode.

This talks to Backend/sign_receiver.py (TCP 5560):
  send_letter("H")  -> one recognised letter (shows live on Unit A)
  send_key("space") -> space / undo / send / clear / get
  send_text("hi")   -> a whole sentence (same as the 250-word recogniser)
send_letter / send_key return the backend's current spelled text, or None if the
backend is not reachable.
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


_warned_offline = False


def _exchange(payload: dict, timeout: float = 0.5) -> Optional[str]:
    """Send one JSON line, return the reply line ('' if none) or None if offline."""
    global _warned_offline
    cfg = load_config()
    raw = (json.dumps(payload) + "\n").encode("utf-8")
    try:
        with socket.create_connection(
            (str(cfg["backend_host"]), int(cfg["backend_port"])), timeout=timeout,
        ) as sock:
            sock.sendall(raw)
            sock.settimeout(timeout)
            reply = b""
            try:
                while not reply.endswith(b"\n") and len(reply) < 512:
                    chunk = sock.recv(256)
                    if not chunk:
                        break
                    reply += chunk
            except OSError:
                pass
        _warned_offline = False
        return reply.decode("ascii", "replace").rstrip("\r\n")
    except OSError as exc:
        if not _warned_offline:
            print(f"[Fingerspell] Backend not reachable: {exc}")
            print("[Fingerspell] Start Backend/main.py - letters will only show here until then.")
            _warned_offline = True
        return None


def _text_from_reply(reply: Optional[str]) -> Optional[str]:
    if reply is None:
        return None
    if reply.startswith("OK "):
        return reply[3:]
    if reply == "OK":
        return ""
    print(f"[Fingerspell] Backend said: {reply}")
    return None


def send_letter(letter: str, confidence: Optional[float] = None) -> Optional[str]:
    """One recognised letter. Returns the backend's spelled text, or None."""
    return _text_from_reply(_exchange(
        {"type": "sign_letter", "letter": letter, "confidence": confidence}))


def send_key(key: str) -> Optional[str]:
    """'space', 'undo', 'send', 'clear' or 'get'. Returns the spelled text, or None."""
    return _text_from_reply(_exchange({"type": "sign_key", "key": key}))
