UNIT A - CAPTIONS + SPELLING SCREEN + BUTTONS (Jodie)

Protocol: UNITA_WIFI_V2 (Backend/PROTOCOL.md). Unit A is a TCP server on
port 5556; the laptop (Backend/main.py) connects to Unit A's IP.

Screen: top = live captions (hearing person, STT), bottom = letters signed so far.

Buttons (TinyScreen+ built-in):
  upper-left  = START / STOP live captions
  upper-right = SEND (speak the spelled text on Unit B)
  lower-left  = SPACE (tap) / SEND (hold 1 s)
  lower-right = UNDO (delete one letter)
  Wireling Port 1 Large Button = UNDO too.  Port 0 disabled.  Port 3 must stay EMPTY.

1. Open UnitA_WiFi/UnitA_WiFi.ino in Arduino IDE (board: TinyScreen+).
2. In the arduino_secrets.h tab, put the hotspot name and password.
   (2.4 GHz, WPA2. iPhone: turn on Maximize Compatibility.)
3. Upload. The screen shows "Waiting for laptop IP x.x.x.x port 5556".
4. On the laptop (same hotspot), from the Backend folder:
     python main.py --unita <Unit A IP> --tts beep
   Screen top-right turns green "LINK". Captions use the laptop mic (Speech/ set up).

Screen top-right: LINK = laptop connected, wifi = WiFi ok but no laptop,
-- = no WiFi. Serial Monitor (9600 baud) prints the reason for any failure.
