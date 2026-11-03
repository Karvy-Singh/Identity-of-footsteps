
#include <Wire.h>
#include <Arduino_RouterBridge.h>

const uint8_t MPU_ADDR = 0x68;

bool readMPU(uint8_t reg, uint8_t *data, size_t count) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);

  // Finish the register selection
  int error = Wire.endTransmission(true);

  if (error != 0) {
    Monitor.print("Register select failed: ");
    Monitor.println(error);
    return false;
  }

  size_t received = Wire.requestFrom(MPU_ADDR, count, true);

  if (received != count) {
    Monitor.print("Read failed. Bytes received: ");
    Monitor.println((int)received);
    return false;
  }

  for (size_t i = 0; i < count; i++) {
    data[i] = Wire.read();
  }

  return true;
}

void setup() {
  Monitor.begin(9600);
  Wire.begin();
  delay(500);

  Monitor.println("Starting MPU6050 test");

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);
  Wire.write(0x00);

  int error = Wire.endTransmission();

  Monitor.print("Wake status: ");
  Monitor.println(error);

  delay(100);

  uint8_t id;

  if (readMPU(0x75, &id, 1)) {
    Monitor.print("WHO_AM_I: 0x");
    Monitor.println(String(id, HEX));
  }
}

void loop() {
  uint8_t data[14];

  if (!readMPU(0x3B, data, 14)) {
    delay(1000);
    return;
  }

  int16_t ax = (int16_t)((data[0] << 8) | data[1]);
  int16_t ay = (int16_t)((data[2] << 8) | data[3]);
  int16_t az = (int16_t)((data[4] << 8) | data[5]);

  int16_t gx = (int16_t)((data[8] << 8) | data[9]);
  int16_t gy = (int16_t)((data[10] << 8) | data[11]);
  int16_t gz = (int16_t)((data[12] << 8) | data[13]);

  Monitor.print("AX: ");
  Monitor.print(ax / 16384.0);
  Monitor.print(" AY: ");
  Monitor.print(ay / 16384.0);
  Monitor.print(" AZ: ");
  Monitor.println(az / 16384.0);

  Monitor.print("GX: ");
  Monitor.print(gx / 131.0);
  Monitor.print(" GY: ");
  Monitor.print(gy / 131.0);
  Monitor.print(" GZ: ");
  Monitor.println(gz / 131.0);

  delay(500);
}
