/*
 * R307S Fingerprint → Python Bridge (USB Serial) - IMPROVED VERSION
 * 
 * Features:
 * 1. Enrolls fingerprints with automatic timeouts (10 sec per step)
 * 2. Verifies fingerprints with detailed feedback
 * 3. Sends fingerprint matches to Python via Serial (JSON format)
 * 4. Power management with ACTIVATE/DEACTIVATE commands
 * 5. Auto-deactivates after 5 minutes of inactivity
 * 6. Detailed error messages and progress updates
 * 
 * Communication Protocol:
 * Python → ESP32 Commands:
 *   - ENROLL:ID - Enroll fingerprint in slot ID
 *   - DELETE:ID - Delete fingerprint from slot ID
 *   - COUNT - Get number of enrolled fingerprints
 *   - ACTIVATE - Turn on fingerprint scanning
 *   - DEACTIVATE - Turn off scanning (save power)
 *   - STATUS - Get sensor status
 *   - EMPTY - Delete all fingerprints
 * 
 * ESP32 → Python Responses (JSON):
 *   - {"type":"match","id":123,"confidence":95} - Fingerprint recognized
 *   - {"type":"nomatch","message":"..."} - Fingerprint not found
 *   - {"type":"enrolled","id":123,"success":true} - Enrollment success
 *   - {"type":"prompt","message":"Place finger"} - User instruction
 *   - {"type":"status","message":"..."} - Status update
 *   - {"type":"error","message":"..."} - Error occurred
 * 
 * Hardware:
 *   - ESP32-S3 board
 *   - R307S fingerprint sensor
 *   - RX_PIN = GPIO 16 (ESP32 RX ← Sensor TX)
 *   - TX_PIN = GPIO 17 (ESP32 TX → Sensor RX)
 *   - Baud: 115200 (USB), 57600 (Sensor)
 */

#include <Adafruit_Fingerprint.h>
#include <ArduinoJson.h>  // Install "ArduinoJson" library

#define RX_PIN 16
#define TX_PIN 17

HardwareSerial mySerial(1);
Adafruit_Fingerprint finger = Adafruit_Fingerprint(&mySerial);

bool sensorActive = false;  // Track sensor state
unsigned long lastActivityTime = 0;
const unsigned long AUTO_DEACTIVATE_TIMEOUT = 300000;  // 5 minutes

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  mySerial.begin(57600, SERIAL_8N1, RX_PIN, TX_PIN);
  
  Serial.println("{\"type\":\"status\",\"message\":\"R307S Fingerprint Bridge Started\"}");
  
  if (finger.verifyPassword()) {
    Serial.println("{\"type\":\"status\",\"message\":\"Sensor connected\",\"success\":true}");
    finger.getTemplateCount();
    
    StaticJsonDocument<200> doc;
    doc["type"] = "info";
    doc["capacity"] = finger.capacity;
    doc["templates"] = finger.templateCount;
    serializeJson(doc, Serial);
    Serial.println();
  } else {
    Serial.println("{\"type\":\"error\",\"message\":\"Sensor not found\"}");
  }
}

void loop() {
  // Check for commands from Python
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    processCommand(command);
  }
  
  // Only scan for fingerprints when active
  if (sensorActive) {
    int result = getFingerprintID();
    if (result > 0) {
      // Send fingerprint match to Python
      StaticJsonDocument<200> doc;
      doc["type"] = "match";
      doc["id"] = result;
      doc["confidence"] = finger.confidence;
      doc["timestamp"] = millis();
      serializeJson(doc, Serial);
      Serial.println();
      
      lastActivityTime = millis();
      delay(2000); // Prevent multiple reads
    }
    
    // Auto-deactivate after timeout
    if (millis() - lastActivityTime > AUTO_DEACTIVATE_TIMEOUT) {
      sensorActive = false;
      Serial.println("{\"type\":\"status\",\"message\":\"Auto-deactivated due to inactivity\"}");
    }
  }
  
  delay(50);  // Small delay to prevent overwhelming the sensor
}

