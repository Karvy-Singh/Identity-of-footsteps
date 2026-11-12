// Arduino UNO Q — continuous three-sensor acquisition for live ML.
// SEN0487 microphone A0, protected/bias-conditioned piezo A1,
// MPU6050 SDA/SCL (0x68). Readings are streamed in Bridge batches.
// Nominal rates match the previously trained Harsh/Karvy model:
//   microphone 500 Hz; piezo 500 Hz; MPU6050 200 Hz.
// Sampling is best-effort, NOT hardware-timer/DMA guaranteed.

#include <Wire.h>
#include <Arduino_RouterBridge.h>
#include <array>
#include <stdint.h>

constexpr int MIC_PIN = A0;
constexpr int PIEZO_PIN = A1;
constexpr uint8_t MPU_ADDR = 0x68;
constexpr uint32_t ANALOG_PERIOD_US = 2000;  // 500 Hz
constexpr uint32_t MPU_PERIOD_US = 5000;     // 200 Hz
constexpr uint32_t ANALOG_RATE = 500;
constexpr uint32_t MPU_RATE = 200;
constexpr uint32_t RING_SECONDS = 8;
constexpr uint32_t ANALOG_RING = ANALOG_RATE * RING_SECONDS;
constexpr uint32_t MPU_RING = MPU_RATE * RING_SECONDS;
constexpr int16_t MISSING = -32768;

// 25.6 kB of buffers, continually reused (no 15-second memory cap).
int16_t micRing[ANALOG_RING];
int16_t piezoRing[ANALOG_RING];
int16_t xRing[MPU_RING];
int16_t yRing[MPU_RING];
int16_t zRing[MPU_RING];

uint32_t nextAnalogDue = 0;
uint32_t nextMpuDue = 0;
uint32_t analogProduced = 0; // absolute sample slots since startup
uint32_t mpuProduced = 0;
uint32_t missedAnalog = 0;
uint32_t missedMpu = 0;
uint32_t mpuErrors = 0;
bool mpuReady = false;

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);
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

bool initializeMPU() {
  if (!writeRegister(0x6B, 0x00)) return false;
  delay(100);
  if (!writeRegister(0x1C, 0x00)) return false; // +/- 2g
  if (!writeRegister(0x1A, 0x03)) return false; // DLPF
  if (!writeRegister(0x19, 0x04)) return false; // 200 Hz output
  int16_t x, y, z;
  return readMPU(x, y, z);
}

// The 16-bit signed encoding uses -32768 for a missing deadline.
void writeAnalog(int16_t mic, int16_t piezo) {
  uint32_t k = analogProduced % ANALOG_RING;
  micRing[k] = mic;
  piezoRing[k] = piezo;
  ++analogProduced;
}

void writeMpu(int16_t x, int16_t y, int16_t z) {
  uint32_t k = mpuProduced % MPU_RING;
  xRing[k] = x;
  yRing[k] = y;
  zRing[k] = z;
  ++mpuProduced;
}

// A single RPC method was already validated on your UNO Q.
// cmd 0: status
// cmd 2: up to 40 analog pairs, mic packed in upper 16 bits,
//        piezo in lower 16 bits (both signed 16-bit).
// cmd 3: up to 13 MPU frames, with three signed values per frame.
// start: absolute sequence index, not a ring-array offset.
// out[0]: count, 0=no data yet, -2=buffer overrun, -1=bad request.
std::array<int32_t, 41> liveRPC(int cmd, int start) {
  std::array<int32_t, 41> out = {};

  if (cmd == 0) {
    out[0] = 2026; // protocol marker
    out[1] = (int32_t)analogProduced;
    out[2] = (int32_t)mpuProduced;
    out[3] = (int32_t)missedAnalog;
    out[4] = (int32_t)missedMpu;
    out[5] = (int32_t)mpuErrors;
    out[6] = mpuReady ? 1 : 0;
    out[7] = (int32_t)ANALOG_RATE;
    out[8] = (int32_t)MPU_RATE;
    out[9] = (int32_t)ANALOG_RING;
    out[10] = (int32_t)MPU_RING;
    return out;
  }

  if (start < 0) {
    out[0] = -1;
    return out;
  }

  if (cmd == 2) {
    uint32_t current = analogProduced;
    uint32_t earliest = current > ANALOG_RING ? current - ANALOG_RING : 0;
    uint32_t wanted = (uint32_t)start;
    if (wanted < earliest) {
      out[0] = -2;
      out[1] = (int32_t)earliest;
      out[2] = (int32_t)current;
      return out;
    }
    uint32_t count = wanted >= current ? 0 : current - wanted;
    if (count > 40) count = 40;
    out[0] = (int32_t)count;
    for (uint32_t i = 0; i < count; ++i) {
      uint32_t k = (wanted + i) % ANALOG_RING;
      uint32_t packed =
          (uint32_t(uint16_t(micRing[k])) << 16) |
          uint32_t(uint16_t(piezoRing[k]));
      out[1 + i] = (int32_t)packed;
    }
    return out;
  }

  if (cmd == 3) {
    uint32_t current = mpuProduced;
    uint32_t earliest = current > MPU_RING ? current - MPU_RING : 0;
    uint32_t wanted = (uint32_t)start;
    if (wanted < earliest) {
      out[0] = -2;
      out[1] = (int32_t)earliest;
      out[2] = (int32_t)current;
      return out;
    }
    uint32_t count = wanted >= current ? 0 : current - wanted;
    if (count > 13) count = 13;
    out[0] = (int32_t)count;
    for (uint32_t i = 0; i < count; ++i) {
      uint32_t k = (wanted + i) % MPU_RING;
      uint32_t j = 1 + 3 * i;
      out[j] = xRing[k];
      out[j + 1] = yRing[k];
      out[j + 2] = zRing[k];
    }
    return out;
  }

  out[0] = -1;
  return out;
}

void setup() {
  Bridge.begin();
  Wire.begin();
  analogReadResolution(14);
  mpuReady = initializeMPU();
  Bridge.provide_safe("footstep_live_rpc", liveRPC);
  nextAnalogDue = micros();
  nextMpuDue = nextAnalogDue;
}

void loop() {
  // micros() wraparound-safe clock comparison (provided lag < 35 min).
  uint32_t now = micros();
  int32_t analogLag = (int32_t)(now - nextAnalogDue);
  if (analogLag >= 0) {
    uint32_t missed = uint32_t(analogLag) / ANALOG_PERIOD_US;
    // Advance the scheduler; missed deadlines remain visible as MISSING.
    for (uint32_t i = 0; i < missed; ++i) {
      writeAnalog(MISSING, MISSING);
    }
    missedAnalog += missed;
    nextAnalogDue += (missed + 1) * ANALOG_PERIOD_US;
    int mic = analogRead(MIC_PIN);
    int piezo = analogRead(PIEZO_PIN);
    writeAnalog((int16_t)mic, (int16_t)piezo);
  }

  now = micros();
  int32_t mpuLag = (int32_t)(now - nextMpuDue);
  if (mpuLag >= 0) {
    uint32_t missed = uint32_t(mpuLag) / MPU_PERIOD_US;
    for (uint32_t i = 0; i < missed; ++i) {
      writeMpu(MISSING, MISSING, MISSING);
    }
    missedMpu += missed;
    nextMpuDue += (missed + 1) * MPU_PERIOD_US;
    int16_t x, y, z;
    if (mpuReady && readMPU(x, y, z)) {
      writeMpu(x, y, z);
    } else {
      writeMpu(MISSING, MISSING, MISSING);
      ++mpuErrors;
    }
  }
}
