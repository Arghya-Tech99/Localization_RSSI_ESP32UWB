#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <DW1000.h>
#include <SPI.h>

// ============================================================
// WIFI DETAILS
// ============================================================
const char* ssid = "Airtel_Housr 409-410";  // enter wifi or hotspot name here
const char* password = "Housr@12345"; // enter the wifi or hotspot password here

// Destination (Laptop) IP and Port for UDP data reporting
// Pre-seeded with laptop's known IP; updated dynamically on first command
IPAddress remoteIP(192, 168, 1, 2);  // Your laptop's IP on the shared network
bool remoteIPKnown = true;           // Set true since IP is pre-configured
unsigned int remotePort = 4210; 

WiFiUDP udp; // UDP client for sending data
WiFiUDP udpServer; // UDP server for receiving commands
unsigned int localCommandPort = 8888;

// ============================================================
// NODE IDENTIFICATION & STATE
// ============================================================
const uint8_t CUSTOM_NodeID = 2;  // Change custom node ID number here for each device

enum NodeMode {
    MODE_IDLE,
    MODE_RX,
    MODE_TX
};

NodeMode currentMode = MODE_IDLE; // Start in idle mode

// ============================================================
// DW1000 PIN DEFINITIONS (Vacus ESP32-DW1000 Boards)
// ============================================================
const uint8_t PIN_RST = 27; // Reset pin
const uint8_t PIN_IRQ = 34; // Interrupt pin
const uint8_t PIN_SS = 15;  // SPI Chip Select pin

// ============================================================
// UWB PACKET STRUCTURE
// ============================================================
#pragma pack(push, 1)
struct UWBPacket {
    uint8_t nodeID;
    uint32_t sequence;
    uint64_t transmitTime;
};
#pragma pack(pop)

// ============================================================
// GLOBAL VARIABLES
// ============================================================
volatile bool packetReceived = false;
volatile bool receiveError = false;
volatile bool packetSent = false;
uint32_t packetSequence = 0;
byte receivedData[128];
String esp_mac = ""; // Stores the MAC address of the receiving node

// ============================================================
// CALLBACKS
// ============================================================
void handleReceived() {
    packetReceived = true;
}
void handleReceiveError() {
    receiveError = true;
}
void handleSent() {
    packetSent = true;
}

// ============================================================
// RECEIVER AND TRANSMITTER CONTROL
// ============================================================
void startReceiver() {
    DW1000.newReceive();
    DW1000.setDefaults();
    // Continuous reception
    DW1000.receivePermanently(true);
    DW1000.startReceive();
}

void enterIdleMode() {
    // Put DW1000 into idle mode
    DW1000.idle();
    packetReceived = false;
    receiveError = false;
    packetSent = false;
}

void transmitPacket() {
    UWBPacket packet;
    packet.nodeID = CUSTOM_NodeID;
    packet.sequence = packetSequence++;
    packet.transmitTime = millis();
    
    byte data[sizeof(UWBPacket)];
    memcpy(data, &packet, sizeof(UWBPacket));
    
    DW1000.newTransmit();
    DW1000.setDefaults();
    DW1000.setData(data, sizeof(UWBPacket));
    DW1000.startTransmit();
}

// ============================================================
// SETUP
// ============================================================
void setup() {
    Serial.begin(115200);
    while(!Serial);
    
    Serial.println("\n=========================================");
    Serial.println("ESP32-DW1000 Dashboard Controlled Node");
    Serial.println("=========================================");
    
    // Connect to Wi-Fi
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.printf("Connecting to Wifi: %s ......\n", ssid);
    }
    Serial.println("\nWiFi connected.");
    esp_mac = WiFi.macAddress();
    Serial.print("Node MAC Address: ");
    Serial.println(esp_mac);
    
    // Start UDP server for receiving commands
    udpServer.begin(localCommandPort);
    Serial.printf("Listening for UDP commands on port %d\n", localCommandPort);
    
    // Initialize DW1000 UWB module via SPI
    SPI.begin(18, 19, 23, PIN_SS); // SCK, MISO, MOSI, SS
    DW1000.begin(PIN_IRQ, PIN_RST);
    DW1000.select(PIN_SS);
    
    DW1000.newConfiguration();
    DW1000.setDefaults();
    DW1000.setDeviceAddress(CUSTOM_NodeID);
    DW1000.setNetworkId(10); // Shared network ID for your boards
    DW1000.commitConfiguration();
    
    // Attach Callbacks
    DW1000.attachReceivedHandler(handleReceived);
    DW1000.attachReceiveFailedHandler(handleReceiveError);
    DW1000.attachSentHandler(handleSent);
    
    // Start in IDLE state
    enterIdleMode();
    Serial.print("UDP data will be sent to: ");
    Serial.print(remoteIP);
    Serial.print(":");
    Serial.println(remotePort);
    Serial.println("DW1000 Initialized. Waiting for Dashboard Commands...");
}

