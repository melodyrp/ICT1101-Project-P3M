"""Laptop <-> Unit A link (Person 4).

Unit A keeps ONE TCP connection open to the laptop so button presses can
arrive at any time. See PROTOCOL.md for the message list (DRAFT - agree with
Jodie before writing the Arduino side).

    link = UnitALink("192.168.1.30", on_event=handle)   # handle("BTN START")
    link.start()
    link.send_caption("hello there")
"""
import socket
import threading
import time

PORT = 5556
HELLO_REPLY = 'UNITA_WIFI_V1'
MAX_CAPTION = 160
HEARTBEAT_S = 5


def _clean(text, limit):
    """Unit A's OLED font is basic ASCII; drop anything else and newlines."""
    text = ''.join(c for c in text if 32 <= ord(c) <= 126)
    return text[:limit]


class UnitALink:
    def __init__(self, address, on_event, port=PORT, report=print):
        self.address, self.port = address, port
        self.on_event = on_event
        self.report = report
        self._sock = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.connected = threading.Event()

    # ---------- public ----------
    def start(self):
        threading.Thread(target=self._run, name='unita-link', daemon=True).start()

    def stop(self):
        self._stop.set()
        self._close()

    def send_caption(self, text):
        return self._send('CAPTION ' + _clean(text, MAX_CAPTION))

    def send_status(self, word):
        """e.g. LISTENING, IDLE, SPEAKING, SIGNING - shown as a status line."""
        return self._send('STATUS ' + _clean(word, 16).upper())

    def clear(self):
        return self._send('CLEAR')

    # ---------- internals ----------
    def _send(self, line):
        with self._lock:
            if not self._sock:
                return False
            try:
                self._sock.sendall(line.encode('ascii') + b'\n')
                return True
            except OSError:
                self._close_locked()
                return False

    def _close(self):
        with self._lock:
            self._close_locked()

    def _close_locked(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self.connected.clear()

    def _run(self):
        """Connect, read events, reconnect forever until stop()."""
        while not self._stop.is_set():
            try:
                self._session()
            except (OSError, ConnectionError, ValueError) as error:
                if self.connected.is_set():
                    self.report(f'[Unit A] link lost: {error}')
            self._close()
            self._stop.wait(2)   # retry delay

    def _session(self):
        sock = socket.create_connection((self.address, self.port), timeout=5)
        sock.settimeout(HEARTBEAT_S * 3)   # no data for 15 s = dead link
        stream = sock.makefile('rb')
        sock.sendall(b'HELLO\n')
        if stream.readline(128).decode('ascii', 'replace').strip() != HELLO_REPLY:
            sock.close()
            raise ValueError('device is not running the Unit A sketch')
        with self._lock:
            self._sock = sock
        self.connected.set()
        self.report(f'[Unit A] connected at {self.address}:{self.port}')

        threading.Thread(target=self._heartbeat, args=(sock,), daemon=True).start()
        while not self._stop.is_set():
            raw = stream.readline(128)
            if not raw:
                raise ConnectionError('Unit A closed the connection')
            line = raw.decode('ascii', 'replace').strip()
            if not line or line == 'PONG':
                continue
            try:
                self.on_event(line)
            except Exception as error:      # never let a handler kill the link
                self.report(f'[Unit A] handler error for {line!r}: {error}')

    def _heartbeat(self, sock):
        while not self._stop.is_set() and self._sock is sock:
            time.sleep(HEARTBEAT_S)
            if self._sock is sock:
                self._send('PING')
