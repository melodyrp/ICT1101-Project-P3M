/*
  UNIT A - captions + spelling screen + buttons (Jodie / P2)
  Protocol: UNITA_WIFI_V2, see Backend/PROTOCOL.md

  Screen:  top    = live captions (what the hearing person said, STT)
           bottom = letters signed so far (sign model gives one letter at a time)

  Unit A is a TCP SERVER on port 5556. The laptop (Backend/main.py) connects
  to Unit A's IP and keeps one connection open.

    Laptop -> Unit A:  HELLO | CAPTION <text> | TEXT <letters so far> |
                       SENT <sentence> | STATUS <WORD> | CLEAR | PING
    Unit A -> Laptop:  UNITA_WIFI_V2 | BTN START | BTN STOP | BTN SPACE |
                       BTN UNDO | BTN SEND | PONG

  Buttons (TinyScreen+ built-in buttons, 2 on each side):
    lower-left  = SPACE (tap)  /  SEND = speak it on Unit B (hold 1 s)
    lower-right = UNDO (delete one letter)
    upper-left  = START / STOP live captions
    upper-right = SEND (speak it on Unit B)
  Wireling Port 1 Large Button = UNDO as well (big and easy to hit)
  Wireling Port 0 = disabled (button was unreliable). Set SPACE_BTN_PORT = 0 to use it again.
  Wireling Port 3 = DO NOT USE (A3 is the WiFi shield reset pin)

  WiFi name/password go in arduino_secrets.h (not committed to git).
*/

#include <Wire.h>
#include <SPI.h>
#include <TinyScreen.h>
#include <Wireling.h>
#include <WiFi101.h>
#include "arduino_secrets.h"

// ================== CONFIG ==================
const int  UNITA_PORT     = 5556;
const int  SPACE_BTN_PORT = -1;              // -1 = no Wireling button for SPACE (Port 0 unreliable)
const int  UNDO_BTN_PORT  = 1;               // Wireling Large Button on Port 1
const bool FLIP_SCREEN    = false;           // true if mounted upside down
const unsigned long HOLD_FOR_SEND_MS = 1000; // hold SPACE this long = SEND
const unsigned long LINK_TIMEOUT_MS  = 15000; // no data from laptop for 15 s = dead link
const unsigned long SLEEP_AFTER_MS   = 120000; // screen off after 2 min idle (only while linked)
const unsigned long WIFI_RETRY_MS    = 15000;
const unsigned long DEBOUNCE_MS      = 30;
// ============================================

TinyScreen display = TinyScreen(TinyScreenPlus);
WiFiServer server(UNITA_PORT);
WiFiClient laptop;
const int portPins[4] = {A0, A1, A2, A3};

// screen zones (96 x 64)
const int CAP_TOP = 14, CAP_LINES = 2;      // captions: y 14..37
const int SEP_Y   = 38;
const int SPL_TOP = 40, SPL_LINES = 2;      // spelling: y 40..63

// ---------- state ----------
bool linked = false;            // laptop connected and said HELLO
bool captionsOn = false;
bool asleep = false;
bool wifiUp = false;
String caption = "";            // last thing the hearing person said
String spelling = "";           // letters signed so far (from laptop)
String lastSent = "";           // last sentence sent to Unit B
String statusWord = "IDLE";
String toast = "";
unsigned long toastUntil = 0;
unsigned long lastRx = 0;
unsigned long lastActivity = 0;
unsigned long lastWifiTry = 0;
char rxBuf[200];
int rxLen = 0;

void dropLaptop(const char* why);   // defined further down

// ================= buttons =================
enum { EV_NONE = 0, EV_TAP = 1, EV_HOLD = 2 };

struct Button {
  int pin;            // -1 if no Wireling button
  int idleLevel;
  uint8_t builtinMask;
  bool stable, lastRaw;
  unsigned long lastChange, pressedAt;
  bool holdFired;
};
Button spaceBtn, undoBtn, captionBtn, sendBtn;

void setupButton(Button& b, int port, uint8_t mask) {
  b.pin = (port >= 0 && port <= 2) ? portPins[port] : -1;
  b.builtinMask = mask;
  if (b.pin >= 0) {
    pinMode(b.pin, INPUT);
    delay(5);
    b.idleLevel = digitalRead(b.pin);   // level at boot = not pressed
  }
  b.stable = b.lastRaw = b.holdFired = false;
  b.lastChange = b.pressedAt = 0;
}

bool rawPressed(Button& b) {
  bool p = (b.pin >= 0) && digitalRead(b.pin) != b.idleLevel;
  if (display.getButtons(b.builtinMask)) p = true;
  return p;
}