void processCommand(String cmd) {
  if (cmd.startsWith("ENROLL:")) {
    int id = cmd.substring(7).toInt();
    enrollFingerprint(id);
  } 
  else if (cmd == "COUNT") {
    finger.getTemplateCount();
    StaticJsonDocument<200> doc;
    doc["type"] = "count";
    doc["templates"] = finger.templateCount;
    doc["capacity"] = finger.capacity;
    serializeJson(doc, Serial);
    Serial.println();
  }
  else if (cmd.startsWith("DELETE:")) {
    int id = cmd.substring(7).toInt();
    deleteFingerprint(id);
  }
  else if (cmd == "ACTIVATE") {
    sensorActive = true;
    lastActivityTime = millis();
    Serial.println("{\"type\":\"status\",\"message\":\"Sensor activated\",\"active\":true}");
  }
  else if (cmd == "DEACTIVATE") {
    sensorActive = false;
    Serial.println("{\"type\":\"status\",\"message\":\"Sensor deactivated\",\"active\":false}");
  }
  else if (cmd == "VERIFY") {
    sensorActive = true;
    lastActivityTime = millis();
    Serial.println("{\"type\":\"status\",\"message\":\"Place finger for verification\"}");
  }
  else if (cmd == "STATUS") {
    // Get sensor status
    StaticJsonDocument<200> doc;
    doc["type"] = "sensor_status";
    doc["active"] = sensorActive;
    doc["templates"] = finger.templateCount;
    doc["capacity"] = finger.capacity;
    doc["connected"] = true;
    serializeJson(doc, Serial);
    Serial.println();
  }
  else if (cmd == "EMPTY") {
    // Delete all fingerprints
    uint8_t p = finger.emptyDatabase();
    StaticJsonDocument<200> doc;
    doc["type"] = "empty";
    doc["success"] = (p == FINGERPRINT_OK);
    serializeJson(doc, Serial);
    Serial.println();
    if (p == FINGERPRINT_OK) {
      finger.getTemplateCount();
    }
  }
}

int getFingerprintID() {
  uint8_t p = finger.getImage();
  
  // No finger detected - return silently
  if (p == FINGERPRINT_NOFINGER) return -1;
  
  // Other errors - skip this read
  if (p != FINGERPRINT_OK) return -1;

  // Convert image to template
  p = finger.image2Tz();
  if (p != FINGERPRINT_OK) return -1;

  // Search for fingerprint match
  p = finger.fingerSearch();
  if (p == FINGERPRINT_OK) {
    // Match found!
    return finger.fingerID;
  } else if (p == FINGERPRINT_NOTFOUND) {
    // No match - send notification
    StaticJsonDocument<200> doc;
    doc["type"] = "nomatch";
    doc["message"] = "Fingerprint not recognized";
    serializeJson(doc, Serial);
    Serial.println();
    return -1;
  } else {
    // Search error
    return -1;
  }
}

