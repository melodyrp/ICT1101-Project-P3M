#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <Wireling.h>
#include <TinyScreen.h>
#include <WiFi101.h>

// The library only emits TC3_Handler when this selection is enabled.
// Without it, the SAMD21 default handler stops execution at the first tick.
#define TIMER_INTERRUPT_DEBUG 0
#define _TIMERINTERRUPT_LOGLEVEL_ 0
#define USING_TIMER_TC3 true
#define USING_TIMER_TC4 false
#define USING_TIMER_TC5 false
#define USING_TIMER_TCC false
#define USING_TIMER_TCC1 false
#define USING_TIMER_TCC2 false
#include "SAMDTimerInterrupt.h"
#include "arduino_secrets.h"

// TinyScreen+ + ASD2123-R + Wireling adapter + amplifier on PORT 0.
// TCP port 5555. Unsigned 8-bit mono PCM at 16000 Hz.
TinyScreen display = TinyScreen(TinyScreenPlus);
WiFiServer server(5555);
SAMDTimer audioTimer(TIMER_TC3);
const uint16_t RING_SIZE = 8192, RING_MASK = 8191;
const uint16_t INITIAL_CREDIT = 7168, CREDIT_SIZE = 1024;
uint8_t audio[RING_SIZE];
volatile uint16_t head = 0, tail = 0;
volatile uint32_t played = 0, totalSamples = 0, underruns = 0;
volatile bool playbackFinished = false, starving = false;
bool timerRunning = false, networkReady = false;
char sentence[161] = {};

void showText(const char *status) {
  display.clearScreen();
  display.fontColor(TS_8b_Green, TS_8b_Black);
  display.setCursor(2, 2);
  display.print(status);
  display.fontColor(TS_8b_White, TS_8b_Black);
  int x = 2, y = 17;
  for (uint16_t i = 0; sentence[i]; i++) {
    char c[2] = {sentence[i], 0};
    int width = display.getPrintWidth(c);
    if (x + width > 94) { x = 2; y += 11; }
    if (y > 50) break;
    display.setCursor(x, y);
    display.print(c);
    x += width;
  }
}

