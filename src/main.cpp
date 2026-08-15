#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <DW1000.h>
#include <SPI.h>

// WIFI DETAILS
const char* ssid = "Your_Laptop_Hotspot_Name";  // enter wifi or hotspot name here
const char* password = "Your_Hotspot_Password"; // enter the wifi or hotspot password here

// Destination (Laptop) IP and Port for UDP
IPAddress remoteIP(192, 168, 137, 1); // Enter your own laptop IP here in case of laptop hotspot
unsigned int remotePort = 4210; // Enter port for UDP communication

WiFiUDP udp; // Creating the constructor of the class

// NODE IDENTIFICATION
const int CUSTOM_NodeID = 1;  // Change custom node ID number here
String esp_nodeMAC = "";      // This will change automatically 

// --- DW1000 Pin Definitions (Vacus ESP32-DW1000 Boards) ---
const uint8_t PIN_RST = 27; // Reset pin
const uint8_t PIN_IRQ = 34; // Interrupt pin
const uint8_t PIN_SS = 15;  // SPI Chip Select pin

// --- Path Loss Constants for Distance Estimation ---
const float A = -45.0; // RSSI value measured precisely at 1 meter (-dBm)
const float n = 2.0;   // Path loss exponent (2.0 for free space)

void setup() {
  Serial.begin(115200); // Number in the () indicates the baud rate
  while(!Serial);
  
  // Connect to Wi-Fi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.printf("Connecting to Wifi: %s ......\n", ssid);
  }
  Serial.println("\nWiFi connected.");

  // Automatically fetch the hardware MAC address
  esp_nodeMAC = WiFi.macAddress();

  // Print on serial monitor for verification
  Serial.printf("Connected to Node number: %d\n", &CUSTOM_NodeID);
  Serial.printf("Node MAC address: %s\n", esp_nodeMAC);

  // Start UDP client
  udp.begin(8888);

  // 3. Initialize DW1000 UWB module via SPI
  SPI.begin(18, 19, 23, PIN_SS); // SCK, MISO, MOSI, SS
  DW1000.begin(PIN_IRQ, PIN_RST);
  DW1000.select(PIN_SS);
  
  // Configure UWB network parameters
  DW1000.newConfiguration();
  DW1000.setDefaults();
  DW1000.setDeviceAddress(CUSTOM_NodeID);
  DW1000.setNetworkId(10); // Shared network ID for your boards
  DW1000.commitConfiguration();

  // Set DW1000 to listen mode for incoming packets
  receiverInit();
  Serial.println("DW1000 Initialized and Listening for Node Packets...");
}

void loop() {
  // Collect sensor data (RSSI measurements)
  float currentRSSI = getDW1000RSSI(); 
  float estimatedDistance = calculateDistance(currentRSSI);

  // Combine Custom Node ID, MAC Address, and Sensor Data into one packet string
  String payload = "NodeNum:" + String(CUSTOM_NodeID) + 
                   "|MAC:" + esp_nodeMAC + 
                   "|RSSI:" + String(currentRSSI, 2) + 
                   "|Dist:" + String(estimatedDistance, 2) + "m";

// Transmit bundle via UDP to laptop
  udp.beginPacket(remoteIP, remotePort);
  udp.print(payload);
  udp.endPacket();

  Serial.println("Sent UDP Packet -> " + payload);
  delay(1000);
}

// Function to query DW1000 RX_POWER register and return RSSI in dBm
float getDW1000RSSI() {
  // DW1000 internal register calculation for Received Power
  // (Specific library functions handle byte parsing, yielding a float dBm value)
  float rxPower = DW1000.getReceivePower(); 
  return rxPower; 
}

// Log-Distance Path Loss Model Function
float calculateDistance(float rssi) {
  if (rssi >= 0) return 0.0; // Invalid or out-of-range signal
  float distance = pow(10.0, (A - rssi) / (10.0 * n));
  return distance;
}

void receiverInit() {
  DW1000.newReceive();
  DW1000.receivePermanently(true);
  DW1000.startReceive();
}