"""Windows speech generation and TCP sender for UnitB_WiFiSpeech."""
import ipaddress
import os
from pathlib import Path
import socket
import subprocess
import time
import wave

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Speech'))
try:
    import speech    # type: ignore  # Julia's Piper TTS
except Exception:
    speech = None

print('Voice: Piper' if speech else 'Voice: Windows (Piper not available)')

BASE = Path(__file__).resolve().parent
PORT = 5555
TTS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Eight, [System.Speech.AudioFormat.AudioChannel]::Mono)
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $speaker.SetOutputToWaveFile($env:UNITB_WAV, $format)
  $speaker.Speak($env:UNITB_TEXT)
} finally { $speaker.Dispose() }
'''

def synthesize(text):
    try:
        encoded = text.encode('ascii')
    except UnicodeEncodeError:
        raise ValueError('Use basic English characters for this version.') from None
    if not encoded or len(encoded) > 160 or any(v < 32 or v > 126 for v in encoded):
        raise ValueError('Use 1-160 basic English characters on one line.')

    # --- Test Julia's Piper voice ---
    if speech is not None:
        try:
            pcm = speech.text_to_pcm(text)
            if pcm and len(pcm) <= 480000:
                return encoded, pcm
        except Exception as error:
            print('Piper failed, using Windows voice:', error)
    # --- end of new part ---

    directory = BASE / 'generated'
    directory.mkdir(exist_ok=True)
    path = directory / 'last-sentence.wav'
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', TTS_SCRIPT],
        env=dict(os.environ, UNITB_TEXT=text, UNITB_WAV=str(path)),
        capture_output=True, text=True, timeout=90,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Windows speech generation failed: ' + result.stderr.strip())
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 1, 16000, 'NONE'):
            raise ValueError('Unexpected speech format.')
        pcm = audio.readframes(audio.getnframes())
    if not pcm or len(pcm) > 480000:
        raise ValueError('Use a shorter sentence (maximum 30 seconds of speech).')
    return encoded, pcm

def read_line(stream):
    raw = stream.readline(256)
    if not raw:
        raise ConnectionError('Unit B closed the connection before confirming completion.')
    if not raw.endswith(b'\n'):
        raise ValueError('Incomplete reply from Unit B.')
    line = raw.decode('ascii', errors='replace').strip()
    if line.startswith('ERROR'):
        raise RuntimeError(line)
    return line

def send_sentence(address, text, report=print):
    address = str(ipaddress.IPv4Address(address))
    report('Generating speech on your laptop...')
    encoded, pcm = synthesize(text)
    report(f'Connecting to Unit B at {address}; speech length {len(pcm)/16000:.1f} seconds...')
    with socket.create_connection((address, PORT), timeout=10) as connection:
        connection.settimeout(15)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with connection.makefile('rb') as stream:
            connection.sendall(b'PING\n')
            if read_line(stream) != 'UNITB_WIFI_V1':
                raise RuntimeError('Upload the matching UnitB_WiFiSpeech sketch first.')
            connection.sendall(f'SAY 16000 {len(pcm)} {len(encoded)}\n'.encode('ascii') + encoded)
            if read_line(stream) != 'READY 7168':
                raise RuntimeError('Unit B did not accept the audio transfer.')
            budget, offset, played, last_bucket = 7168, 0, 0, -1
            deadline = time.monotonic() + len(pcm)/16000 + 30
            report('Sending text and audio over Wi-Fi...')
            while time.monotonic() < deadline:
                while budget and offset < len(pcm):
                    count = min(1024, budget, len(pcm) - offset)
                    connection.sendall(pcm[offset:offset+count])
                    offset += count
                    budget -= count
                reply = read_line(stream)
                if reply == 'CREDIT 1024':
                    budget += 1024
                    played += 1024
                    percent = min(100, played * 100 // len(pcm))
                    if percent // 10 != last_bucket:
                        report(f'Unit B playback: {percent}%')
                        last_bucket = percent // 10
                elif reply.startswith('DONE '):
                    fields = reply.split()
                    if len(fields) != 3 or int(fields[1]) != len(pcm):
                        raise RuntimeError('The completed audio length did not match.')
                    pauses = int(fields[2])
                    if pauses:
                        report(f'Finished. Audio buffer ran dry {pauses} time(s); keep a stronger Wi-Fi signal.')
                    else:
                        report('Finished. Type another sentence to send again.')
                    return
                else:
                    raise RuntimeError('Unexpected reply: ' + reply)
            raise TimeoutError('Playback did not finish within the allowed time.')

def main():
    print('\nUNIT B - WI-FI TEXT AND SPEECH\n')
    print('Use the UnitB_WiFiSpeech sketch and wait for WIFI READY.')
    print('Your laptop and Unit B must use the same Wi-Fi network.')
    print('Enter only the IP address on the TinyScreen, without http://.\n')
    address = input('Unit B IP address: ').strip()
    while True:
        print(f'\nUnit B address: {address}')
        text = input('Type a sentence, /ip to change address, or /quit to exit:\n> ').strip()
        if text.lower() == '/quit': return
        if text.lower() == '/ip':
            address = input('Unit B IP address: ').strip()
            continue
        if not text: continue
        try:
            send_sentence(address, text)
        except Exception as error:
            print('\nCould not send:', error)
            print('Check WIFI READY/FINISHED, the IP address, and that both devices use the same network.')
            print('If the board is still SPEAKING, let it time out or restart it before retrying.')

if __name__ == '__main__':
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print('\nSender closed.')
