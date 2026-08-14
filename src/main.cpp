#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "DW1000.h"

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

void setup() {
  Serial.begin(115200); // Number in the () indicates the baud rate
  
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
}

void loop() {
  // Collect sensor data (e.g., RSSI or UWB measurements)
  /*
  HERE A FUNCTION OR SOME METHOD NEEDS TO BE ADDED
  WHICH WILL COLLECT SENSOR DATA AND FORMAT THE THING INTO 
  A PAYLOAD WHICH WILL THEN BE TRANSMITTED ON TO CONTROL COMPUTER 
  FOR FURTHER PROCESSING
  */
  int RSSI = -65; // JUST A DUMMY, CHANGE LATER AS PER INSTRUCTIONS ABOVE 
  String sensorData = "Node_1: RSSI = -65dBm"; // Changes made here

  // Send data via UDP
  udp.beginPacket(remoteIP, remotePort);
  udp.print(sensorData);
  udp.endPacket();

  delay(1000); // Send every second
}