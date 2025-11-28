/*
 * R307S Simple Serial Test for ESP32-S3
 * This code replaces SoftwareSerial with HardwareSerial
 * 
 * WIRING:
 * R307S VCC (Red)   -> ESP32 5V or 3.3V
 * R307S GND (Black) -> ESP32 GND
 * R307S TX (White)  -> ESP32 GPIO 16 (RX)
 * R307S RX (Green)  -> ESP32 GPIO 17 (TX)
 */

// For ESP32, use HardwareSerial instead of SoftwareSerial
HardwareSerial mySerial(1); // Use UART1

// Define the GPIO pins - Using GPIO 16 and 17 (safe for ESP32-S3)
#define RX_PIN 16  // Connect R307S TX (White wire) to GPIO 16
#define TX_PIN 17  // Connect R307S RX (Green wire) to GPIO 17

void setup() {
  Serial.begin(115200);  // Changed to 115200 for better performance
  
  // Initialize hardware serial with RX and TX pins
  mySerial.begin(57600, SERIAL_8N1, RX_PIN, TX_PIN);
  
  delay(2000);
  
  Serial.println("\n========================================");
  Serial.println("R307S Fingerprint Sensor Test");
  Serial.println("========================================");
  Serial.println("R307S test started");
  Serial.println("Sensor RX Pin (Green): GPIO " + String(TX_PIN));
  Serial.println("Sensor TX Pin (White): GPIO " + String(RX_PIN));
  Serial.println("========================================");
  Serial.println("\nWaiting for sensor data...");
}

void loop() {
  // Forward data from R307 sensor to Serial Monitor
  if (mySerial.available()) {
    Serial.write(mySerial.read());
  }
  
  // Forward data from Serial Monitor to R307 sensor
  if (Serial.available()) {
    mySerial.write(Serial.read());
  }
}
