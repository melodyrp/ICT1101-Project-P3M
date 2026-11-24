"""Main backend / conversation controller (Person 4 + Person 6).

Flow:
  Signer  --(sign AI, P1, one letter at a time, TCP 5560)--> spelling buffer --> shown on Unit A (P2)
          Unit A buttons: SPACE, UNDO (one letter), SEND --> TTS (P5) --> Unit B speaks (P3)
  Hearing --(mic + STT, P5)--> caption --> Unit A screen
          Unit A button: START/STOP live captions

Placeholders are marked TODO(P#). Each teammate replaces one function.

Quick test with no hardware (3 terminals, from the Backend folder):
    python fake_unitb.py
    python fake_unita.py
    python main.py --tts beep
Then type letters here (pretend signing) and press keys in fake_unita.
Captions always use the real microphone + STT (needs Speech/ set up).

Real hardware:
    python main.py --unitb 192.168.1.25 --unita 192.168.1.30
Then start SignAI/fingerspell_team.py: each letter it registers appears on Unit A.
"""
import argparse
import math
import sys
import threading
import time
from collections import deque
from pathlib import Path

import unitb_client
from unita_link import UnitALink
from sign_receiver import SignReceiver

ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT = 160          # Unit B / Unit A limit


def log(msg):
    print(f'{time.strftime("%H:%M:%S")} {msg}', flush=True)


# =====================================================================
#  Teammate hooks - replace the bodies, keep the signatures
# =====================================================================