// ============================================================
// MAIN LOOP
// ============================================================
void loop() {
    // --------------------------------------------------------
    // PROCESS INCOMING DASHBOARD COMMANDS
    // --------------------------------------------------------
    int packetSize = udpServer.parsePacket();
    if (packetSize) {
        char incomingPacket[255];
        int len = udpServer.read(incomingPacket, 255);
        if (len > 0) {
            incomingPacket[len] = 0;
        }
        
        // Dynamically discover the laptop's IP from the sender of the command
        IPAddress senderIP = udpServer.remoteIP();
        // Only accept real unicast IPs (not 0.0.0.0 or 255.x.x.x)
        if (senderIP[0] != 0 && senderIP[0] != 255) {
            remoteIP = senderIP;
            remoteIPKnown = true;
            Serial.print("Laptop IP discovered: ");
            Serial.println(remoteIP);
        }

        String command = String(incomingPacket);
        command.trim();
        Serial.println("Received Command: " + command + " from IP: " + udpServer.remoteIP().toString());

        // Send an ACK back so we can confirm two-way UDP works
        if (remoteIPKnown) {
            String ack = "ACK:" + String(CUSTOM_NodeID) + ":" + command;
            udp.beginPacket(remoteIP, remotePort);
            udp.print(ack);
            udp.endPacket();
        }
        
        // Command format: CMD:<NodeID>:<STATE>
        // Examples: CMD:1:RX, CMD:2:TX, CMD:3:IDLE
        String expectedPrefix = "CMD:" + String(CUSTOM_NodeID) + ":";
        
        if (command.startsWith(expectedPrefix)) {
            String newState = command.substring(expectedPrefix.length());
            
            if (newState == "RX") {
                currentMode = MODE_RX;
                startReceiver();
                Serial.println("Mode changed to RECEIVER");
            } 
            else if (newState == "TX") {
                currentMode = MODE_TX;
                enterIdleMode(); // clear any pending operations
                Serial.println("Mode changed to TRANSMITTER");
            } 
            else if (newState == "IDLE") {
                currentMode = MODE_IDLE;
                enterIdleMode();
                Serial.println("Mode changed to IDLE");
            }
        }
    }

    // --------------------------------------------------------
    // MODE-SPECIFIC LOGIC
    // --------------------------------------------------------
    
    if (currentMode == MODE_RX) {
        if (packetReceived) {
            packetReceived = false;
            
            uint16_t dataLen = DW1000.getDataLength();
            DW1000.getData(receivedData, dataLen);
            
            if (dataLen >= sizeof(UWBPacket)) {
                UWBPacket packet;
                memcpy(&packet, receivedData, sizeof(UWBPacket));
                
                // Ignore packets transmitted by this node
                if (packet.nodeID != CUSTOM_NodeID) {
                    DW1000Time receiveTimestamp;
                    DW1000.getReceiveTimestamp(receiveTimestamp);
                    uint64_t toa = receiveTimestamp.getTimestamp();
                    
                    float rssi = DW1000.getReceivePower();
                    float fpPower = DW1000.getFirstPathPower();
                    uint64_t currentTime = millis();
                    
                    // Format Payload
                    char payload[256];
                    snprintf(payload, sizeof(payload), "[%llu, %llu, %u, \"%s\", %u, %.2f, %.2f]", 
                             currentTime, toa, CUSTOM_NodeID, esp_mac.c_str(), packet.nodeID, rssi, fpPower);
                    
                    Serial.println(String("Sending UDP to ") + remoteIP.toString() + ":" + remotePort);
                    Serial.println(String("Payload: ") + payload);
                    
                    if (remoteIPKnown) {
                        // Transmit payload to python script via UDP
                        udp.beginPacket(remoteIP, remotePort);
                        udp.print(payload);
                        int result = udp.endPacket();
                        Serial.println(result == 1 ? "UDP sent OK" : "UDP send FAILED");
                    } else {
                        Serial.println("WARNING: remoteIP not yet known, cannot send UDP!");
                    }
                }
            }
            // Restart receiver after processing
            startReceiver();
        }

        if (receiveError) {
            receiveError = false;
            startReceiver();
        }
    } 
    else if (currentMode == MODE_TX) {
        if (packetSent) {
            packetSent = false;
            // Node is in TX mode, do not start receiver.
        }
        
        static uint32_t lastTransmission = 0;
        if (millis() - lastTransmission >= 1000) { // Transmit every 1 second
            lastTransmission = millis();
            transmitPacket();
            Serial.println("Transmitted UWB packet");
        }
    }
}