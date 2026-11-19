"""Main backend / conversation controller (Person 4 + Person 6).

Flow:
  Signer  --(sign AI, P1)--> sentence --(TTS, P5)--> Unit B speaks it (P3)
  Hearing --(mic + STT, P5)--> caption --> Unit A screen (P2)
  Unit A buttons --> START / STOP captions, UNDO last queued sentence

Placeholders are marked TODO(P#). Each teammate replaces one function.

Quick test with no hardware (3 terminals, from the Backend folder):
    python fake_unitb.py
    python fake_unita.py
    python main.py --tts beep --stt fake
Then type sentences here (pretend signing) and press s/t/u in fake_unita.

Real hardware:
    python main.py --unitb 192.168.1.25 --unita 192.168.1.30
"""
import argparse
import itertools
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
_FAKE_LINES = itertools.cycle([
    'Hi, how can I help you?',
    'Sure, the toilet is on the left.',
    'Could you repeat that please?',
])


def stt_fake():
    time.sleep(4)
    return next(_FAKE_LINES)


def stt_real():
    sys.path.insert(0, str(ROOT / 'Speech'))
    import speech
    return speech.audio_to_text(speech.record_audio(4))


# ---- Sign recognition (Person 1) ----
# TODO(P1): call controller.on_sign_sentence(text) when a sentence is final.
# Until then, sentences typed into this console are used instead (see run()).


# =====================================================================
#  Controller
# =====================================================================
class Controller:
    def __init__(self, unitb_ip, unita_ip, tts, stt):
        self.unitb_ip = unitb_ip
        self.tts, self.stt = tts, stt
        self.pending = deque()               # sentences waiting for Unit B
        self.cv = threading.Condition()
        self.speaking = threading.Event()    # Unit B is playing audio
        self.captioning = threading.Event()  # STT is on
        self.running = True
        self.unita = UnitALink(unita_ip, self.on_unita_event, report=log) if unita_ip else None
        self.sign_receiver = SignReceiver(
            on_sentence=self.on_sign_sentence,
            report=log
        )

    # ---------- inputs ----------
    def on_sign_sentence(self, text):
        """Called by the sign-language module (P1) with a final sentence."""
        text = text.strip()
        if not text:
            return
        try:
            unitb_client.check_text(text)
        except ValueError as error:
            log(f'[sign] rejected "{text}": {error}')
            return
        with self.cv:
            self.pending.append(text)
            self.cv.notify()
        log(f'[sign] queued "{text}" ({len(self.pending)} waiting)')

    def on_unita_event(self, line):
        """Messages from Unit A (see PROTOCOL.md)."""
        log(f'[Unit A] {line}')
        if line == 'BTN START':
            self.start_captions()
        elif line == 'BTN STOP':
            self.stop_captions()
        elif line == 'BTN UNDO':
            self.undo()
        elif line in ('TOF NEAR', 'TOF FAR'):
            pass   # TODO(P2/P6): decide what presence detection should do
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
        log('[stt] captions OFF')

    def undo(self):
        with self.cv:
            removed = self.pending.pop() if self.pending else None
        if removed:
            log(f'[undo] removed "{removed}" before it was spoken')
            self._caption(f'Undone: {removed}')
        else:
            log('[undo] nothing to undo (already spoken or queue empty)')
            self._caption('Nothing to undo')

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
            try:
                for attempt in (1, 2):
                    try:
                        underruns = unitb_client.send(self.unitb_ip, text, pcm,
                                                      report=lambda m: log(m))
                        log(f'[Unit B] done "{text}"' + (f' ({underruns} underruns)' if underruns else ''))
                        break
                    except Exception as error:
                        log(f'[Unit B] attempt {attempt} failed: {error}')
                        if attempt == 2:
                            self._caption('Unit B not responding')
                        else:
                            time.sleep(2)
            finally:
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
        
        self.sign_receiver.start()

        threading.Thread(target=self.speaker_worker, daemon=True).start()
        threading.Thread(target=self.caption_worker, daemon=True).start()
        log(f'Unit B {self.unitb_ip}: ' + ('reachable' if unitb_client.ping(self.unitb_ip) else 'NOT reachable yet'))
        print('\nType a sentence (= pretend signing). Commands: /start /stop /undo /quit\n')
        try:
            while True:
                line = input().strip()
                cmd = line.lower()
                if cmd == '/quit':
                    break
                elif cmd == '/start':
                    self.start_captions()
                elif cmd == '/stop':
                    self.stop_captions()
                elif cmd == '/undo':
                    self.undo()
                else:
                    self.on_sign_sentence(line)   # TODO(P1): replace with webcam output
        except (EOFError, KeyboardInterrupt):
            pass
        self.running = False
        with self.cv:
            self.cv.notify_all()
        if self.unita:
            self.unita.stop()

        self.sign_receiver.stop()
        
        log('backend stopped')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--unitb', default='127.0.0.1', help='Unit B IP (default: fake on this laptop)')
    p.add_argument('--unita', default='127.0.0.1', help="Unit A IP, or 'none' to run without it")
    p.add_argument('--tts', choices=['real', 'beep'], default='real')
    p.add_argument('--stt', choices=['real', 'fake'], default='fake')
    a = p.parse_args()
    Controller(
        unitb_ip=a.unitb,
        unita_ip=None if a.unita.lower() == 'none' else a.unita,
        tts=tts_real if a.tts == 'real' else tts_beep,
        stt=stt_real if a.stt == 'real' else stt_fake,
    ).run()


if __name__ == '__main__':
    main()