# ---- TTS (Person 5) : text -> raw 16 kHz mono unsigned 8-bit PCM ----
def tts_beep(text):
    """Fake TTS: a short tone, 0.08 s per character. No dependencies."""
    n = int(16000 * min(30, 0.5 + 0.08 * len(text)))
    return bytes(int(128 + 60 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(n))


def tts_real(text):
    """Piper (Julia's speech.py), falling back to the Windows voice.
    Reuses Melody's synthesize() so both senders behave the same."""
    sys.path.insert(0, str(ROOT / "Speech"))
    import speech
    return speech.text_to_pcm(text)


# ---- STT (Person 5) : listen once, return what the hearing person said ----
def stt_real():
    sys.path.insert(0, str(ROOT / 'Speech'))
    import speech
    return speech.audio_to_text(speech.record_audio(4))


# ---- Sign recognition (Person 1) ----
# P1 runs in its own process (SignAI/fingerspell_team.py) and talks to the
# SignReceiver on TCP 5560 (see sign_receiver.py):
#   sign_letter -> on_sign_letter(ch)      one recognised letter
#   sign_key    -> on_sign_key(key)        space / undo / send / clear / get
#   sign_sentence -> on_sign_sentence(t)   a finished sentence (250-word mode)
# Letters typed into this console also work (see run()).


# =====================================================================
#  Controller
# =====================================================================
class Controller:
    def __init__(self, unitb_ip, unita_ip, tts, stt,
                 sign_host='127.0.0.1', sign_port=5560, sign_enabled=True):
        self.unitb_ip = unitb_ip
        self.tts, self.stt = tts, stt
        self.spelling = ''                   # letters signed so far, not yet spoken
        self.text_lock = threading.Lock()
        self.pending = deque()               # sentences waiting for Unit B
        self.cv = threading.Condition()
        self.speaking = threading.Event()    # Unit B is playing audio
        self.captioning = threading.Event()  # STT is on
        self.running = True
        self.unita = UnitALink(unita_ip, self.on_unita_event, report=log,
                               on_connect=self._push_text) if unita_ip else None
        self.sign_receiver = (
            SignReceiver(self.on_sign_sentence, host=sign_host, port=sign_port, report=log,
                         on_letter=self.on_sign_letter, on_key=self.on_sign_key,
                         get_text=self.get_spelling)
            if sign_enabled else None
        )

    # ---------- inputs ----------
    def on_sign_letter(self, ch):
        """Called by the sign-language module (P1) with ONE recognised letter."""
        ch = str(ch)[:1]
        if not ch or not (32 <= ord(ch) <= 126):
            return
        with self.text_lock:
            if len(self.spelling) >= MAX_TEXT:
                log('[sign] buffer full, letter ignored')
                return
            self.spelling += ch
        log(f'[sign] "{ch}"  -> "{self.spelling}"')
        self._push_text()

    def on_sign_sentence(self, text):
        """A finished sentence (P1 250-word mode or ENTER in an older GUI)."""
        text = text.strip()
        if not text:
            return
        if self.unita:
            self.unita.send_sent(text)
        self.queue_sentence(text)

    def on_sign_key(self, key):
        """Keyboard keys from P1's fingerspelling window. Returns the new text."""
        key = key.lower()
        if key == 'space':
            self.add_space()
        elif key in ('undo', 'backspace'):
            self.undo_letter()
        elif key == 'send':
            self.send()
        elif key == 'clear':
            self.clear_spelling()
        elif key != 'get':
            log(f'[sign] unknown key ignored: {key!r}')
        return self.get_spelling()

    def get_spelling(self):
        with self.text_lock:
            return self.spelling

    def on_unita_event(self, line):
        """Messages from Unit A (see PROTOCOL.md)."""
        log(f'[Unit A] {line}')
        if line == 'BTN START':
            self.start_captions()
        elif line == 'BTN STOP':
            self.stop_captions()
        elif line == 'BTN UNDO':
            if self.get_spelling():
                self.undo_letter()     # letters on screen: delete one
            else:
                self.undo()            # nothing spelled: cancel last queued sentence
        elif line == 'BTN SPACE':
            self.add_space()
        elif line == 'BTN SEND':
            self.send()
        else:
            log(f'[Unit A] unknown message ignored: {line!r}')

    # ---------- actions ----------
    def start_captions(self):
        if self.captioning.is_set():
            log('[stt] captions already ON')
            return
        self.captioning.set()
        self._status('LISTENING')
        log('[stt] captions ON')

    def stop_captions(self):
        if not self.captioning.is_set():
            log('[stt] captions already OFF')
            return
        self.captioning.clear()
        self._status('IDLE')
        self._caption('')
        log('[stt] captions OFF')

    def undo(self):
        """Cancel the last sentence that is queued but not spoken yet."""
        with self.cv:
            removed = self.pending.pop() if self.pending else None
        if removed:
            log(f'[undo] removed "{removed}" before it was spoken')
            self._caption(f'Undone: {removed}')
        else:
            log('[undo] nothing to undo (already spoken or queue empty)')
            self._caption('Nothing to undo')

    def clear_spelling(self):
        with self.text_lock:
            self.spelling = ''
        log('[clear] spelling cleared')
        self._push_text()

    def undo_letter(self):
        with self.text_lock:
            if not self.spelling:
                log('[undo] nothing to undo')
                return
            removed = self.spelling[-1]
            self.spelling = self.spelling[:-1]
        log(f'[undo] removed {removed!r} -> "{self.spelling}"')
        self._push_text()

    def add_space(self):
        with self.text_lock:
            # no leading space, no double spaces
            if not self.spelling or self.spelling.endswith(' ') or len(self.spelling) >= MAX_TEXT:
                return
            self.spelling += ' '
        log(f'[space] -> "{self.spelling}"')
        self._push_text()

    def send(self):
        """Speak whatever has been spelled, then start a new sentence."""
        with self.text_lock:
            text = self.spelling.strip()
            self.spelling = ''
        if not text:
            log('[send] nothing to send')
            return
        self._push_text()
        if self.unita:
            self.unita.send_sent(text)
        self.queue_sentence(text)

    def queue_sentence(self, text):
        try:
            unitb_client.check_text(text)
        except ValueError as error:
            log(f'[send] rejected "{text}": {error}')
            return
        with self.cv:
            self.pending.append(text)
            self.cv.notify()
        log(f'[send] queued "{text}" ({len(self.pending)} waiting)')

    def _push_text(self):
        if self.unita:
            with self.text_lock:
                text = self.spelling
            self.unita.send_text(text)

    def _caption(self, text):
        if self.unita:
            self.unita.send_caption(text)

    def _status(self, word):
        if self.unita:
            self.unita.send_status(word)

    # ---------- workers ----------
    def speaker_worker(self):
        """One sentence at a time: TTS -> Unit B -> wait for DONE -> next."""
        while self.running:
            with self.cv:
                while self.running and not self.pending:
                    self.cv.wait()
                if not self.running:
                    return
                text = self.pending.popleft()
            try:
                t0 = time.monotonic()
                pcm = self.tts(text)
                log(f'[tts] "{text}" -> {len(pcm) / 16000:.1f}s audio in {time.monotonic() - t0:.1f}s')
            except Exception as error:
                log(f'[tts] failed for "{text}": {error}')
                continue
            self.speaking.set()
            self._status('SPEAKING')
            ok = False
            for attempt in (1, 2):
                try:
                    underruns = unitb_client.send(self.unitb_ip, text, pcm,
                                                  report=lambda m: log(m))
                    log(f'[Unit B] done "{text}"' + (f' ({underruns} underruns)' if underruns else ''))
                    ok = True
                    break
                except Exception as error:
                    log(f'[Unit B] attempt {attempt} failed: {error}')
                    if attempt == 1:
                        time.sleep(2)
            if not ok:
                self._caption('Unit B not responding')
            self.speaking.clear()
            self._status('LISTENING' if self.captioning.is_set() else 'IDLE')

    def caption_worker(self):
        """While captions are on, listen and push text to Unit A.
        Pauses while Unit B is speaking so the mic doesn't caption our own TTS."""
        while self.running:
            if not self.captioning.is_set() or self.speaking.is_set():
                time.sleep(0.1)
                continue
            try:
                text = self.stt()
            except Exception as error:
                log(f'[stt] error: {error}')
                time.sleep(1)
                continue
            if text and self.captioning.is_set() and not self.speaking.is_set():
                log(f'[stt] "{text}"')
                self._caption(text)

    # ---------- lifecycle ----------
    def run(self):
        log('loading TTS (first load can take ~10 s)...')
        try:
            self.tts('Ready')               # load the voice model now, not on the first sentence
        except Exception as error:
            log(f'[tts] warm-up failed: {error}')
        if self.unita:
            self.unita.start()
        if self.sign_receiver:
            self.sign_receiver.start()
        threading.Thread(target=self.speaker_worker, daemon=True).start()
        threading.Thread(target=self.caption_worker, daemon=True).start()
        log(f'Unit B {self.unitb_ip}: ' + ('reachable' if unitb_client.ping(self.unitb_ip) else 'NOT reachable yet'))
        print('\nPerson 1 fingerspelling (letters/keys/sentences) is accepted on TCP port 5560.\n'
              'You can also type letters + Enter here (each character is one letter).\n'
              'Commands: /space /undo /send /start /stop /say <sentence> /quit\n')
        try:
            while True:
                line = input()
                cmd = line.strip().lower()
                if cmd == '/quit':
                    break
                elif cmd == '/space':
                    self.add_space()
                elif cmd == '/undo':
                    self.undo_letter()
                elif cmd == '/send':
                    self.send()
                elif cmd == '/start':
                    self.start_captions()
                elif cmd == '/stop':
                    self.stop_captions()
                elif cmd.startswith('/say '):
                    self.queue_sentence(line.strip()[5:].strip())
                else:
                    for ch in line.strip():           # TODO(P1): replace with webcam output
                        if ch == ' ':
                            self.add_space()
                        else:
                            self.on_sign_letter(ch)
        except (EOFError, KeyboardInterrupt):
            pass
        self.running = False
        with self.cv:
            self.cv.notify_all()
        if self.unita:
            self.unita.stop()
        if self.sign_receiver:
            self.sign_receiver.stop()
        log('backend stopped')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--unitb', default='127.0.0.1', help='Unit B IP (default: fake on this laptop)')
    p.add_argument('--unita', default='127.0.0.1', help="Unit A IP, or 'none' to run without it")
    p.add_argument('--tts', choices=['real', 'beep'], default='real')
    p.add_argument('--sign-host', default='127.0.0.1', help='Person 1 sign receiver bind address')
    p.add_argument('--sign-port', type=int, default=5560, help='Person 1 sign receiver TCP port')
    p.add_argument('--no-sign', action='store_true', help='disable Person 1 TCP receiver')
    a = p.parse_args()
    Controller(
        unitb_ip=a.unitb,
        unita_ip=None if a.unita.lower() == 'none' else a.unita,
        tts=tts_real if a.tts == 'real' else tts_beep,
        stt=stt_real,
        sign_host=a.sign_host,
        sign_port=a.sign_port,
        sign_enabled=not a.no_sign,
    ).run()


if __name__ == '__main__':
    main()
