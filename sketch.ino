// UNO Q two-phase footstep recorder (protocol 2028).
// Capture ONE 10 s 6 kHz microphone WAV (A0) with no other sensors active,
// then 10 s of A0 microphone 500 Hz, A1 piezo 500 Hz, MPU6050 200 Hz.
// The two phases ARE NOT simultaneously synchronized.
// Best-effort acquisition using micros()/analogRead(), NOT DMA/timer sampling.
// Audio dropouts remain measurable; do not assume 6 kHz is achievable.

#include <Wire.h>
#include <Arduino_RouterBridge.h>
#include <array>
#include <stdint.h>

constexpr int MIC_PIN = A0;
constexpr int PIEZO_PIN = A1;
constexpr uint8_t MPU_ADDR = 0x68;
constexpr uint32_t AUDIO_HZ = 6000;
constexpr uint32_t ANALOG_HZ = 500;
constexpr uint32_t MPU_HZ = 200;
constexpr uint32_t MAX_SECONDS = 10;
constexpr uint32_t MAX_AUDIO = MAX_SECONDS * AUDIO_HZ;
constexpr uint32_t MAX_ANALOG = MAX_SECONDS * ANALOG_HZ;
constexpr uint32_t MAX_MPU = MAX_SECONDS * MPU_HZ;
constexpr int16_t MISSING = -32768;
constexpr int32_t PROTOCOL = 2028;

// 152 kB static buffers. Different sensors are sampled in separate phases.
static int16_t audioRaw[MAX_AUDIO];
static int16_t mic500[MAX_ANALOG];
static int16_t piezo500[MAX_ANALOG];
static int16_t xRaw[MAX_MPU];
static int16_t yRaw[MAX_MPU];
static int16_t zRaw[MAX_MPU];

uint32_t startUs = 0;
uint32_t secondsActive = 0;
uint32_t targetAudio = 0, targetAnalog = 0, targetMpu = 0;
uint32_t nAudio = 0, nAnalog = 0, nMpu = 0;
uint32_t missedAudio = 0, missedAnalog = 0, missedMpu = 0;
uint32_t mpuErrors = 0;
bool mpuReady = false;
uint8_t captureState = 0; // 0=idle, 1=recording, 2=ready for next stage/download
uint8_t captureMode = 0;  // 1=audio only, 2=sensors only
bool audioComplete = false;
bool sensorsComplete = false;

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg); Wire.write(value);
  return Wire.endTransmission(true) == 0;
}

bool readMPU(int16_t &x, int16_t &y, int16_t &z) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  if (Wire.endTransmission(true) != 0) return false;
  if (Wire.requestFrom(MPU_ADDR, (size_t)6, true) != 6) return false;
  uint8_t d[6];
  for (int i = 0; i < 6; ++i) d[i] = Wire.read();
  x = (int16_t)(((uint16_t)d[0] << 8) | d[1]);
  y = (int16_t)(((uint16_t)d[2] << 8) | d[3]);
  z = (int16_t)(((uint16_t)d[4] << 8) | d[5]);
  return true;
}

bool initMPU() {
  if (!writeRegister(0x6B, 0x00)) return false;
  delay(100);
  if (!writeRegister(0x1C, 0x00)) return false; // +-2g
  if (!writeRegister(0x1A, 0x03)) return false; // DLPF
  if (!writeRegister(0x19, 0x04)) return false; // 200 Hz internal MPU output
  int16_t x, y, z;
  return readMPU(x, y, z);
}

// Python calls with +10 for AUDIO phase, -10 for SENSORS phase.
// Preserve audio buffer and its dropout statistics when beginning sensor phase.
int32_t startCapture(int32_t signedSeconds) {
  if (captureState == 1) return -2;
  if (signedSeconds == 0 || signedSeconds < -int32_t(MAX_SECONDS) ||
      signedSeconds > int32_t(MAX_SECONDS)) return -1;
  uint32_t seconds = signedSeconds > 0 ? uint32_t(signedSeconds) : uint32_t(-signedSeconds);
  if (seconds < 2) return -1;

  if (signedSeconds > 0) {
    // Starting audio begins a new complete session.
    captureMode = 1;
    audioComplete = false;
    sensorsComplete = false;
    targetAudio = seconds * AUDIO_HZ;
    targetAnalog = 0;
    targetMpu = 0;
    nAudio = nAnalog = nMpu = 0;
    missedAudio = missedAnalog = missedMpu = mpuErrors = 0;
  } else {
    if (!audioComplete || sensorsComplete) return -4;
    captureMode = 2;
    targetAnalog = seconds * ANALOG_HZ;
    targetMpu = seconds * MPU_HZ;
    nAnalog = nMpu = 0;
    missedAnalog = missedMpu = mpuErrors = 0;
  }
  secondsActive = seconds;
  startUs = micros();
  captureState = 1;
  return 0;
}

// Status slots are kept stable across phases:
// 0 protocol, 1 state, 2 audio slots, 3 analog slots, 4 MPU slots,
// 5 audio misses, 6 analog misses, 7 MPU misses, 8 MPU read errors,
// 9 MPU ready, 10 audio rate, 11 analog rate, 12 MPU rate,
// 13 active seconds, 14 current mode, 15 audio done, 16 sensors done.
std::array<int32_t, 41> captureStatus() {
  std::array<int32_t, 41> out = {};
  out[0] = PROTOCOL;
  out[1] = captureState;
  out[2] = nAudio; out[3] = nAnalog; out[4] = nMpu;
  out[5] = missedAudio; out[6] = missedAnalog;
  out[7] = missedMpu; out[8] = mpuErrors;
  out[9] = mpuReady ? 1 : 0;
  out[10] = AUDIO_HZ; out[11] = ANALOG_HZ; out[12] = MPU_HZ;
  out[13] = secondsActive; out[14] = captureMode;
  out[15] = audioComplete ? 1 : 0;
  out[16] = sensorsComplete ? 1 : 0;
  return out;
}

