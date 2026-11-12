
#include <Arduino_RouterBridge.h>

const int MIC_PIN = A0;

void setup() {
  Monitor.begin(9600);
  analogReadResolution(14);

  Monitor.println("SEN0487 Microphone Test");
}

void loop() {
  int minValue = 16383;
  int maxValue = 0;
  long total = 0;
  int count = 0;

  unsigned long start = millis();

  // Measure sound for 250 milliseconds
  while (millis() - start < 250) {
    int value = analogRead(MIC_PIN);

    if (value < minValue) minValue = value;
    if (value > maxValue) maxValue = value;

    total += value;
    count++;
  }

  int range = maxValue - minValue;
  float average = (float)total / count;

  Monitor.print("Average: ");
  Monitor.print(average);

  Monitor.print(" Min: ");
  Monitor.print(minValue);

  Monitor.print(" Max: ");
  Monitor.print(maxValue);

  Monitor.print(" Range: ");
  Monitor.println(range);

  delay(100);
}
