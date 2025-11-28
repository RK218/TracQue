/*
 * R307S Fingerprint Sensor Test
 * 
 * This sketch tests if the R307S fingerprint sensor is connected and working
 * 
 * Wiring for ESP32-S3:
 * R307S VCC (Red)    -> ESP32 5V or 3.3V
 * R307S GND (Black)  -> ESP32 GND
 * R307S TX (White)   -> ESP32 GPIO 16 (RX)
 * R307S RX (Green)   -> ESP32 GPIO 17 (TX)
 */

#include <Adafruit_Fingerprint.h>

// Define the serial pins for R307S sensor
// ESP32-S3 UART1 pins - GPIO 16 and 17 are safe to use
#define RX_PIN 16  // Connect to R307S TX (White wire)
#define TX_PIN 17  // Connect to R307S RX (Green wire)

// Create a hardware serial object for the sensor
HardwareSerial mySerial(1);  // Using UART1

// Create fingerprint object
Adafruit_Fingerprint finger = Adafruit_Fingerprint(&mySerial);

void setup() {
  // Start the main serial for debugging
  Serial.begin(115200);
  delay(2000);
  
  while(!Serial && millis() < 5000);
  
  Serial.println("\n\n========================================");
  Serial.println("R307S Fingerprint Sensor Test");
  Serial.println("========================================");
  
  // Start the sensor serial
  mySerial.begin(57600, SERIAL_8N1, RX_PIN, TX_PIN);
  
  Serial.println("Initializing R307S sensor...");
  delay(500);
  
  // Check if sensor is connected
  if (finger.verifyPassword()) {
    Serial.println("✓ R307S Fingerprint sensor found!");
    Serial.println("========================================");
    
    // Get sensor parameters
    finger.getParameters();
    
    Serial.println("\nSensor Information:");
    Serial.print("  Status register: 0x");
    Serial.println(finger.status_reg, HEX);
    Serial.print("  System ID: 0x");
    Serial.println(finger.system_id, HEX);
    Serial.print("  Capacity: ");
    Serial.println(finger.capacity);
    Serial.print("  Security level: ");
    Serial.println(finger.security_level);
    Serial.print("  Device address: 0x");
    Serial.println(finger.device_addr, HEX);
    Serial.print("  Packet length: ");
    Serial.println(finger.packet_len);
    Serial.print("  Baud rate: ");
    Serial.println(finger.baud_rate);
    
    Serial.println("\n========================================");
    Serial.println("✓ SENSOR IS WORKING CORRECTLY!");
    Serial.println("========================================");
    Serial.println("\nYou can now:");
    Serial.println("1. Enroll fingerprints");
    Serial.println("2. Verify fingerprints");
    Serial.println("3. Check template count");
    
  } else {
    Serial.println("✗ Sensor NOT found!");
    Serial.println("\nTroubleshooting:");
    Serial.println("========================================");
    Serial.println("1. Check wiring:");
    Serial.println("   R307S VCC (Red)   -> ESP32 5V or 3.3V");
    Serial.println("   R307S GND (Black) -> ESP32 GND");
    Serial.println("   R307S TX (White)  -> ESP32 GPIO " + String(RX_PIN) + " (RX)");
    Serial.println("   R307S RX (Green)  -> ESP32 GPIO " + String(TX_PIN) + " (TX)");
    Serial.println("\n2. Check power supply (sensor needs stable power)");
    Serial.println("3. Try different baud rate (9600 instead of 57600)");
    Serial.println("4. Check if sensor LED blinks when powered");
    Serial.println("5. Make sure sensor is R307S (not just R307)");
    Serial.println("========================================");
  }
}

void loop() {
  // Get template count
  static unsigned long lastCheck = 0;
  
  if (millis() - lastCheck > 5000) {  // Every 5 seconds
    lastCheck = millis();
    
    Serial.println("\n--- Sensor Status ---");
    Serial.print("Templates stored: ");
    Serial.println(finger.templateCount);
    
    Serial.println("\nPlace finger on sensor to test detection...");
    
    // Try to detect a finger
    int p = finger.getImage();
    if (p == FINGERPRINT_OK) {
      Serial.println("✓ Finger detected on sensor!");
    } else if (p == FINGERPRINT_NOFINGER) {
      Serial.println("  No finger detected");
    } else {
      Serial.println("  Error reading sensor");
    }
  }
}
