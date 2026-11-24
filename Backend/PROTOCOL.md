# Laptop ↔ TinyCircuit message protocol

Both units join the same 2.4 GHz WPA2 hotspot as the laptop and show their IP
on the OLED. The **laptop is always the TCP client** and each unit is a server,
so the laptop only needs the two IP addresses.

| Unit | Port | Connection style | Status |
|---|---|---|---|
| Unit B (speaker, Melody) | 5555 | one connection per sentence | **working** (`UnitB_WiFiSpeech.ino`) |
| Unit A (spelling screen + buttons, Jodie) | 5556 | one long-lived connection | **working** (`UnitA_WiFi.ino`) |

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

## Unit A — UNITA_WIFI_V2 (captions + fingerspelling, working: `UnitA/UnitA_WiFi`)

The sign model recognises **one letter at a time**. The laptop keeps the
letters spelled so far (the *spelling buffer*) and shows them on Unit A.
Unit A's buttons edit the buffer. The top of the screen shows live captions
(what the hearing person said, STT), the bottom shows the spelling buffer.

Unit A has buttons, so it must be able to send messages at any time. The
laptop therefore keeps one connection open and reconnects every 2 s if it drops.

**Handshake**
```
Laptop: HELLO
Unit A: UNITA_WIFI_V2
```

**Laptop → Unit A**

| Message | Meaning on Unit A |
|---|---|
| `CAPTION <text>` | what the hearing person said (STT). Empty = clear the caption |
| `TEXT <letters>` | the whole spelling buffer (may be empty, may end with a space). Sent after every change and on every (re)connect |
| `SENT <sentence>` | the sentence just sent to Unit B; shown as "Spoken:" until the next letter |
| `STATUS <WORD>` | status line: `IDLE`, `LISTENING`, `SPEAKING`, `NO UNIT B` |
| `CLEAR` | clear the screen text |
| `PING` | heartbeat every 5 s, reply `PONG` |

**Unit A → Laptop**

| Message | Button | Laptop does |
|---|---|---|
| `BTN START` / `BTN STOP` | built-in upper-left (toggle) | live captions on / off |
| `BTN SPACE` | built-in lower-left, tap | add one space (no leading or double spaces) |
| `BTN SEND` | built-in lower-left held 1 s, or upper-right | speak the buffer on Unit B, then empty it |
| `BTN UNDO` | built-in lower-right, or Wireling Port 1 | delete the last letter (or space) |
| `PONG` | – | reply to `PING` |

If the laptop hears nothing for 15 s (so not even a `PONG`), it treats the
link as dead and reconnects. Unit A does the same: if it gets no `PING`
for 15 s, it closes the client and waits for a new connection.

Laptop code: [unita_link.py](unita_link.py).

---

## Interfaces between teammates' Python code

| From | Function the backend calls / expects | Notes |
|---|---|---|
| P1 sign AI | `controller.on_sign_letter(ch)` | call once per recognised **letter** (one character) |
| P5 TTS | `text_to_pcm(text) -> bytes` | already in `Speech/speech.py` |
| P5 STT | `audio_to_text(record_audio(4)) -> str` | backend pauses STT while Unit B speaks so it doesn't caption our own TTS |
