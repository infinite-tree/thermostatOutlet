
#include <Arduino.h>

// http://arduino.cc/playground/Main/DHTLib
#include <dht.h>

// Digital Temperature and Humidity Sensor
#define DHT22_PIN           6
#define OUTLET_A            10
#define OUTLET_B            11
#define OUTLET_C            12

#define FEEDBACK_A          7
#define FEEDBACK_B          8
#define FEEDBACK_C          9

dht DHT;


float fahrenheit(double celsius) {
  return (float) celsius * 1.8 + 32;
}

void readDHT22() {
    float value = 0.0;
    int chk = DHT.read22(DHT22_PIN);
    switch (chk)
    {
        case DHTLIB_OK:
            value = fahrenheit(DHT.temperature);
            Serial.println(value);
            break;
        case DHTLIB_ERROR_CHECKSUM:
            Serial.println("DHT22 Checksum error,\t");
            break;
        case DHTLIB_ERROR_TIMEOUT:
            Serial.println("DHT22 Time out error,\t");
            break;
        default:
            Serial.println("DHT22 Unknown error,\t");
            break;
    }
}

void feedback(uint8_t pin) {
    uint8_t value = digitalRead(pin);
    Serial.println(value);
}

void setup() {
    pinMode(OUTLET_A, OUTPUT);
    pinMode(OUTLET_B, OUTPUT);
    pinMode(OUTLET_C, OUTPUT);

    digitalWrite(OUTLET_A, LOW);
    digitalWrite(OUTLET_B, LOW);
    digitalWrite(OUTLET_C, LOW);

    pinMode(FEEDBACK_A, INPUT);
    pinMode(FEEDBACK_B, INPUT);
    pinMode(FEEDBACK_C, INPUT);

    Serial.begin(57600);

}

void loop() {
    if (Serial.available()) {
        char code = Serial.read();
        switch(code) {
            case 'F':
                readDHT22();
                break;

            // Outlet controls
            case 'A':
                digitalWrite(OUTLET_A, HIGH);
                Serial.println('A');
                break;
            case 'a':
                digitalWrite(OUTLET_A, LOW);
                Serial.println('a');
                break;
            case 'B':
                digitalWrite(OUTLET_B, HIGH);
                Serial.println('B');
                break;
            case 'b':
                digitalWrite(OUTLET_B, LOW);
                Serial.println('b');
                break;
            case 'C':
                digitalWrite(OUTLET_C, HIGH);
                Serial.println('C');
                break;
            case 'c':
                digitalWrite(OUTLET_C, LOW);
                Serial.println('c');
                break;

            // Feedback sensors
            case '1':
                feedback(FEEDBACK_A);
                break;
            case '2':
                feedback(FEEDBACK_B);
                break;
            case '3':
                feedback(FEEDBACK_C);
                break;
        }
    }
    delay(100);
}