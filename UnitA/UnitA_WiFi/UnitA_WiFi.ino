/*
  UNIT A - captions + buttons (Jodie / P2)
  Protocol: UNITA_WIFI_V1, see Backend/PROTOCOL.md

  Unit A is a TCP SERVER on port 5556. The laptop (Backend/main.py) connects
  to Unit A's IP and keeps one connection open.

    Laptop -> Unit A:  HELLO | CAPTION <text> | STATUS <WORD> | CLEAR | PING
    Unit A -> Laptop:  UNITA_WIFI_V1 | BTN START | BTN STOP | BTN UNDO | PONG

  Hardware: TinyScreen+ -> WiFi TinyShield (ASD2123-R) -> Wireling Adapter
    Port 0 = Large Button (START / STOP toggle)
    Port 1 = Large Button (UNDO)
    Port 2 = empty
    Port 3 = DO NOT USE (A3 is the WiFi shield reset pin)
  Built-in TinyScreen+ buttons also work: lower-left = START/STOP, lower-right = UNDO

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
const int  START_BTN_PORT = 0;
const int  UNDO_BTN_PORT  = 1;
const bool FLIP_SCREEN    = false;          // true if mounted upside down
const unsigned long LINK_TIMEOUT_MS = 15000; // no data from laptop for 15 s = dead link
const unsigned long SLEEP_AFTER_MS  = 60000; // screen off after 60 s idle (only while linked)
const unsigned long WIFI_RETRY_MS   = 15000;
const unsigned long DEBOUNCE_MS     = 30;
// ============================================

TinyScreen display = TinyScreen(TinyScreenPlus);
WiFiServer server(UNITA_PORT);
WiFiClient laptop;
const int portPins[4] = {A0, A1, A2, A3};

// ---------- state ----------
bool linked = false;            // laptop connected and said HELLO
bool captionsOn = false;        // our idea of START/STOP state
bool asleep = false;
bool wifiUp = false;
String caption = "";
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
struct Button {
  int pin;            // -1 if none
  int idleLevel;
  uint8_t builtinMask;
  bool stable, lastRaw;
  unsigned long lastChange;
};
Button startBtn, undoBtn;

void setupButton(Button& b, int port, uint8_t mask) {
  b.pin = (port >= 0 && port <= 2) ? portPins[port] : -1;
  b.builtinMask = mask;
  if (b.pin >= 0) {
    pinMode(b.pin, INPUT);
    delay(5);
    b.idleLevel = digitalRead(b.pin);   // level at boot = not pressed
  }
  b.stable = b.lastRaw = false;
  b.lastChange = 0;
}

bool rawPressed(Button& b) {
  bool p = (b.pin >= 0) && digitalRead(b.pin) != b.idleLevel;
  if (display.getButtons(b.builtinMask)) p = true;
  return p;
}

bool wasPressed(Button& b) {           // true once per press
  bool raw = rawPressed(b);
  if (raw != b.lastRaw) { b.lastRaw = raw; b.lastChange = millis(); }
  if (millis() - b.lastChange > DEBOUNCE_MS && raw != b.stable) {
    b.stable = raw;
    return raw;
  }
  return false;
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
  } else {
    display.fontColor(TS_8b_White, TS_8b_Black);
    display.print(statusWord);
  }
  display.setCursor(76, 0);
  if (linked)      { display.fontColor(TS_8b_Green,  TS_8b_Black); display.print("LINK"); }
  else if (wifiUp) { display.fontColor(TS_8b_Yellow, TS_8b_Black); display.print("wifi"); }
  else             { display.fontColor(TS_8b_Red,    TS_8b_Black); display.print("--"); }
  display.drawLine(0, 11, 95, 11, TS_8b_Blue);
}

void drawWrapped(String text) {
  const int MAX_LINES = 4, LINE_H = 12, TOP = 14, MAX_W = 94;
  String lines[20];
  int n = 0, i = 0;
  String cur = "";
  while (i <= (int)text.length() && n < 20) {
    int sp = text.indexOf(' ', i);
    if (sp < 0) sp = text.length();
    String word = text.substring(i, sp);
    String trial = cur.length() ? cur + " " + word : word;
    if (cur.length() == 0 || textWidth(trial) <= MAX_W) cur = trial;
    else { lines[n++] = cur; cur = word; }
    i = sp + 1;
  }
  if (cur.length() && n < 20) lines[n++] = cur;

  display.clearWindow(0, 12, 96, 52);
  display.fontColor(TS_8b_White, TS_8b_Black);
  int first = n > MAX_LINES ? n - MAX_LINES : 0;   // newest lines only
  for (int k = first; k < n; k++) {
    display.setCursor(0, TOP + (k - first) * LINE_H);
    display.print(lines[k]);
  }
}

void drawBody() {
  if (!wifiUp)      drawWrapped("No WiFi. Check hotspot (2.4 GHz, WPA2).");
  else if (!linked) drawWrapped("Waiting for laptop  IP " + ipString() + "  port " + String(UNITA_PORT));
  else if (caption.length() == 0)
    drawWrapped(captionsOn ? "Listening..." : "Captions off. Press START");
  else              drawWrapped(caption);
}

void redrawAll() { if (!asleep) { drawStatusBar(); drawBody(); } }

void showToast(const String& msg) {
  toast = msg;
  toastUntil = millis() + 1200;
  if (!asleep) drawStatusBar();
}

// ================= sleep =================
void wake() {
  lastActivity = millis();
  if (asleep) { asleep = false; display.on(); redrawAll(); }
}

void maybeSleep() {
  // only sleep when linked and idle - otherwise keep the IP / warning visible
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

void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;
  lastRx = millis();

  if (line == "HELLO") {
    sendLine("UNITA_WIFI_V1");
    linked = true;
    caption = "";
    SerialUSB.println("Laptop connected (HELLO)");
    wake();
    redrawAll();
  } else if (line == "PING") {
    sendLine("PONG");
  } else if (line.startsWith("CAPTION ")) {
    caption = line.substring(8);
    SerialUSB.print("CAPTION: "); SerialUSB.println(caption);
    wake();
    drawBody();
  } else if (line.startsWith("STATUS ")) {
    statusWord = line.substring(7);
    if (statusWord == "LISTENING") captionsOn = true;
    else if (statusWord == "IDLE") captionsOn = false;
    SerialUSB.print("STATUS: "); SerialUSB.println(statusWord);
    if (!asleep) drawStatusBar();
  } else if (line == "CLEAR") {
    caption = "";
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

  setupButton(startBtn, START_BTN_PORT, TSButtonLowerLeft);
  setupButton(undoBtn,  UNDO_BTN_PORT,  TSButtonLowerRight);

  statusWord = "STARTING";
  drawStatusBar();
  drawWrapped("Connecting to WiFi...");

  if (WiFi.status() == WL_NO_SHIELD) {
    SerialUSB.println("WiFi shield NOT found");
    drawWrapped("No WiFi shield. Power off and reseat it.");
    while (true) {}
  }
  if (strlen(WIFI_PASS) < 8 || !strcmp(WIFI_SSID, "YOUR_WIFI_NAME")) {
    drawWrapped("Edit arduino_secrets.h and upload again.");
    while (true) {}
  }

  connectWifi();
  statusWord = "IDLE";
  lastActivity = millis();
  redrawAll();
}

void loop() {
  if (wasPressed(startBtn)) {
    if (asleep) wake();
    else {
      wake();
      if (!linked) showToast("No laptop");
      else {
                captionsOn = !captionsOn;
        sendLine(captionsOn ? "BTN START" : "BTN STOP");
        SerialUSB.println(captionsOn ? "sent BTN START" : "sent BTN STOP");
        if (!captionsOn) {              // make STOP obvious: clear old caption
          caption = "";
          statusWord = "IDLE";
          drawBody();
        }
        showToast(captionsOn ? "Start" : "Stopped");
      }
    }
  }
  if (wasPressed(undoBtn)) {
    if (asleep) wake();
    else {
      wake();
      if (!linked) showToast("No laptop");
      else { sendLine("BTN UNDO"); SerialUSB.println("sent BTN UNDO"); showToast("Undo"); }
    }
  }

  // restore normal status bar after a toast
  static bool toastShown = false;
  if (millis() < toastUntil) toastShown = true;
  else if (toastShown) { toastShown = false; if (!asleep) drawStatusBar(); }

  checkWifi();
  serviceLaptop();
  maybeSleep();
}