// allowHold = false: EV_TAP as soon as it is pressed.
// allowHold = true : EV_TAP on release if short, EV_HOLD once after HOLD_FOR_SEND_MS.
int pollButton(Button& b, bool allowHold) {
  unsigned long now = millis();
  bool raw = rawPressed(b);
  if (raw != b.lastRaw) { b.lastRaw = raw; b.lastChange = now; }

  if (now - b.lastChange > DEBOUNCE_MS && raw != b.stable) {
    b.stable = raw;
    if (raw) {                                   // just pressed
      b.pressedAt = now;
      b.holdFired = false;
      if (!allowHold) return EV_TAP;
    } else if (allowHold && !b.holdFired) {      // released before hold time
      return EV_TAP;
    }
  }
  if (allowHold && b.stable && !b.holdFired && now - b.pressedAt >= HOLD_FOR_SEND_MS) {
    b.holdFired = true;
    return EV_HOLD;
  }
  return EV_NONE;
}

// ================= screen =================
String ipString() {
  IPAddress ip = WiFi.localIP();
  return String(ip[0]) + "." + ip[1] + "." + ip[2] + "." + ip[3];
}

int textWidth(const String& s) {
  char buf[100];
  s.toCharArray(buf, sizeof(buf));
  return display.getPrintWidth(buf);
}

void drawStatusBar() {
  display.clearWindow(0, 0, 96, 12);
  display.setCursor(0, 0);
  if (millis() < toastUntil) {
    display.fontColor(TS_8b_Yellow, TS_8b_Black);
    display.print(toast);
  } else if (statusWord == "LISTENING") {
    display.fontColor(TS_8b_Green, TS_8b_Black);
    display.print("LISTENING");
  } else if (statusWord == "SPEAKING") {
    display.fontColor(TS_8b_Blue, TS_8b_Black);
    display.print("SPEAKING");
  } else if (statusWord == "IDLE") {
    display.fontColor(TS_8b_White, TS_8b_Black);
    display.print("READY");
  } else {
    display.fontColor(TS_8b_Red, TS_8b_Black);
    display.print(statusWord);
  }
  display.setCursor(76, 0);
  if (linked)      { display.fontColor(TS_8b_Green,  TS_8b_Black); display.print("LINK"); }
  else if (wifiUp) { display.fontColor(TS_8b_Yellow, TS_8b_Black); display.print("wifi"); }
  else             { display.fontColor(TS_8b_Red,    TS_8b_Black); display.print("--"); }
  display.drawLine(0, 11, 95, 11, TS_8b_Blue);
}

// Wraps at spaces where possible; a word too long for one line is split.
// Shows only the newest lines. Spaces are kept so a typed SPACE is visible.
void drawWrapped(const String& text, int top, int maxLines, uint8_t color) {
  const int LINE_H = 12, MAX_W = 94;
  String lines[24];
  int n = 0;
  String cur = "";
  for (unsigned int i = 0; i < text.length() && n < 23; i++) {
    String trial = cur + text[i];
    if (textWidth(trial) <= MAX_W) { cur = trial; continue; }
    int sp = cur.lastIndexOf(' ');
    if (sp > 0 && text[i] != ' ') {              // move the unfinished word down
      lines[n++] = cur.substring(0, sp);
      cur = cur.substring(sp + 1) + text[i];
    } else {                                     // no space to break at: hard split
      lines[n++] = cur;
      cur = (text[i] == ' ') ? String("") : String(text[i]);
    }
  }
  lines[n++] = cur;

  display.fontColor(color, TS_8b_Black);
  int first = n > maxLines ? n - maxLines : 0;
  for (int k = first; k < n; k++) {
    display.setCursor(0, top + (k - first) * LINE_H);
    display.print(lines[k]);
  }
}

void drawCaptionZone() {
  display.clearWindow(0, 12, 96, SEP_Y - 12);
  if (caption.length() > 0)  drawWrapped(caption, CAP_TOP, CAP_LINES, TS_8b_Yellow);
  else if (captionsOn)       drawWrapped("Listening...", CAP_TOP, CAP_LINES, TS_8b_Blue);
  else                       drawWrapped("Captions off", CAP_TOP, CAP_LINES, TS_8b_Blue);
}

void drawSpellZone() {
  display.clearWindow(0, SEP_Y, 96, 64 - SEP_Y);
  display.drawLine(0, SEP_Y, 95, SEP_Y, TS_8b_Blue);
  if (spelling.length() > 0)       drawWrapped(spelling + "_", SPL_TOP, SPL_LINES, TS_8b_White);
  else if (lastSent.length() > 0)  drawWrapped("Said: " + lastSent, SPL_TOP, SPL_LINES, TS_8b_Green);
  else                             drawWrapped("Sign letters...", SPL_TOP, SPL_LINES, TS_8b_Blue);
}

