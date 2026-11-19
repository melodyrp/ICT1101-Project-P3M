UNIT A - CAPTIONS + BUTTONS (Jodie)

Protocol: UNITA_WIFI_V1 (Backend/PROTOCOL.md). Unit A is a TCP server on
port 5556; the laptop (Backend/main.py) connects to Unit A's IP.

Hardware: TinyScreen+ -> WiFi TinyShield (ASD2123-R) -> Wireling adapter
  Port 0 = START/STOP button, Port 1 = UNDO button, Port 3 must stay EMPTY
  Built-in buttons also work: lower-left = START/STOP, lower-right = UNDO

1. Open UnitA_WiFi/UnitA_WiFi.ino in Arduino IDE (board: TinyScreen+).
2. In the arduino_secrets.h tab, put the hotspot name and password.
   (2.4 GHz, WPA2. iPhone: turn on Maximize Compatibility.)
3. Upload. The screen shows "Waiting for laptop  IP x.x.x.x port 5556".
4. On the laptop (same hotspot), from the Backend folder:
     python main.py --unita <Unit A IP> --tts beep --stt fake
   Screen top-right turns green "LINK".
5. Press START -> fake captions appear every few seconds. STOP stops them.
   Type a sentence in main.py then press UNDO quickly -> "Undone: ..." shows.

Screen top-right: LINK = laptop connected, wifi = WiFi ok but no laptop,
-- = no WiFi. Serial Monitor (9600 baud) prints the reason for any failure.
