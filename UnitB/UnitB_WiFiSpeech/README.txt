UNIT B - WI-FI TEXT AND SPEECH

Sentence → TTS generates audio → PCM numbers
                                    ↓
                         TinyScreen+ DAC
                                    ↓
                           Amplifier → Speaker

WHATS REQUIRED to run contents of this folder:
Hardware: TinyScreen+, Wi-Fi shield, Wireling adapter, amplifier and speaker
Amplifier connection: Adapter port 0, carrying DAC output A0
Network: Compatible 2.4 GHz WPA2 network
Connection: Laptop connects to Unit B’s IP on TCP port 5555
Audio: 16,000 Hz, mono, unsigned 8-bit raw PCM
Current limits: Basic English, 160 characters, up to 30 seconds of audio
Display: Long sentences currently get cut off


1. Extract the complete ZIP.
2. Switch OFF and unplug USB/battery before changing hardware.
3. Stack TinyScreen+, the ASD2123-R Wi-Fi TinyShield, and Wireling adapter
   using the matching tan 32-pin connectors. Check alignment; do not force.
4. Connect the audio amplifier to Wireling adapter PORT 0 and its speaker.
5. Turn on a 2.4 GHz WPA2-Personal hotspot/router. Connect the laptop to it.
A phone hotspot is usually easier.
6. Open UnitB_WiFiSpeech/UnitB_WiFiSpeech.ino in Arduino IDE.
7. Open its arduino_secrets.h tab. Replace YOUR_WIFI_NAME and
   YOUR_WIFI_PASSWORD with your actual details, keeping quotation marks.
   Enter credentials locally. If a value contains a literal
   backslash or double quote, it needs C++ string escaping.
8. Reconnect USB, switch ON, select TinyScreen+ and its current COM port,
   then upload. Installed libraries: TinyScreen, Wireling,
   SAMD_TimerInterrupt, and WiFi101.
9. Wait for WIFI READY and the board's IP address on its screen.
10. Double-click Open_WiFi_Sender.cmd from this package.
11. Enter the board's IP address only, for example 192.168.1.25 (not COM13
    and not http://). Type a sentence and press Enter.
12. The sender shows playback progress; Unit B displays and speaks it.
    Enter another sentence to send again. No further upload is required.

Use /ip to change the IP address and /quit to close the sender.
Do not use the earlier Open_Sender.cmd for this Wi-Fi sketch.
USB can remain connected for power; sentence data uses TCP over Wi-Fi,
port 5555. This is not a browser address. The old USB sketch remains in
its own folder and can be uploaded again if needed.

Power: USB is suitable for initial use. Do not use a TinyDuino coin cell
for this shield. If using battery later, check its ability to supply the
Wi-Fi shield's peak current and the speaker load.

Screen status:
EDIT WIFI INFO: edit arduino_secrets.h and upload.
NO WIFI SHIELD: power off and check the shield model and connector.
WIFI FAILED: check network name/password, 2.4 GHz and WPA2-Personal.
WIFI LOST: restore the network and restart the board.
SEND AGAIN: sender disconnected or transfer timed out; retry after it ends.
FINISHED: the sentence finished; the board accepts a new connection.

The sender generates speech locally using Windows System.Speech.
It supports basic English text (1-160 characters) and up to 30 seconds of
mono 16000 Hz unsigned 8-bit PCM. The screen shows the portion that fits.
The latest generated WAV is saved in generated/last-sentence.wav.
The launcher uses the Python runtime bundled with Codex on this laptop.
No pyserial, Tcl/Tk, external TTS service, or sample.raw.h is required.

Audio uses a short timer interrupt to write directly to the SAMD21 DAC,
allowing network reception to continue in the main program. The sender
reports buffer underruns. Physical playback quality depends on the board,
speaker, and network; it has not been verified remotely.

This is a local-network prototype with no authentication or encryption.
Use your own hotspot/private network; do not expose TCP port 5555 online.

Reference for shield pins and specifications:
https://learn.tinycircuits.com/Communication/WiFi_TinyShield_Tutorial/

Reference for shield pins and specifications:
https://learn.tinycircuits.com/Communication/WiFi_TinyShield_Tutorial/