void enrollFingerprint(int id) {
  Serial.println("{\"type\":\"status\",\"message\":\"Starting enrollment for ID " + String(id) + "\"}");
  
  // Step 1: Get first fingerprint image
  Serial.println("{\"type\":\"prompt\",\"message\":\"Place finger on sensor\"}");
  int p = -1;
  int timeout = 0;
  
  while (p != FINGERPRINT_OK && timeout < 100) {  // 10 second timeout
    p = finger.getImage();
    delay(100);
    timeout++;
    
    if (timeout % 20 == 0) {  // Send reminder every 2 seconds
      Serial.println("{\"type\":\"status\",\"message\":\"Waiting for finger...\"}");
    }
  }
  
  if (p != FINGERPRINT_OK) {
    Serial.println("{\"type\":\"error\",\"message\":\"Timeout waiting for finger\"}");
    return;
  }
  
  Serial.println("{\"type\":\"status\",\"message\":\"Finger detected, processing...\"}");
  
  // Convert image to template
  p = finger.image2Tz(1);
  if (p != FINGERPRINT_OK) {
    Serial.println("{\"type\":\"error\",\"message\":\"Image conversion failed - try again\"}");
    return;
  }
  
  Serial.println("{\"type\":\"status\",\"message\":\"First scan successful!\"}");
  Serial.println("{\"type\":\"prompt\",\"message\":\"Remove finger\"}");
  delay(2000);
  
  // Wait for finger to be removed
  p = 0;
  timeout = 0;
  while (p != FINGERPRINT_NOFINGER && timeout < 50) {  // 5 second timeout
    p = finger.getImage();
    delay(100);
    timeout++;
  }
  
  Serial.println("{\"type\":\"prompt\",\"message\":\"Place SAME finger again\"}");
  
  // Step 2: Get second fingerprint image
  p = -1;
  timeout = 0;
  while (p != FINGERPRINT_OK && timeout < 100) {  // 10 second timeout
    p = finger.getImage();
    delay(100);
    timeout++;
    
    if (timeout % 20 == 0) {  // Send reminder every 2 seconds
      Serial.println("{\"type\":\"status\",\"message\":\"Waiting for same finger again...\"}");
    }
  }
  
  if (p != FINGERPRINT_OK) {
    Serial.println("{\"type\":\"error\",\"message\":\"Timeout waiting for second scan\"}");
    return;
  }
  
  Serial.println("{\"type\":\"status\",\"message\":\"Second finger detected, processing...\"}");
  
  // Convert second image
  p = finger.image2Tz(2);
  if (p != FINGERPRINT_OK) {
    Serial.println("{\"type\":\"error\",\"message\":\"Second image conversion failed\"}");
    return;
  }
  
  Serial.println("{\"type\":\"status\",\"message\":\"Second scan successful!\"}");
  
  // Create fingerprint model
  Serial.println("{\"type\":\"status\",\"message\":\"Creating fingerprint model...\"}");
  p = finger.createModel();
  if (p != FINGERPRINT_OK) {
    if (p == FINGERPRINT_ENROLLMISMATCH) {
      Serial.println("{\"type\":\"error\",\"message\":\"Fingerprints did not match - use same finger!\"}");
    } else {
      Serial.println("{\"type\":\"error\",\"message\":\"Failed to create model - try again\"}");
    }
    return;
  }
  
  Serial.println("{\"type\":\"status\",\"message\":\"Model created, storing...\"}");
  
  // Store the model
  p = finger.storeModel(id);
  if (p == FINGERPRINT_OK) {
    Serial.println("{\"type\":\"status\",\"message\":\"Fingerprint stored successfully!\"}");
    
    StaticJsonDocument<200> doc;
    doc["type"] = "enrolled";
    doc["id"] = id;
    doc["success"] = true;
    doc["message"] = "Enrollment complete!";
    serializeJson(doc, Serial);
    Serial.println();
    
    // Update template count
    finger.getTemplateCount();
  } else if (p == FINGERPRINT_BADLOCATION) {
    Serial.println("{\"type\":\"error\",\"message\":\"Could not store in that location\"}");
  } else if (p == FINGERPRINT_FLASHERR) {
    Serial.println("{\"type\":\"error\",\"message\":\"Error writing to flash\"}");
  } else {
    Serial.println("{\"type\":\"error\",\"message\":\"Unknown error storing fingerprint\"}");
  }
}

void deleteFingerprint(int id) {
  uint8_t p = finger.deleteModel(id);
  
  StaticJsonDocument<200> doc;
  doc["type"] = "delete";
  doc["id"] = id;
  doc["success"] = (p == FINGERPRINT_OK);
  serializeJson(doc, Serial);
  Serial.println();
}
