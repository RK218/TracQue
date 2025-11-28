/*
 * ESP32-S3 WROOM-1 - Simple Example
 * 
 * This example demonstrates:
 * - Built-in LED blinking
 * - Serial communication
 * - Basic GPIO control
 */

// Define LED pin (ESP32-S3 usually has built-in LED on GPIO48 or GPIO2)
// Adjust this based on your specific board
#define LED_PIN 2  // Change to 48 if GPIO2 doesn't work

void setup() {
  // Initialize serial communication at 115200 baud
  Serial.begin(115200);
  
  // Wait for USB CDC to be ready (ESP32-S3 specific)
  // This prevents disconnect issues
  delay(2000);
  
  // Wait for serial monitor to connect (optional, but helpful)
  while(!Serial && millis() < 5000) {
    delay(100);
  }
  
  Serial.println("========================================");
  Serial.println("ESP32-S3 WROOM-1 - Simple Example");
  Serial.println("========================================");
  Serial.println("Board: ESP32-S3 WROOM-1");
  Serial.println("Starting...");
  Serial.println("========================================");
  
  // Configure LED pin as output
  pinMode(LED_PIN, OUTPUT);
  
  Serial.println("Setup complete!");
  Serial.println("Board should remain connected now!");
}

void loop() {
  // Turn LED ON
  digitalWrite(LED_PIN, HIGH);
  Serial.println("*** LED: ON ***");
  delay(1000);  // Wait 1 second
  
  // Turn LED OFF
  digitalWrite(LED_PIN, LOW);
  Serial.println("*** LED: OFF ***");
  delay(1000);  // Wait 1 second
  
  // Print system info every cycle
  Serial.println("========================================");
  Serial.print("Free Heap: ");
  Serial.print(ESP.getFreeHeap());
  Serial.println(" bytes");
  
  Serial.print("Uptime: ");
  Serial.print(millis() / 1000);
  Serial.println(" seconds");
  
  Serial.print("Loop count: ");
  static int loopCount = 0;
  Serial.println(++loopCount);
  Serial.println("========================================\n");
}