void drawBody() {
  if (!wifiUp) {
    display.clearWindow(0, 12, 96, 52);
    drawWrapped("No WiFi. Check hotspot (2.4 GHz, WPA2).", 14, 4, TS_8b_White);
  } else if (!linked) {
    display.clearWindow(0, 12, 96, 52);
    drawWrapped("Waiting for laptop IP " + ipString() + " port " + String(UNITA_PORT), 14, 4, TS_8b_White);
  } else {
    drawCaptionZone();
    drawSpellZone();
  }
}

void redrawAll() { if (!asleep) { drawStatusBar(); drawBody(); } }

void showToast(const String& msg) {
  toast = msg;
  toastUntil = millis() + 1000;
  if (!asleep) drawStatusBar();
}

// ================= sleep =================
void wake() {
  lastActivity = millis();
  if (asleep) { asleep = false; display.on(); redrawAll(); }
}

void maybeSleep() {
  // only sleep when linked, captions off and idle - otherwise keep info visible
  if (!asleep && linked && !captionsOn && millis() - lastActivity > SLEEP_AFTER_MS) {
    asleep = true;
    display.off();
  }
}

// ================= WiFi =================
const char* statusName(int s) {
  switch (s) {
    case WL_CONNECTED:      return "CONNECTED";
    case WL_NO_SSID_AVAIL:  return "NO_SSID_AVAIL (hotspot not found - open iPhone hotspot screen)";
    case WL_CONNECT_FAILED: return "CONNECT_FAILED (wrong password)";
    case WL_DISCONNECTED:   return "DISCONNECTED";
    case WL_NO_SHIELD:      return "NO_SHIELD (reseat WiFi shield)";
    default:                return "OTHER";
  }
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  SerialUSB.print("Connecting to "); SerialUSB.println(WIFI_SSID);
  int s = WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t = millis();
  while (s != WL_CONNECTED && millis() - t < 15000) { delay(250); s = WiFi.status(); }
  lastWifiTry = millis();
  SerialUSB.print("  -> "); SerialUSB.println(statusName(s));
  if (s == WL_CONNECTED) {
    server.begin();
    wifiUp = true;
    SerialUSB.print("  Unit A IP: "); SerialUSB.print(ipString());
    SerialUSB.print("  port "); SerialUSB.println(UNITA_PORT);
  }
  redrawAll();
}

void checkWifi() {
  bool up = WiFi.status() == WL_CONNECTED;
  if (wifiUp && !up) {
    SerialUSB.println("WiFi DROPPED (hotspot went away)");
    wifiUp = false;
    dropLaptop("wifi lost");
    redrawAll();
  }
  if (!wifiUp && millis() - lastWifiTry > WIFI_RETRY_MS) connectWifi();
}

// ================= laptop link =================
void sendLine(const char* line) {
  if (laptop && laptop.connected()) { laptop.print(line); laptop.print('\n'); }
}

void dropLaptop(const char* why) {
  if (laptop) laptop.stop();
  rxLen = 0;
  if (linked) {
    linked = false;
    captionsOn = false;
    statusWord = "IDLE";
    SerialUSB.print("Laptop disconnected: "); SerialUSB.println(why);
    wake();
    redrawAll();
  }
}

// NOTE: no trim() on the payload - a trailing space in TEXT is meaningful.
void handleLine(const String& line) {
  if (line.length() == 0) return;
  lastRx = millis();

  if (line == "HELLO") {
    sendLine("UNITA_WIFI_V2");
    linked = true;
    caption = "";
    SerialUSB.println("Laptop connected (HELLO)");
    wake();
    redrawAll();
  } else if (line == "PING") {
    sendLine("PONG");
  } else if (line == "CAPTION" || line.startsWith("CAPTION ")) {
    caption = line.length() > 8 ? line.substring(8) : String("");
    SerialUSB.print("CAPTION: "); SerialUSB.println(caption);
    wake();
    if (!asleep) drawCaptionZone();
  } else if (line == "TEXT" || line.startsWith("TEXT ")) {
    spelling = line.length() > 5 ? line.substring(5) : String("");
    if (spelling.length() > 0) lastSent = "";      // new sentence started
    SerialUSB.print("TEXT: \""); SerialUSB.print(spelling); SerialUSB.println("\"");
    wake();
    if (!asleep) drawSpellZone();
  } else if (line.startsWith("SENT ")) {
    lastSent = line.substring(5);
    SerialUSB.print("SENT: "); SerialUSB.println(lastSent);
    wake();
    if (!asleep) drawSpellZone();
  } else if (line.startsWith("STATUS ")) {
    statusWord = line.substring(7);
    if (statusWord == "LISTENING") captionsOn = true;
    else if (statusWord == "IDLE") captionsOn = false;
    SerialUSB.print("STATUS: "); SerialUSB.println(statusWord);
    if (!asleep) { drawStatusBar(); drawCaptionZone(); }
  } else if (line == "CLEAR") {
    caption = "";
    spelling = "";
    lastSent = "";
    if (!asleep) drawBody();
  } else {
    SerialUSB.print("Unknown message: "); SerialUSB.println(line);
  }
}

