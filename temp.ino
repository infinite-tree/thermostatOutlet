

// http://arduino.cc/playground/Main/DHTLib
#include <dht.h>

// Digital Temperature and Humidity Sensor
#define DHT22_PIN           6


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


void setup() {
    Serial.begin(57600);

}

void loop() {
    if (Serial.available()) {
        char code = Serial.read();
        if (code == 'F') {
            readDHT22();
        }
    }
    delay(100);
}