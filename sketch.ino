
#include <Wire.h>
#include <Arduino_RouterBridge.h>
#include <array>
#include <stdint.h>

// ===================================
// RECORDING SETTINGS
// ===================================

constexpr int CAPTURE_SECONDS = 2;

constexpr int MIC_RATE = 4000;
constexpr int PIEZO_RATE = 1000;
constexpr int MPU_RATE = 200;

constexpr uint32_t MIC_US = 250;
constexpr uint32_t PIEZO_US = 1000;
constexpr uint32_t MPU_US = 5000;

constexpr uint32_t DURATION_US =
    CAPTURE_SECONDS * 1000000UL;

constexpr int MIC_N = MIC_RATE * CAPTURE_SECONDS;
constexpr int PIEZO_N = PIEZO_RATE * CAPTURE_SECONDS;
constexpr int MPU_N = MPU_RATE * CAPTURE_SECONDS;

constexpr int16_t MISSING = -32768;
constexpr uint8_t MPU_ADDR = 0x68;

// ===================================
// SENSOR DATA ARRAYS
// ===================================

int16_t micData[MIC_N];
int16_t piezoData[PIEZO_N];

int16_t mpuX[MPU_N];
int16_t mpuY[MPU_N];
int16_t mpuZ[MPU_N];

// ===================================
// STATE
// ===================================

bool startRequested = false;
bool sensorReady = false;

// 0 = idle
// 1 = recording
// 2 = finished

int captureState = 0;

int micCount = 0;
int piezoCount = 0;
int mpuCount = 0;

uint32_t missedMic = 0;
uint32_t missedPiezo = 0;
uint32_t missedMPU = 0;
uint32_t mpuErrors = 0;

uint32_t captureStartUs = 0;

// ===================================
// MPU6050 FUNCTIONS
// ===================================

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);

  return Wire.endTransmission(true) == 0;
}

bool readMPU(int16_t &ax, int16_t &ay, int16_t &az) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);

  // Method that worked on your UNO Q
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

  ax = (int16_t)(((uint16_t)d[0] << 8) | d[1]);
  ay = (int16_t)(((uint16_t)d[2] << 8) | d[3]);
  az = (int16_t)(((uint16_t)d[4] << 8) | d[5]);

  return true;
}

bool initializeMPU() {
  if (!writeRegister(0x6B, 0x00)) return false;

  delay(100);

  // Accelerometer +/- 2g
  if (!writeRegister(0x1C, 0x00)) return false;

  // Low-pass filter
  if (!writeRegister(0x1A, 0x03)) return false;

  // MPU6050 internal 200 Hz sampling
  if (!writeRegister(0x19, 0x04)) return false;

  int16_t ax, ay, az;
  return readMPU(ax, ay, az);
}

// ===================================
// BRIDGE FUNCTION
// ===================================

// cmd = 0 : get status
// cmd = 1 : start recording
// cmd = 2 : microphone data
// cmd = 3 : piezo data
// cmd = 4 : MPU data

std::array<int32_t, 41> footstepRPC(
    int cmd, int start) {

  std::array<int32_t, 41> result = {};

  // STATUS
  if (cmd == 0) {
    result[0] = captureState;
    result[1] = micCount;
    result[2] = piezoCount;
    result[3] = mpuCount;
    result[4] = missedMic;
    result[5] = missedPiezo;
    result[6] = missedMPU;
    result[7] = mpuErrors;
    result[8] = sensorReady ? 1 : 0;
    result[9] = CAPTURE_SECONDS;

    return result;
  }

  // START
  if (cmd == 1) {
    if (captureState != 1 && !startRequested) {
      startRequested = true;
      result[0] = 1;
    }

    return result;
  }

  // Downloads only after recording
  if (captureState != 2 || start < 0) {
    return result;
  }

  // MICROPHONE / PIEZO
  if (cmd == 2 || cmd == 3) {
    int total = (cmd == 2) ? micCount : piezoCount;

    if (start >= total) return result;

    int count = total - start;
    if (count > 40) count = 40;

    result[0] = count;

    for (int i = 0; i < count; i++) {
      result[i + 1] = (cmd == 2)
        ? micData[start + i]
        : piezoData[start + i];
    }

    return result;
  }

  // MPU6050: 10 XYZ readings per block
  if (cmd == 4) {
    if (start >= mpuCount) return result;

    int frames = mpuCount - start;
    if (frames > 10) frames = 10;

    result[0] = frames;

    for (int i = 0; i < frames; i++) {
      int j = 1 + i * 3;

      result[j] = mpuX[start + i];
      result[j + 1] = mpuY[start + i];
      result[j + 2] = mpuZ[start + i];
    }
  }

  return result;
}