void serviceLaptop() {
  if (!wifiUp) return;

  // accept a connection only when we don't already have a live one
  if (!laptop || !laptop.connected()) {
    if (laptop) dropLaptop("closed");
    WiFiClient incoming = server.available();
    if (!incoming) return;
    laptop = incoming;
    linked = false;
    rxLen = 0;
    lastRx = millis();
    SerialUSB.println("Laptop connecting...");
  }

  while (laptop.available()) {
    char c = laptop.read();
    if (c == '\n') {
      rxBuf[rxLen] = 0;
      handleLine(String(rxBuf));
      rxLen = 0;
    } else if (c != '\r' && rxLen < (int)sizeof(rxBuf) - 1) {
      rxBuf[rxLen++] = c;
    }
  }

  if (millis() - lastRx > LINK_TIMEOUT_MS) dropLaptop("no PING for 15 s");
}

// ================= button actions =================
// returns false if the press was only used to wake the screen / no laptop
bool pressReady() {
  if (asleep) { wake(); return false; }   // first press only wakes the screen
  wake();
  if (!linked) { showToast("No laptop"); return false; }
  return true;
}

void pressed(const char* btnMsg, const char* label) {
  if (!pressReady()) return;
  sendLine(btnMsg);
  SerialUSB.print("sent "); SerialUSB.println(btnMsg);
  showToast(label);
}

void toggleCaptions() {
  if (!pressReady()) return;
  captionsOn = !captionsOn;
  sendLine(captionsOn ? "BTN START" : "BTN STOP");
  SerialUSB.println(captionsOn ? "sent BTN START" : "sent BTN STOP");
  if (!captionsOn) caption = "";
  drawCaptionZone();
  showToast(captionsOn ? "Captions on" : "Captions off");
}

// ================= setup / loop =================
void setup() {
  SerialUSB.begin(9600);
  delay(1000);                      // let the WiFi shield power up

  WiFi.setPins(8, 2, A3, -1);       // WiFi first, before anything touches SPI / A3
  WiFi.setTimeout(15000);

  Wire.begin();
  Wireling.begin();
  display.begin();
  display.setFlip(FLIP_SCREEN);
  display.setBrightness(10);
  display.setFont(thinPixel7_10ptFontInfo);
  display.clearScreen();

  setupButton(spaceBtn,   SPACE_BTN_PORT, TSButtonLowerLeft);
  setupButton(undoBtn,    UNDO_BTN_PORT,  TSButtonLowerRight);
  setupButton(captionBtn, -1,             TSButtonUpperLeft);
  setupButton(sendBtn,    -1,             TSButtonUpperRight);

  statusWord = "STARTING";
  drawStatusBar();
  display.clearWindow(0, 12, 96, 52);
  drawWrapped("Connecting to WiFi...", 14, 4, TS_8b_White);

  if (WiFi.status() == WL_NO_SHIELD) {
    SerialUSB.println("WiFi shield NOT found");
    display.clearWindow(0, 12, 96, 52);
    drawWrapped("No WiFi shield. Power off and reseat it.", 14, 4, TS_8b_White);
    while (true) {}
  }
  if (strlen(WIFI_PASS) < 8 || !strcmp(WIFI_SSID, "YOUR_WIFI_NAME")) {
    display.clearWindow(0, 12, 96, 52);
    drawWrapped("Edit arduino_secrets.h and upload again.", 14, 4, TS_8b_White);
    while (true) {}
  }

  connectWifi();
  statusWord = "IDLE";
  lastActivity = millis();
  redrawAll();
}

void loop() {
  int ev = pollButton(spaceBtn, true);
  if (ev == EV_TAP)  pressed("BTN SPACE", "Space");
  if (ev == EV_HOLD) pressed("BTN SEND",  "Sending...");

  if (pollButton(undoBtn,    false) == EV_TAP) pressed("BTN UNDO", "Undo");
  if (pollButton(sendBtn,    false) == EV_TAP) pressed("BTN SEND", "Sending...");
  if (pollButton(captionBtn, false) == EV_TAP) toggleCaptions();

  // restore normal status bar after a toast
  static bool toastShown = false;
  if (millis() < toastUntil) toastShown = true;
  else if (toastShown) { toastShown = false; if (!asleep) drawStatusBar(); }

  checkWifi();
  serviceLaptop();
  maybeSleep();
}
