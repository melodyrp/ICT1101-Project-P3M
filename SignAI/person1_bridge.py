"""Bridge used by the live 250-sign recogniser.

Copy this file into the upstream translator's ``src`` folder.  The patched
webcam demo calls ``observe_sentence_from_locals(locals())`` every frame and
``send_sentence_from_locals(locals())`` when Enter is pressed.

The final sentence is sent to the team's Backend/sign_receiver.py as one JSON
line.  Backend/main.py then handles TTS and Unit B; Person 1 should not send
speech/audio directly.
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "person1_config.json"

_last_sentence = ""
_last_change = time.monotonic()


def _config() -> dict[str, Any]:
    data: dict[str, Any] = {
        "backend_host": "127.0.0.1",
        "backend_port": 5560,
        "connect_timeout_seconds": 2.0,
        "prediction_log": "logs/person1_predictions.jsonl",
    }
    if CONFIG.exists():
        try:
            loaded = json.loads(CONFIG.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception as error:
            print(f"[Person1] config warning: {error}")
    return data


def _clean(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.strip().split())
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return " ".join(" ".join(value).strip().split())
    return ""


def extract_sentence(namespace: Mapping[str, Any]) -> str:
    names = (
        "sentence", "sentence_text", "sentence_words", "words", "word_buffer",
        "sentence_buffer", "accepted_words", "recognized_sentence",
        "recognised_sentence", "output_sentence",
    )
    for name in names:
        if name in namespace:
            text = _clean(namespace[name])
            if text:
                return text
    # Defensive fallback for small upstream naming changes.
    found: list[str] = []
    for name, value in namespace.items():
        lower = name.lower()
        if any(k in lower for k in ("sentence", "word_buffer", "accepted_words")):
            text = _clean(value)
            if text:
                found.append(text)
    return max(found, key=len) if found else ""


def extract_confidence(namespace: Mapping[str, Any]) -> Optional[float]:
    for name in ("confidence", "conf", "top_confidence", "top_prob", "probability", "best_prob"):
        value = namespace.get(name)
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
    return None


def _append_log(payload: dict[str, Any]) -> None:
    cfg = _config()
    path = ROOT / str(cfg.get("prediction_log", "logs/person1_predictions.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def send_sentence_text(sentence: str, confidence: Optional[float] = None) -> bool:
    sentence = " ".join(sentence.strip().split())
    if not sentence:
        print("[Person1] Nothing to send yet.")
        return False
    # Team Unit B currently supports printable ASCII and max 160 chars.
    try:
        encoded = sentence.encode("ascii")
    except UnicodeEncodeError:
        print("[Person1] Sentence contains unsupported non-ASCII characters.")
        return False
    if len(encoded) > 160:
        print("[Person1] Sentence is over 160 characters; shorten it before sending.")
        return False

    cfg = _config()
    message = {
        "type": "sign_sentence",
        "sentence": sentence,
        "confidence": confidence,
        "source": "person1_sign_ai",
    }
    raw = (json.dumps(message) + "\n").encode("utf-8")
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
        suffix = "" if confidence is None else f" ({confidence:.0%})"
        print(f"[Person1] Sent to team backend: {sentence}{suffix}" + (f" [{reply}]" if reply else ""))
        return True
    except OSError as error:
        print(f"[Person1] Backend is not reachable: {error}")
        print("[Person1] Start Backend/main.py first, then press Enter again.")
        return False


def send_sentence_from_locals(namespace: Mapping[str, Any]) -> bool:
    return send_sentence_text(extract_sentence(namespace), extract_confidence(namespace))


def observe_sentence_from_locals(namespace: Mapping[str, Any]) -> None:
    global _last_sentence, _last_change
    sentence = extract_sentence(namespace)
    if sentence != _last_sentence:
        confidence = extract_confidence(namespace)
        _last_sentence = sentence
        _last_change = time.monotonic()
        if sentence:
            _append_log({
                "time": time.time(),
                "sentence": sentence,
                "confidence": confidence,
            })
