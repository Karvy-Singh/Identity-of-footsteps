
#include <Arduino_RouterBridge.h>

const int PIEZO_PIN = A1;

void setup() {
  Monitor.begin(9600);
  analogReadResolution(14);

  Monitor.println("PIEZO TEST STARTED");
}

void loop() {
  int minValue = 16383;
  int maxValue = 0;

  long total = 0;
  int count = 0;

  unsigned long startTime = millis();

  // Collect readings for 250 ms
  while (millis() - startTime < 250) {

    int value = analogRead(PIEZO_PIN);

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
