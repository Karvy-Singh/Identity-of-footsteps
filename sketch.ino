
#include <Wire.h>
#include <Arduino_RouterBridge.h>
#include <array>
#include <stdint.h>

// Recording configuration
constexpr int CAPTURE_SECONDS = 15;
constexpr int ANALOG_RATE = 500;
constexpr int MPU_RATE = 200;

constexpr uint32_t CAPTURE_US =
    CAPTURE_SECONDS * 1000000UL;

constexpr uint32_t ANALOG_PERIOD_US =
    1000000UL / ANALOG_RATE;

constexpr uint32_t MPU_PERIOD_US =
    1000000UL / MPU_RATE;

constexpr int ANALOG_MAX =
    CAPTURE_SECONDS * ANALOG_RATE;

constexpr int MPU_MAX =
    CAPTURE_SECONDS * MPU_RATE;

constexpr int16_t MISSING = -32768;

constexpr uint8_t MPU_ADDR = 0x68;
constexpr int MIC_PIN = A0;
constexpr int PIEZO_PIN = A1;

// Actual timestamps and readings
uint32_t micTimes[ANALOG_MAX];
uint32_t piezoTimes[ANALOG_MAX];

int16_t micValues[ANALOG_MAX];
int16_t piezoValues[ANALOG_MAX];

uint32_t mpuTimes[MPU_MAX];
int16_t mpuX[MPU_MAX];
int16_t mpuY[MPU_MAX];
int16_t mpuZ[MPU_MAX];

// Recording state
volatile bool startRequested = false;
volatile int captureState = 0;

// 0 = idle
// 1 = recording
// 2 = finished

int analogCount = 0;
int mpuCount = 0;

uint32_t missedAnalog = 0;
uint32_t missedMPU = 0;
uint32_t mpuErrors = 0;
uint32_t adcErrors = 0;

bool mpuReady = false;

uint32_t captureStartUs = 0;
uint32_t nextAnalogUs = 0;
uint32_t nextMPUUs = 0;

// -----------------------------
// MPU6050 FUNCTIONS
// -----------------------------

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);

  return Wire.endTransmission(true) == 0;
}

bool readMPU(int16_t &x, int16_t &y, int16_t &z) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);

  // Working method for your UNO Q
  if (Wire.endTransmission(true) != 0) {
    return false;
  }

  if (Wire.requestFrom(
      MPU_ADDR, (size_t)6, true) != 6) {
    return false;
  }

  uint8_t d[6];

  for (int i = 0; i < 6; i++) {
    d[i] = Wire.read();
  }

  x = (int16_t)(((uint16_t)d[0] << 8) | d[1]);
  y = (int16_t)(((uint16_t)d[2] << 8) | d[3]);
  z = (int16_t)(((uint16_t)d[4] << 8) | d[5]);

  return true;
}

bool initializeMPU() {
  if (!writeRegister(0x6B, 0x00))
    return false;

  delay(100);

  // Accelerometer +/-2g
  if (!writeRegister(0x1C, 0x00))
    return false;

  // Digital low-pass filter
  if (!writeRegister(0x1A, 0x03))
    return false;

  // 200 Hz internal output
  if (!writeRegister(0x19, 0x04))
    return false;

  int16_t x, y, z;
  return readMPU(x, y, z);
}

// -----------------------------
// BRIDGE COMMUNICATION
// -----------------------------
// cmd 0: status
// cmd 1: start recording
// cmd 2: mic + piezo data
// cmd 3: MPU6050 data
//
// Each response contains 25 integers.
// Download only after recording.

std::array<int32_t, 25> footstepRPC(
    int cmd, int start) {

  std::array<int32_t, 25> out = {};

  if (cmd == 0) {
    out[0] = captureState;
    out[1] = analogCount;
    out[2] = mpuCount;
    out[3] = missedAnalog;
    out[4] = missedMPU;
    out[5] = mpuErrors;
    out[6] = adcErrors;
    out[7] = mpuReady ? 1 : 0;
    out[8] = CAPTURE_SECONDS;
    out[9] = ANALOG_RATE;
    out[10] = MPU_RATE;
    return out;
  }

  if (cmd == 1) {
    if (captureState != 1 && !startRequested) {
      startRequested = true;
      out[0] = 1;
    }
    return out;
  }

  if (captureState != 2 || start < 0) {
    return out;
  }

  // Mic and piezo: 6 pairs per response
  // timeMic, mic, timePiezo, piezo
  if (cmd == 2) {
    if (start >= analogCount) return out;

    int count = analogCount - start;
    if (count > 6) count = 6;

    out[0] = count;

    for (int i = 0; i < count; i++) {
      int j = 1 + 4 * i;
      int n = start + i;

      out[j] = micTimes[n];
      out[j + 1] = micValues[n];
      out[j + 2] = piezoTimes[n];
      out[j + 3] = piezoValues[n];
    }

    return out;
  }

  // MPU6050: 6 frames per response
  // time, X, Y, Z
  if (cmd == 3) {
    if (start >= mpuCount) return out;

    int count = mpuCount - start;
    if (count > 6) count = 6;

    out[0] = count;

    for (int i = 0; i < count; i++) {
      int j = 1 + 4 * i;
      int n = start + i;

      out[j] = mpuTimes[n];
      out[j + 1] = mpuX[n];
      out[j + 2] = mpuY[n];
      out[j + 3] = mpuZ[n];
    }
  }

  return out;
}