// Fetch only AFTER both phases complete. Each RPC response is 41 int32 values.
// cmd1: <=40 audio samples; cmd2: <=40 packed mic/piezo pairs;
// cmd3: <=13 MPU XYZ triples.
std::array<int32_t, 41> captureRead(int32_t cmd, int32_t start) {
  std::array<int32_t, 41> out = {};
  if (captureState != 2 || !audioComplete || !sensorsComplete) {
    out[0] = -3; return out;
  }
  if (start < 0) { out[0] = -1; return out; }
  uint32_t index = uint32_t(start);
  if (cmd == 1) {
    if (index >= targetAudio) return out;
    uint32_t count = targetAudio - index;
    if (count > 40) count = 40;
    out[0] = int32_t(count);
    for (uint32_t i = 0; i < count; ++i) out[1 + i] = audioRaw[index + i];
    return out;
  }
  if (cmd == 2) {
    if (index >= targetAnalog) return out;
    uint32_t count = targetAnalog - index;
    if (count > 40) count = 40;
    out[0] = int32_t(count);
    for (uint32_t i = 0; i < count; ++i) {
      uint32_t packed = (uint32_t(uint16_t(mic500[index + i])) << 16) |
                         uint32_t(uint16_t(piezo500[index + i]));
      out[1 + i] = int32_t(packed);
    }
    return out;
  }
  if (cmd == 3) {
    if (index >= targetMpu) return out;
    uint32_t count = targetMpu - index;
    if (count > 13) count = 13;
    out[0] = int32_t(count);
    for (uint32_t i = 0; i < count; ++i) {
      uint32_t j = 1 + 3 * i;
      out[j] = xRaw[index + i];
      out[j + 1] = yRaw[index + i];
      out[j + 2] = zRaw[index + i];
    }
    return out;
  }
  out[0] = -1; return out;
}

// Fast fixed-rate deadline arithmetic: 6 kHz = 3 samples per 500us.
// For 10s captures, elapsedUs * 3 fits into uint32_t.
void sampleAudio(uint32_t elapsedUs) {
  uint32_t due = elapsedUs * 3UL / 500UL + 1;
  if (due > targetAudio) due = targetAudio;
  if (due <= nAudio) return;
  while (nAudio + 1 < due) {
    audioRaw[nAudio++] = MISSING;
    ++missedAudio;
  }
  audioRaw[nAudio++] = int16_t(analogRead(MIC_PIN));
}

void sampleAnalog(uint32_t elapsedUs) {
  uint32_t due = elapsedUs / 2000UL + 1;
  if (due > targetAnalog) due = targetAnalog;
  if (due <= nAnalog) return;
  while (nAnalog + 1 < due) {
    mic500[nAnalog] = MISSING;
    piezo500[nAnalog] = MISSING;
    ++nAnalog; ++missedAnalog;
  }
  mic500[nAnalog] = int16_t(analogRead(MIC_PIN));
  piezo500[nAnalog] = int16_t(analogRead(PIEZO_PIN));
  ++nAnalog;
}

void sampleMpu(uint32_t elapsedUs) {
  uint32_t due = elapsedUs / 5000UL + 1;
  if (due > targetMpu) due = targetMpu;
  if (due <= nMpu) return;
  while (nMpu + 1 < due) {
    xRaw[nMpu] = yRaw[nMpu] = zRaw[nMpu] = MISSING;
    ++nMpu; ++missedMpu;
  }
  int16_t x, y, z;
  if (mpuReady && readMPU(x, y, z)) {
    xRaw[nMpu] = x; yRaw[nMpu] = y; zRaw[nMpu] = z;
  } else {
    xRaw[nMpu] = yRaw[nMpu] = zRaw[nMpu] = MISSING;
    ++mpuErrors;
  }
  ++nMpu;
}

void setup() {
  Bridge.begin();
  Wire.begin();
  Wire.setClock(400000);
  analogReadResolution(14);
  mpuReady = initMPU();
  Bridge.provide_safe("footstep_capture_start", startCapture);
  Bridge.provide_safe("footstep_capture_status", captureStatus);
  Bridge.provide_safe("footstep_capture_read", captureRead);
}

void loop() {
  if (captureState != 1) return;
  uint32_t elapsedUs = uint32_t(micros() - startUs);
  uint32_t totalUs = secondsActive * 1000000UL;
  if (elapsedUs >= totalUs) {
    if (captureMode == 1) {
      while (nAudio < targetAudio) { audioRaw[nAudio++] = MISSING; ++missedAudio; }
      audioComplete = true;
    } else if (captureMode == 2) {
      while (nAnalog < targetAnalog) {
        mic500[nAnalog] = piezo500[nAnalog] = MISSING;
        ++nAnalog; ++missedAnalog;
      }
      while (nMpu < targetMpu) {
        xRaw[nMpu] = yRaw[nMpu] = zRaw[nMpu] = MISSING;
        ++nMpu; ++missedMpu;
      }
      sensorsComplete = true;
    }
    captureState = 2;
    return;
  }
  if (captureMode == 1) {
    sampleAudio(elapsedUs);
  } else if (captureMode == 2) {
    sampleAnalog(elapsedUs);
    sampleMpu(elapsedUs);
  }
}
