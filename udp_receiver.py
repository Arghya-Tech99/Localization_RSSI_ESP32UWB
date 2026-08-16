import socket

# This should match the port configured in main.cpp
UDP_IP = "0.0.0.0" # Listen on all available network interfaces
UDP_PORT = 4210

# Create a UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print(f"Listening for UWB UDP packets on port {UDP_PORT}...")
print("Make sure your ESP32 is connected to the same Wi-Fi hotspot as this computer.")
print("Waiting for data...\n")

try:
    while True:
        data, addr = sock.recvfrom(1024) # buffer size is 1024 bytes
        # Decode the bytes to a string
        payload = data.decode('utf-8')
        print(f"Received from {addr}: {payload}")
except KeyboardInterrupt:
    print("\nStopped listening.")
    sock.close()