void showAddress(const char *status) {
  IPAddress ip = WiFi.localIP();
  snprintf(sentence, sizeof(sentence), "%u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
  showText(status);
  display.setCursor(2, 45);
  display.print("Wi-Fi port 5555");
}

// Only the DAC and ring-buffer consumer are touched in this interrupt.
// Network, SPI, screen updates, and logging stay in the main program.
void audioTick() {
  if (playbackFinished) return;
  uint16_t currentTail = tail;
  if (currentTail == head) {
    DAC->DATA.reg = 512;
    if (!starving) { underruns++; starving = true; }
    return;
  }
  DAC->DATA.reg = static_cast<uint16_t>(audio[currentTail]) << 2;
  tail = (currentTail + 1) & RING_MASK;
  starving = false;
  played++;
  if (played >= totalSamples) playbackFinished = true;
}

void stopAudio() {
  if (timerRunning) audioTimer.detachInterrupt();
  timerRunning = false;
  analogWrite(A0, 512);
}

bool readLine(WiFiClient &client, char *line, size_t capacity) {
  size_t length = 0;
  uint32_t started = millis();
  while (millis() - started < 10000) {
    if (client.available()) {
      int value = client.read();
      if (value < 0) continue;
      char c = value;
      if (c == '\r') continue;
      if (c == '\n') { line[length] = 0; return true; }
      if (length >= capacity - 1) return false;
      line[length++] = c;
    } else {
      if (!client.connected()) return false;
      delay(1);
    }
  }
  return false;
}

bool readSentence(WiFiClient &client, uint16_t length) {
  uint16_t position = 0;
  uint32_t lastData = millis();
  while (position < length && millis() - lastData < 10000) {
    int count = client.read(reinterpret_cast<uint8_t *>(sentence + position), length - position);
    if (count > 0) { position += count; lastData = millis(); }
    else { if (!client.connected()) return false; delay(1); }
  }
  sentence[position] = 0;
  if (position != length) return false;
  for (uint16_t i = 0; i < length; i++)
    if (sentence[i] < 32 || sentence[i] > 126) sentence[i] = '?';
  return true;
}

void receiveAudio(WiFiClient &client, uint32_t count) {
  stopAudio();
  head = tail = 0;
  played = underruns = 0;
  totalSamples = count;
  playbackFinished = starving = false;
  uint32_t received = 0, credited = 0;
  uint32_t lastData = millis(), lastLinkCheck = millis();
  uint32_t startedAt = millis();
  const uint32_t deadlineMs = (count / 16000UL) * 1000UL + 20000UL;
  const char *failure = nullptr;

  showText("BUFFERING");
  client.println("READY 7168");

  while (!playbackFinished) {
    uint16_t currentHead = head;
    uint16_t currentTail = tail;
    uint16_t freeSpace = (currentTail - currentHead - 1) & RING_MASK;
    if (freeSpace && received < count) {
      uint16_t wanted = min(freeSpace, static_cast<uint16_t>(RING_SIZE - currentHead));
      wanted = min(wanted, static_cast<uint16_t>(1024));
      if (count - received < wanted) wanted = count - received;
      int got = client.read(audio + currentHead, wanted);
      if (got > 0) {
        // Publish only after the block has been copied into the ring.
        __DMB();
        head = (currentHead + got) & RING_MASK;
        received += got;
        lastData = millis();
      }
    }

    if (!timerRunning) {
      uint16_t queued = (head - tail) & RING_MASK;
      uint16_t prefill = count < 4096 ? count : 4096;
      if (queued >= prefill) {
        showText("SPEAKING");
        // The library enables the timer before assigning its callback.
        // Keep interrupts masked until the callback and priority are ready.
        uint32_t interruptMask = __get_PRIMASK();
        __disable_irq();
        NVIC_DisableIRQ(TC3_IRQn);
        NVIC_ClearPendingIRQ(TC3_IRQn);
        bool attached = audioTimer.attachInterrupt(16000, audioTick);
        if (attached) NVIC_SetPriority(TC3_IRQn, 3);
        else NVIC_DisableIRQ(TC3_IRQn);
        if (!interruptMask) __enable_irq();
        if (!attached) {
          failure = "Audio timer could not start";
          break;
        }
        timerRunning = true;
      }
    }

    // played is an aligned 32-bit value: reads are atomic on SAMD21.
    uint32_t consumed = played;
    while (consumed - credited >= CREDIT_SIZE) {
      client.println("CREDIT 1024");
      credited += CREDIT_SIZE;
    }

    if (millis() - lastLinkCheck >= 500) {
      lastLinkCheck = millis();
      if (!client.connected()) { failure = "Laptop disconnected"; break; }
    }
    if (received < count && millis() - lastData > 10000) {
      failure = "Audio data timeout"; break;
    }
    if (millis() - startedAt > deadlineMs) {
      failure = "Playback timeout"; break;
    }
  }

  stopAudio();
  if (failure) {
    showText("SEND AGAIN");
    client.print("ERROR ");
    client.println(failure);
  } else {
    showText("FINISHED");
    client.print("DONE ");
    client.print(played);
    client.print(' ');
    client.println(underruns);
  }
}

void handleLaptop(WiFiClient &client) {
  char header[80];
  if (!readLine(client, header, sizeof(header)) || strcmp(header, "PING")) {
    client.println("ERROR Expected PING"); return;
  }
  client.println("UNITB_WIFI_V1");
  if (!readLine(client, header, sizeof(header))) return;
  unsigned long rate = 0, count = 0, length = 0;
  char extra;
  if (sscanf(header, "SAY %lu %lu %lu %c", &rate, &count, &length, &extra) != 3
      || rate != 16000 || !count || count > 480000 || !length || length > 160) {
    client.println("ERROR Invalid sentence header"); return;
  }
  if (!readSentence(client, length)) {
    client.println("ERROR Incomplete text"); return;
  }
  receiveAudio(client, count);
  delay(50);
}

void setup() {
  SerialUSB.begin(115200);
  Wire.begin();
  Wireling.begin();
  display.begin();
  display.setBrightness(10);
  display.setFont(thinPixel7_10ptFontInfo);
  analogWriteResolution(10);
  analogWrite(A0, 512);

  strcpy(sentence, "Checking ASD2123-R");
  showText("WIFI START");
  WiFi.setPins(8, 2, A3, -1);
  WiFi.setTimeout(15000);
  if (WiFi.status() == WL_NO_SHIELD) {
    strcpy(sentence, "Power off and check the Wi-Fi shield connector.");
    showText("NO WIFI SHIELD"); return;
  }
  if (!strcmp(WIFI_SSID, "YOUR_WIFI_NAME") ||
      !strcmp(WIFI_PASS, "YOUR_WIFI_PASSWORD") ||
      !strlen(WIFI_SSID) || strlen(WIFI_SSID) > 32 ||
      strlen(WIFI_PASS) < 8 || strlen(WIFI_PASS) > 63) {
    strcpy(sentence, "Edit arduino_secrets.h and upload again.");
    showText("EDIT WIFI INFO"); return;
  }
  for (uint8_t attempt = 1; attempt <= 3; attempt++) {
    snprintf(sentence, sizeof(sentence), "Connecting: %u/3", attempt);
    showText("CONNECTING");
    if (WiFi.begin(WIFI_SSID, WIFI_PASS) == WL_CONNECTED && WiFi.localIP() != 0) {
      server.begin();
      networkReady = true;
      showAddress("WIFI READY V2");
      SerialUSB.print("Unit B Wi-Fi address: ");
      SerialUSB.println(IPAddress(WiFi.localIP()));
      return;
    }
    WiFi.disconnect();
    delay(1000);
  }
  strcpy(sentence, "Check name/password and 2.4 GHz WPA2 network. Restart to retry.");
  showText("WIFI FAILED");
}

void loop() {
  if (!networkReady) { delay(100); return; }
  if (WiFi.status() != WL_CONNECTED) {
    networkReady = false;
    strcpy(sentence, "Restore the network and restart Unit B.");
    showText("WIFI LOST"); return;
  }
  WiFiClient client = server.available();
  if (client) {
    handleLaptop(client);
    client.stop();
  }
}
