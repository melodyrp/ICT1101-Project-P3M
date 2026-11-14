"""Laptop -> Unit B client (Person 4).

Speaks the UNITB_WIFI_V1 protocol used by Melody's UnitB_WiFiSpeech sketch.
Same logic as UnitB/UnitB_WiFiSpeech/wifi_sender.py, but without the typing
loop or TTS step, so the main program can call send() directly.

    from unitb_client import send
    send("192.168.1.25", "Hello", pcm_bytes)   # blocks until Unit B says DONE
"""
import ipaddress
import socket
import time

PORT = 5555
SAMPLE_RATE = 16000
MAX_TEXT = 160            # characters, basic ASCII only
MAX_PCM = 480000          # bytes = 30 s of 16 kHz 8-bit mono
INITIAL_CREDIT = 7168
CHUNK = 1024


class UnitBError(RuntimeError):
    pass


def check_text(text):
    """Return the ASCII bytes Unit B accepts, or raise ValueError."""
    try:
        encoded = text.encode('ascii')
    except UnicodeEncodeError:
        raise ValueError('Unit B only accepts basic English characters.') from None
    if not encoded or len(encoded) > MAX_TEXT or any(v < 32 or v > 126 for v in encoded):
        raise ValueError(f'Text must be 1-{MAX_TEXT} basic characters on one line.')
    return encoded


def _read_line(stream):
    raw = stream.readline(256)
    if not raw:
        raise ConnectionError('Unit B closed the connection.')
    if not raw.endswith(b'\n'):
        raise UnitBError('Incomplete reply from Unit B.')
    line = raw.decode('ascii', errors='replace').strip()
    if line.startswith('ERROR'):
        raise UnitBError(line)
    return line


def ping(address, port=PORT, timeout=3):
    """True if a Unit B (real or fake) answers on this address."""
    try:
        with socket.create_connection((address, port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            with conn.makefile('rb') as stream:
                conn.sendall(b'PING\n')
                return _read_line(stream) == 'UNITB_WIFI_V1'
    except (OSError, UnitBError):
        return False


def send(address, text, pcm, port=PORT, report=print):
    """Send one sentence + its audio and block until playback finishes.

    pcm: raw 16 kHz, mono, unsigned 8-bit samples (no WAV header).
    Returns the number of buffer underruns Unit B reported.
    """
    if address != 'localhost':
        address = str(ipaddress.IPv4Address(address))
    encoded = check_text(text)
    if not pcm or len(pcm) > MAX_PCM:
        raise ValueError('Audio must be 1 byte to 30 seconds long.')

    with socket.create_connection((address, port), timeout=10) as conn:
        conn.settimeout(15)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with conn.makefile('rb') as stream:
            conn.sendall(b'PING\n')
            if _read_line(stream) != 'UNITB_WIFI_V1':
                raise UnitBError('Device is not running the UnitB_WiFiSpeech sketch.')
            conn.sendall(f'SAY {SAMPLE_RATE} {len(pcm)} {len(encoded)}\n'.encode('ascii') + encoded)
            if _read_line(stream) != f'READY {INITIAL_CREDIT}':
                raise UnitBError('Unit B did not accept the audio transfer.')

            budget, offset, played, last_bucket = INITIAL_CREDIT, 0, 0, -1
            deadline = time.monotonic() + len(pcm) / SAMPLE_RATE + 30
            while time.monotonic() < deadline:
                while budget and offset < len(pcm):
                    count = min(CHUNK, budget, len(pcm) - offset)
                    conn.sendall(pcm[offset:offset + count])
                    offset += count
                    budget -= count
                reply = _read_line(stream)
                if reply == 'CREDIT 1024':
                    budget += CHUNK
                    played += CHUNK
                    percent = min(100, played * 100 // len(pcm))
                    if percent // 25 != last_bucket:
                        report(f'[Unit B] playback {percent}%')
                        last_bucket = percent // 25
                elif reply.startswith('DONE '):
                    fields = reply.split()
                    if len(fields) != 3 or int(fields[1]) != len(pcm):
                        raise UnitBError('Completed audio length did not match.')
                    return int(fields[2])
                else:
                    raise UnitBError('Unexpected reply: ' + reply)
            raise TimeoutError('Playback did not finish in time.')
