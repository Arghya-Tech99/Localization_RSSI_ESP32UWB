"""
Quick UDP sniffer – run this INSTEAD of the dashboard to check
whether the ESP32 RX node is sending anything back at all.
"""
import socket

PORT = 4210
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", PORT))
sock.settimeout(5)

print(f"Listening for UDP packets on port {PORT} ...")
print("If nothing appears within 10 s, the ESP32 is not sending data back.\n")

while True:
    try:
        data, addr = sock.recvfrom(1024)
        print(f"[RECEIVED] from {addr}: {data.decode('utf-8', errors='replace')}")
    except socket.timeout:
        print("[timeout] No packet received in the last 5 s …")
