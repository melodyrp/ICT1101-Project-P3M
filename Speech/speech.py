"""
speech.py - Speech-to-text (Whisper) and text-to-speech (Piper)

Sources / attribution:
  - faster-whisper (MIT): https://github.com/SYSTRAN/faster-whisper
  - Piper TTS (GPL-3.0):   https://github.com/OHF-Voice/piper1-gpl
  - Voice en_US-lessac-medium: https://huggingface.co/rhasspy/piper-voices
  - SpeechRecognition (BSD, fallback STT): https://github.com/Uberi/speech_recognition

Functions for the server (Person 4):
  record_audio(seconds)  -> audio from the laptop mic
  audio_to_text(audio)   -> text the hearing person said
  text_to_audio(text)    -> WAV bytes to send to Unit B
"""
import io
import os
import time
import wave
import urllib.request

import numpy as np
import sounddevice as sd
from piper import PiperVoice

# Whisper (offline) is preferred. If it can't load - e.g. Windows Smart App
# Control blocks its library - fall back to Google speech recognition (online).
try:
    from faster_whisper import WhisperModel
    STT_ENGINE = "whisper"
except Exception as error:
    WhisperModel = None
    STT_ENGINE = "google"
    print(f"Whisper unavailable ({error.__class__.__name__}), using Google speech recognition (needs internet).")

import speech_recognition as sr

# ---------------- Settings ----------------
SPEECH_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SPEECH_DIR, "output")

VOICE = "en_US-lessac-medium"
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/"
MODEL_PATH = os.path.join(SPEECH_DIR, VOICE + ".onnx")

WHISPER_MODEL = "base.en"   # "tiny.en" = faster, "small.en" = more accurate
MIC_RATE = 16000            # Whisper expects 16 kHz mono

# Output format for Unit B (matches Melody's UnitB_WiFiSpeech: 16 kHz, 8-bit unsigned, mono)
OUTPUT_RATE = 16000         # None = keep Piper's original rate (22050 Hz)
OUTPUT_8BIT = True          # True = 8-bit unsigned PCM, False = 16-bit

# Models are loaded once and reused (loading is the slow part)
_whisper = None
_voice = None


# ---------------- Setup helpers ----------------
def ensure_voice():
    """Download the Piper voice files into Speech/ if they're missing."""
    for ext in (".onnx", ".onnx.json"):
        path = os.path.join(SPEECH_DIR, VOICE + ext)
        if not os.path.exists(path):
            print(f"Downloading {VOICE + ext} ...")
            urllib.request.urlretrieve(VOICE_URL + VOICE + ext, path)


def _get_whisper():
    global _whisper
    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def _get_voice():
    global _voice
    if _voice is None:
        ensure_voice()
        _voice = PiperVoice.load(MODEL_PATH)
    return _voice


# ---------------- Speech-to-text ----------------
def record_audio(seconds=5):
    """Record from the laptop mic. Returns a float32 numpy array at 16 kHz."""
    print(f"Recording for {seconds}s... speak now")
    audio = sd.rec(int(seconds * MIC_RATE), samplerate=MIC_RATE,
                   channels=1, dtype="float32")
    sd.wait()
    return audio.flatten()


def audio_to_text(audio):
    """audio: numpy array from record_audio(), or a path to a .wav file.
    Uses Whisper if available, otherwise Google. Returns "" if nothing was understood."""
    if STT_ENGINE == "whisper":
        segments, _ = _get_whisper().transcribe(audio, language="en", vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
    return _google_to_text(audio)


def _google_to_text(audio):
    recognizer = sr.Recognizer()
    if isinstance(audio, str):                      # path to a .wav file
        with sr.AudioFile(audio) as source:
            data = recognizer.record(source)
    else:                                           # float32 numpy array -> 16-bit PCM
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
        data = sr.AudioData(pcm, MIC_RATE, 2)
    try:
        return recognizer.recognize_google(data, language="en-US")
    except sr.UnknownValueError:                    # speech not understood
        return ""
    except sr.RequestError as error:                # no internet / Google unreachable
        print("Google speech recognition failed:", error)
        return ""


# ---------------- Text-to-speech ----------------
def _convert(samples, rate):
    """Change sample rate / bit depth to match OUTPUT_RATE and OUTPUT_8BIT."""
    if OUTPUT_RATE and OUTPUT_RATE != rate:
        n_out = int(len(samples) * OUTPUT_RATE / rate)
        x_new = np.linspace(0, len(samples) - 1, n_out)
        samples = np.interp(x_new, np.arange(len(samples)), samples).astype(np.int16)
        rate = OUTPUT_RATE
    if OUTPUT_8BIT:
        data = ((samples.astype(np.int32) >> 8) + 128).astype(np.uint8)
        width = 1
    else:
        data = samples.astype(np.int16)
        width = 2
    return data, rate, width


def text_to_audio(text):
    """Turn text into speech. Returns WAV file bytes in the Unit B format."""
    raw = io.BytesIO()
    with wave.open(raw, "wb") as wf:
        _get_voice().synthesize_wav(text, wf)
    raw.seek(0)
    with wave.open(raw, "rb") as wf:
        rate = wf.getframerate()
        samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)

    data, rate, width = _convert(samples, rate)

    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(data.tobytes())
    return out.getvalue()


def text_to_pcm(text):
    """Same as text_to_audio() but returns raw PCM bytes (no WAV header),
    which is what Unit B's Wi-Fi sender streams."""
    with wave.open(io.BytesIO(text_to_audio(text)), "rb") as wf:
        return wf.readframes(wf.getnframes())


# ---------------- Quick test ----------------
if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    audio = record_audio(5)

    t = time.time()
    text = audio_to_text(audio)
    print(f"[{STT_ENGINE}] Heard: {text!r}  ({time.time() - t:.2f}s)")

    if text:
        t = time.time()
        wav_bytes = text_to_audio(text)
        print(f"TTS: {len(wav_bytes) / 1024:.0f} KB  ({time.time() - t:.2f}s)")

        path = os.path.join(OUTPUT_DIR, "test.wav")
        with open(path, "wb") as f:
            f.write(wav_bytes)
        print("Saved", path)