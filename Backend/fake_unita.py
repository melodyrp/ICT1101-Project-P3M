"""Fake Unit A - pretends to be Jodie's TinyScreen (spelling screen + buttons).

    python fake_unita.py          # listens on 127.0.0.1:5556

Prints whatever the laptop sends to the "screen". Type a key + Enter to
simulate the hardware:
    c = START/STOP captions    s = SPACE    u = UNDO (one letter)
    e = SEND (speak it)        q = quit
"""
import argparse
import socket
import threading

PORT = 5556
KEYS = {'s': 'BTN SPACE', 'u': 'BTN UNDO', 'e': 'BTN SEND'}
captions_on = [False]

current = {'conn': None}
lock = threading.Lock()


def serve(host, port):
    with socket.create_server((host, port)) as server:
        print(f'[fake Unit A] WIFI READY  {host}  port {port}')
        while True:
            conn, addr = server.accept()
            with conn:
                f = conn.makefile('rb')
                if f.readline(128).strip() != b'HELLO':
                    continue
                conn.sendall(b'UNITA_WIFI_V2\n')
                with lock:
                    current['conn'] = conn
                print(f'[fake Unit A] laptop connected from {addr[0]}')
                try:
                    for raw in f:
                        line = raw.decode('ascii', 'replace').rstrip('\r\n')
                        if line == 'PING':
                            conn.sendall(b'PONG\n')
                        elif line == 'TEXT' or line.startswith('TEXT '):
                            print(f'[fake Unit A] SCREEN text: "{line[5:]}_"')
                        elif line == 'CAPTION' or line.startswith('CAPTION '):
                            print(f'[fake Unit A] SCREEN caption: "{line[8:]}"')
                        elif line.startswith('SENT '):
                            print(f'[fake Unit A] SCREEN spoken: "{line[5:]}"')
                        elif line.startswith('STATUS '):
                            print(f'[fake Unit A] SCREEN status: {line[7:]}')
                        elif line == 'CLEAR':
                            print('[fake Unit A] SCREEN cleared')
                        else:
                            print(f'[fake Unit A] unknown message: {line!r}')
                except OSError:
                    pass
                with lock:
                    current['conn'] = None
                print('[fake Unit A] laptop disconnected')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=PORT)
    a = p.parse_args()
    threading.Thread(target=serve, args=(a.host, a.port), daemon=True).start()
    print(__doc__.split('\n', 4)[-1])
    while True:
        key = input().strip().lower()
        if key == 'q':
            return
        if key == 'c':
            captions_on[0] = not captions_on[0]
            msg = 'BTN START' if captions_on[0] else 'BTN STOP'
        elif key in KEYS:
            msg = KEYS[key]
        else:
            continue
        with lock:
            conn = current['conn']
        if conn is None:
            print('[fake Unit A] (laptop not connected yet)')
            continue
        conn.sendall(msg.encode() + b'\n')
        print(f'[fake Unit A] sent {msg}')


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\n[fake Unit A] off')