// -----------------------------
// START RECORDING
// -----------------------------

void beginCapture() {
  startRequested = false;
  captureState = 0;

  analogCount = 0;
  mpuCount = 0;

  missedAnalog = 0;
  missedMPU = 0;
  mpuErrors = 0;
  adcErrors = 0;

  mpuReady = initializeMPU();

  captureStartUs = micros();
  nextAnalogUs = 0;
  nextMPUUs = 0;

  captureState = 1;
}

// -----------------------------
// SETUP
// -----------------------------

void setup() {
  Bridge.begin();
  Wire.begin();

  analogReadResolution(14);

  Bridge.provide_safe(
    "footstep_rpc", footstepRPC
  );
}

// -----------------------------
// MAIN LOOP
// -----------------------------

void loop() {
  if (startRequested && captureState != 1) {
    beginCapture();
  }

  if (captureState != 1) {
    delay(1);
    return;
  }

  uint32_t elapsed =
      (uint32_t)(micros() - captureStartUs);

  if (elapsed >= CAPTURE_US) {
    captureState = 2;
    return;
  }

  // ---------------------------
  // MPU6050: target 200 Hz
  // ---------------------------

  if (elapsed >= nextMPUUs) {
    if (mpuCount < MPU_MAX) {
      uint32_t t = micros() - captureStartUs;

      int16_t x, y, z;

      mpuTimes[mpuCount] = t;

      if (mpuReady && readMPU(x, y, z)) {
        mpuX[mpuCount] = x;
        mpuY[mpuCount] = y;
        mpuZ[mpuCount] = z;
      } else {
        mpuX[mpuCount] = MISSING;
        mpuY[mpuCount] = MISSING;
        mpuZ[mpuCount] = MISSING;
        mpuErrors++;
      }

      mpuCount++;
    }

    nextMPUUs += MPU_PERIOD_US;

    uint32_t after = micros() - captureStartUs;

    if (after >= nextMPUUs) {
      uint32_t skipped =
          (after - nextMPUUs) / MPU_PERIOD_US + 1;

      missedMPU += skipped;
      nextMPUUs += skipped * MPU_PERIOD_US;
    }
  }

  // ---------------------------
  // MIC AND PIEZO: target 500 Hz
  // ---------------------------

  elapsed = micros() - captureStartUs;

  if (elapsed < CAPTURE_US &&
      elapsed >= nextAnalogUs) {

    if (analogCount < ANALOG_MAX) {
      uint32_t tMic =
          micros() - captureStartUs;

      int mic = analogRead(MIC_PIN);

      uint32_t tPiezo =
          micros() - captureStartUs;

      int piezo = analogRead(PIEZO_PIN);

      micTimes[analogCount] = tMic;
      piezoTimes[analogCount] = tPiezo;

      if (mic >= 0 && mic <= 16383) {
        micValues[analogCount] = mic;
      } else {
        micValues[analogCount] = MISSING;
        adcErrors++;
      }

      if (piezo >= 0 && piezo <= 16383) {
        piezoValues[analogCount] = piezo;
      } else {
        piezoValues[analogCount] = MISSING;
        adcErrors++;
      }

      analogCount++;
    }

    nextAnalogUs += ANALOG_PERIOD_US;

    uint32_t after = micros() - captureStartUs;

    if (after >= nextAnalogUs) {
      uint32_t skipped =
          (after - nextAnalogUs) /
          ANALOG_PERIOD_US + 1;

      missedAnalog += skipped;
      nextAnalogUs += skipped * ANALOG_PERIOD_US;
    }
  }
}
