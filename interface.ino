
#include <Arduino.h>

// http://arduino.cc/playground/Main/DHTLib
#include <dht.h>

// Digital Temperature and Humidity Sensor
#define DHT22_POWER         5
#define DHT22_PIN           6

#define OUTLET_A            10
#define OUTLET_B            11
#define OUTLET_C            12

#define FEEDBACK_A          7
#define FEEDBACK_B          8
#define FEEDBACK_C          9

#define REFUEL_BTN          2

#define DHT_READ_INTERVAL   2*1000

dht DHT;

char REFUEL = 'r';
float TEMPERATURE;
float HUMIDITY;
uint32_t dhtTimer = 0;

float fahrenheit(double celsius) {
  return (float) celsius * 1.8 + 32;
}

void resetDHT22() {
    digitalWrite(DHT22_POWER, LOW);
    delay(200);
    digitalWrite(DHT22_POWER, HIGH);
}

void readDHT22() {
    int chk = DHT.read22(DHT22_PIN);
    switch (chk)
    {
        case DHTLIB_OK:
            TEMPERATURE = fahrenheit(DHT.temperature);
            HUMIDITY = DHT.humidity;
            break;
        case DHTLIB_ERROR_CHECKSUM:
            Serial.println("DHT22 Checksum error,\t");
            resetDHT22();
            break;
        case DHTLIB_ERROR_TIMEOUT:
            Serial.println("DHT22 Time out error,\t");
            resetDHT22();
            break;
        default:
            Serial.println("DHT22 Unknown error,\t");
            resetDHT22();
            break;
    }
}

void feedback(uint8_t pin) {
    uint8_t value = digitalRead(pin);
    Serial.println(value);
}


void setup() {
    pinMode(DHT22_POWER, OUTPUT);
    digitalWrite(DHT22_POWER, HIGH);
    delay(50);

    pinMode(REFUEL_BTN, INPUT);

    pinMode(OUTLET_A, OUTPUT);
    pinMode(OUTLET_B, OUTPUT);
    pinMode(OUTLET_C, OUTPUT);

    digitalWrite(OUTLET_A, LOW);
    digitalWrite(OUTLET_B, LOW);
    digitalWrite(OUTLET_C, LOW);

    pinMode(FEEDBACK_A, INPUT);
    pinMode(FEEDBACK_B, INPUT);
    pinMode(FEEDBACK_C, INPUT);

    readDHT22();
    dhtTimer = millis();
    REFUEL = 'r';
    Serial.begin(57600);
}

void loop() {
    if (Serial.available()) {
        char code = Serial.read();
        switch(code) {
            case 'I':
                Serial.println('I');
                break;

            case 'H':
                Serial.println(HUMIDITY);
                break;

            case 'R':
                Serial.println(REFUEL);
                REFUEL = 'r';
                break;

            case 'F':
                Serial.println(TEMPERATURE);
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

            default:
                Serial.println('E');
                break;
        }
    }

    // There is too much line noise for external interrupts,
    // but this is surprisingly stable. All 3 consecutive
    // reads must be HIGH for the button to register pressed.
    bool pressed = true;
    for (uint8_t x=0; x<3;x++) {
        if (digitalRead(REFUEL_BTN) == LOW) {
            pressed = false;
            break;
        }
        delay(2);
    }
    if (pressed) {
        REFUEL = 'R';
    }
    delay(10);

    if (millis() - dhtTimer > DHT_READ_INTERVAL) {
        readDHT22();
        dhtTimer = millis();
    }
}