// ===================================
// START CAPTURE
// ===================================

void beginCapture() {
  startRequested = false;
  captureState = 0;

  micCount = 0;
  piezoCount = 0;
  mpuCount = 0;

  missedMic = 0;
  missedPiezo = 0;
  missedMPU = 0;
  mpuErrors = 0;

  sensorReady = initializeMPU();

  captureStartUs = micros();
  captureState = 1;
}

// ===================================
// FINISH CAPTURE
// ===================================

void finishCapture() {
  while (micCount < MIC_N) {
    micData[micCount++] = MISSING;
    missedMic++;
  }

  while (piezoCount < PIEZO_N) {
    piezoData[piezoCount++] = MISSING;
    missedPiezo++;
  }

  while (mpuCount < MPU_N) {
    mpuX[mpuCount] = MISSING;
    mpuY[mpuCount] = MISSING;
    mpuZ[mpuCount] = MISSING;

    mpuCount++;
    missedMPU++;
  }

  captureState = 2;
}

// ===================================
// SETUP
// ===================================

void setup() {
  Bridge.begin();
  Wire.begin();

  analogReadResolution(14);

  // Only one Bridge function
  Bridge.provide_safe("footstep_rpc", footstepRPC);
}

// ===================================
// MAIN LOOP
// ===================================

void loop() {

  if (startRequested && captureState != 1) {
    beginCapture();
  }

  if (captureState != 1) {
    return;
  }

  uint32_t elapsed =
      (uint32_t)(micros() - captureStartUs);

  if (elapsed >= DURATION_US) {
    finishCapture();
    return;
  }

  // MICROPHONE 4000 Hz
  uint32_t micSlot = elapsed / MIC_US;

  if (micSlot >= (uint32_t)micCount &&
      micCount < MIC_N) {

    while ((uint32_t)micCount < micSlot) {
      micData[micCount++] = MISSING;
      missedMic++;
    }

    micData[micCount++] =
        (int16_t)analogRead(A0);
  }

  // PIEZO 1000 Hz
  uint32_t piezoSlot = elapsed / PIEZO_US;

  if (piezoSlot >= (uint32_t)piezoCount &&
      piezoCount < PIEZO_N) {

    while ((uint32_t)piezoCount < piezoSlot) {
      piezoData[piezoCount++] = MISSING;
      missedPiezo++;
    }

    piezoData[piezoCount++] =
        (int16_t)analogRead(A2);
  }

  // MPU6050 200 Hz
  uint32_t mpuSlot = elapsed / MPU_US;

  if (mpuSlot >= (uint32_t)mpuCount &&
      mpuCount < MPU_N) {

    while ((uint32_t)mpuCount < mpuSlot) {
      mpuX[mpuCount] = MISSING;
      mpuY[mpuCount] = MISSING;
      mpuZ[mpuCount] = MISSING;

      mpuCount++;
      missedMPU++;
    }

    int16_t ax, ay, az;

    if (sensorReady && readMPU(ax, ay, az)) {
      mpuX[mpuCount] = ax;
      mpuY[mpuCount] = ay;
      mpuZ[mpuCount] = az;
    } else {
      mpuX[mpuCount] = MISSING;
      mpuY[mpuCount] = MISSING;
      mpuZ[mpuCount] = MISSING;
      mpuErrors++;
    }

    mpuCount++;
  }
}
