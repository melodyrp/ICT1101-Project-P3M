"""Local bridge from Person 1 sign-language recogniser to the team backend.

The sign recogniser runs in its own process because MediaPipe/OpenCV/PyTorch are
heavy and have their own webcam/UI loop.  When the signer finalises a sentence,
the recogniser sends one JSON line to this server, for example::

    {"type":"sign_sentence","sentence":"want water","confidence":0.81}

Fingerspelling mode sends one message per letter / key instead, so the letters
appear live on Unit A and Unit A's UNDO / SPACE / SEND edit the same text::

    {"type":"sign_letter","letter":"H","confidence":0.93}
    {"type":"sign_key","key":"space"}      # space | undo | send | clear | get

For sign_letter / sign_key the reply is ``OK <current spelled text>`` so the
recogniser window can show exactly what Unit A shows.

The receiver validates the message and calls the backend callback.  It intentionally does *not* perform TTS or talk to Unit B; those
steps remain the responsibility of Backend/main.py.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Callable, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5560
MAX_LINE = 8192


class SignReceiver:
    def __init__(
        self,
        on_sentence: Callable[[str], None],
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        report: Callable[[str], None] = print,
        on_letter: Optional[Callable[[str], None]] = None,
        on_key: Optional[Callable[[str], None]] = None,
        get_text: Optional[Callable[[], str]] = None,
    ):
        self.on_sentence = on_sentence
        self.on_letter = on_letter
        self.on_key = on_key
        self.get_text = get_text
        self.host = host
        self.port = int(port)
        self.report = report
        self._stop = threading.Event()
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sign-receiver", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        server = self._server
        self._server = None
        if server:
            try:
                server.close()
            except OSError:
                pass

    def _run(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(5)
            server.settimeout(1.0)
            self._server = server
            self.report(f"[sign] listening for Person 1 on {self.host}:{self.port}")

            while not self._stop.is_set():
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise

                threading.Thread(
                    target=self._handle,
                    args=(conn, addr),
                    daemon=True,
                ).start()

    def _handle(self, conn: socket.socket, addr) -> None:
        with conn:
            conn.settimeout(4.0)
            stream = conn.makefile("rb")
            try:
                raw = stream.readline(MAX_LINE + 1)
                if not raw:
                    return
                if len(raw) > MAX_LINE:
                    raise ValueError("message too large")
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("message must be a JSON object")
                kind = payload.get("type")
                if kind == "sign_letter":
                    self._handle_letter(conn, payload)
                    return
                if kind == "sign_key":
                    self._handle_key(conn, payload)
                    return
                if kind != "sign_sentence":
                    raise ValueError("unsupported message type")
                text = payload.get("sentence")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("missing sentence")

                confidence = payload.get("confidence")
                suffix = ""
                if isinstance(confidence, (int, float)):
                    suffix = f" confidence={float(confidence):.1%}"
                self.report(f"[sign] received from {addr[0]}: {text!r}{suffix}")
                self.on_sentence(text)
                try:
                    conn.sendall(b"OK\n")
                except OSError:
                    pass
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                self.report(f"[sign] ignored invalid message from {addr[0]}: {error}")
                try:
                    conn.sendall(f"ERROR {error}\n".encode("ascii", "replace"))
                except OSError:
                    pass
            except (OSError, TimeoutError) as error:
                self.report(f"[sign] connection error from {addr[0]}: {error}")

    # ---------- fingerspelling (one letter / key at a time) ----------
    def _reply_text(self, conn: socket.socket) -> None:
        text = self.get_text() if self.get_text else ""
        try:
            conn.sendall(("OK " + text + "\n").encode("ascii", "replace"))
        except OSError:
            pass

    def _handle_letter(self, conn: socket.socket, payload: dict) -> None:
        letter = payload.get("letter")
        if not isinstance(letter, str) or len(letter) != 1 or not (32 <= ord(letter) <= 126):
            raise ValueError("letter must be one printable ASCII character")
        if not self.on_letter:
            raise ValueError("letters are not supported by this backend")
        self.on_letter(letter)
        self._reply_text(conn)

    def _handle_key(self, conn: socket.socket, payload: dict) -> None:
        key = payload.get("key")
        if key not in ("space", "undo", "backspace", "send", "clear", "get"):
            raise ValueError("key must be space, undo, send, clear or get")
        if not self.on_key:
            raise ValueError("keys are not supported by this backend")
        self.on_key(key)
        self._reply_text(conn)
