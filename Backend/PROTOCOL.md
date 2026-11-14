# Laptop ↔ TinyCircuit message protocol

Both units join the same 2.4 GHz WPA2 hotspot as the laptop and show their IP
on the OLED. The **laptop is always the TCP client** and each unit is a server,
so the laptop only needs the two IP addresses.

| Unit | Port | Connection style | Status |
|---|---|---|---|
| Unit B (speaker, Melody) | 5555 | one connection per sentence | **working** (`UnitB_WiFiSpeech.ino`) |
| Unit A (captions + buttons, Jodie) | 5556 | one long-lived connection | **DRAFT — agree with Jodie** |

All text lines are ASCII ending in `\n`. Text shown on screens: printable
ASCII (32–126) only, max 160 characters.

---

## Unit B — UNITB_WIFI_V1 (already implemented)

```
Laptop                         Unit B
PING                    →
                        ←      UNITB_WIFI_V1
SAY 16000 <pcm_len> <text_len>\n<text bytes>  →
                        ←      READY 7168
<up to 7168 bytes PCM>  →
                        ←      CREDIT 1024        (each time 1024 samples are played)
<1024 more bytes>       →
        ... repeat ...
                        ←      DONE <played> <underruns>
(connection closes)
```

- Audio: 16 000 Hz, mono, unsigned 8-bit PCM, no WAV header, max 480 000 bytes (30 s).
- Any failure: Unit B sends `ERROR <reason>` and closes.
- Unit B handles **one sentence at a time** and blocks until `DONE`, so the
  laptop keeps a queue and only sends the next sentence after `DONE`.

Laptop code: [unitb_client.py](unitb_client.py) → `send(ip, text, pcm)`.

---

## Unit A — UNITA_WIFI_V1 (draft)

Unit A has buttons, so it must be able to send messages at any time. The
laptop therefore keeps one connection open and reconnects every 2 s if it drops.

**Handshake**
```
Laptop: HELLO
Unit A: UNITA_WIFI_V1
```

**Laptop → Unit A**

| Message | Meaning on Unit A |
|---|---|
| `CAPTION <text>` | show what the hearing person said (STT result) |
| `STATUS <WORD>` | small status line: `IDLE`, `LISTENING`, `SPEAKING` |
| `CLEAR` | clear the caption area |
| `PING` | heartbeat every 5 s, reply `PONG` |

**Unit A → Laptop**

| Message | When |
|---|---|
| `BTN START` | start button: turn live captions on |
| `BTN STOP` | stop button: turn live captions off |
| `BTN UNDO` | undo: cancel the last signed sentence if it hasn't been spoken yet |
| `TOF NEAR` / `TOF FAR` | user comes in front of / leaves the device (send only on change) |
| `PONG` | reply to `PING` |

If the laptop hears nothing for 15 s (so not even a `PONG`), it treats the
link as dead and reconnects. Unit A should do the same: if it gets no `PING`
for 15 s, close the client and wait for a new connection.

Laptop code: [unita_link.py](unita_link.py).

### Open questions for the team
1. What should START/STOP actually control: live captions (current draft), sign recognition, or both?
2. What should ToF do: wake the screen, start sign recognition automatically, or nothing?
3. Long captions: should Unit A scroll them, or should the laptop split them into screen-sized pieces?
4. What exactly can UNDO undo: only sentences still in the queue (current draft), or also the last sign word while someone is still signing (needs P1)?

---

## Interfaces between teammates' Python code

| From | Function the backend calls / expects | Notes |
|---|---|---|
| P1 sign AI | `controller.on_sign_sentence(text)` | call once per **final** sentence |
| P5 TTS | `text_to_pcm(text) -> bytes` | already in `Speech/speech.py` |
| P5 STT | `audio_to_text(record_audio(4)) -> str` | backend pauses STT while Unit B speaks so it doesn't caption our own TTS |
