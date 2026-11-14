"""Fake Unit B - pretends to be Melody's TinyScreen so the backend can be
tested without hardware. Speaks the same UNITB_WIFI_V1 protocol and plays
audio at real-time speed (16000 bytes/second), sending CREDIT 1024 as it goes.

    python fake_unitb.py            # listens on 127.0.0.1:5555
    python fake_unitb.py --play     # also plays the audio on laptop speakers

Every received sentence is saved to Backend/fake_output/unitb_last.wav.
"""
import argparse
import socket
import time
import wave
from pathlib import Path

PORT = 5555
RATE = 16000
INITIAL_CREDIT = 7168
PREFILL = 4096
OUT = Path(__file__).resolve().parent / 'fake_output'


def read_line(f):
    raw = f.readline(80)
    return raw.decode('ascii', 'replace').strip() if raw else None


def handle(conn, play):
    f = conn.makefile('rb')
    if read_line(f) != 'PING':
        conn.sendall(b'ERROR Expected PING\n'); return
    conn.sendall(b'UNITB_WIFI_V1\n')
    header = read_line(f)
    if header is None:
        return                       # a ping() check - just hang up
    try:
        word, rate, count, length = header.split()
        rate, count, length = int(rate), int(count), int(length)
        assert word == 'SAY' and rate == RATE and 0 < count <= 480000 and 0 < length <= 160
    except (ValueError, AssertionError):
        conn.sendall(b'ERROR Invalid sentence header\n'); return
    text = f.read(length).decode('ascii', 'replace')
    if len(text) != length:
        conn.sendall(b'ERROR Incomplete text\n'); return
    print(f'\n[fake Unit B] SCREEN: "{text}"  ({count / RATE:.1f}s audio)')
    conn.sendall(f'READY {INITIAL_CREDIT}\n'.encode())

    # Receive with flow control, "playing" at 16 kHz once PREFILL is buffered.
    audio = bytearray()
    conn.settimeout(0.02)
    started = None
    played = credited = underruns = 0
    starving = False
    deadline = time.monotonic() + count / RATE + 20
    while played < count:
        if time.monotonic() > deadline:
            conn.sendall(b'ERROR Playback timeout\n'); return
        if len(audio) < count:
            try:
                chunk = conn.recv(min(1024, count - len(audio)))
                if not chunk:
                    print('[fake Unit B] laptop disconnected'); return
                audio += chunk
            except socket.timeout:
                pass
        if started is None and len(audio) >= min(count, PREFILL):
            started = time.monotonic()
            print('[fake Unit B] SPEAKING')
        if started is not None:
            target = min(count, int((time.monotonic() - started) * RATE))
            if target > len(audio):           # buffer ran dry
                if not starving:
                    underruns += 1
                    starving = True
                started += (target - len(audio)) / RATE   # pause the clock
                target = len(audio)
            else:
                starving = False
            played = target
        while played - credited >= 1024:
            conn.sendall(b'CREDIT 1024\n')
            credited += 1024

    conn.sendall(f'DONE {played} {underruns}\n'.encode())
    print(f'[fake Unit B] FINISHED (underruns: {underruns})')

    OUT.mkdir(exist_ok=True)
    path = OUT / 'unitb_last.wav'
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(1); w.setframerate(RATE)
        w.writeframes(bytes(audio))
    if play:
        try:
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except ImportError:
            pass


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=PORT)
    p.add_argument('--play', action='store_true', help='play received audio on this laptop')
    a = p.parse_args()
    with socket.create_server((a.host, a.port)) as server:
        print(f'[fake Unit B] WIFI READY  {a.host}  port {a.port}')
        while True:
            conn, _ = server.accept()     # one laptop at a time, like the real board
            with conn:
                try:
                    handle(conn, a.play)
                except OSError as error:
                    print('[fake Unit B] connection error:', error)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n[fake Unit B] off')
