import tkinter as tk
from tkinter import ttk
import socket
import threading
import json
import time

# ============================================================
# NETWORK CONFIGURATION
# ============================================================
# The port where ESP32s send UDP packets to the laptop
UDP_LISTEN_PORT = 4210 
# The port where the dashboard broadcasts commands to ESP32s
UDP_COMMAND_PORT = 8888 
# Use subnet broadcast (more reliable than 255.255.255.255 on Linux WiFi)
BROADCAST_IP = '192.168.1.255'  # <-- subnet broadcast for your network

class UwbDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32-DW1000 Master Control Dashboard")
        self.root.geometry("600x500")
        
        self.nodes = [1, 2, 3]
        
        # State tracking
        self.current_receiver = tk.IntVar(value=1) # Default Node 1 is receiver
        self.active_transmitter = None # None, 1, 2, or 3
        
        # UDP Sockets
        self.cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.cmd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        self.data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.data_sock.bind(("0.0.0.0", UDP_LISTEN_PORT))
        self.data_sock.settimeout(0.1)
        
        self.setup_ui()
        
        # Start data listening thread
        self.running = True
        self.listen_thread = threading.Thread(target=self.listen_for_data, daemon=True)
        self.listen_thread.start()
        # Discovery structures
        self.discovered_nodes = set()
        self.discovered_label = ttk.Label(self.root, text='Discovered Nodes: None', font=('Helvetica', 10))
        self.discovered_label.pack(pady=5)
        # Send initial discovery ping
        self.send_discovery()
        
        # Apply initial state
        self.on_receiver_change()
        
    def setup_ui(self):
        style = ttk.Style()
        style.configure('TButton', font=('Helvetica', 10))
        style.configure('TLabel', font=('Helvetica', 11))
        style.configure('Header.TLabel', font=('Helvetica', 14, 'bold'))
        
        # --------------------------------------------------------
        # RECEIVER SELECTION FRAME
        # --------------------------------------------------------
        rx_frame = ttk.LabelFrame(self.root, text=" 1. Select Receiver Node ", padding=10)
        rx_frame.pack(fill=tk.X, padx=20, pady=10)
        
        for node in self.nodes:
            rb = ttk.Radiobutton(rx_frame, text=f"Node {node}", variable=self.current_receiver, 
                                 value=node, command=self.on_receiver_change)
            rb.pack(side=tk.LEFT, padx=20)
            
        # --------------------------------------------------------
        # TRANSMITTER CONTROL FRAME
        # --------------------------------------------------------
        tx_frame = ttk.LabelFrame(self.root, text=" 2. Control Transmitters ", padding=10)
        tx_frame.pack(fill=tk.X, padx=20, pady=10)
        
        self.tx_buttons = {}
        
        for node in self.nodes:
            frame = ttk.Frame(tx_frame)
            frame.pack(fill=tk.X, pady=5)
            
            lbl = ttk.Label(frame, text=f"Node {node}:", width=10)
            lbl.pack(side=tk.LEFT)
            
            start_btn = ttk.Button(frame, text="Start TX", command=lambda n=node: self.start_tx(n))
            start_btn.pack(side=tk.LEFT, padx=5)
            
            stop_btn = ttk.Button(frame, text="Stop TX", command=lambda n=node: self.stop_tx(n))
            stop_btn.pack(side=tk.LEFT, padx=5)
            
            status_lbl = ttk.Label(frame, text="IDLE", width=15, foreground="gray")
            status_lbl.pack(side=tk.LEFT, padx=20)
            
            self.tx_buttons[node] = {
                'start': start_btn,
                'stop': stop_btn,
                'status': status_lbl
            }

        # --------------------------------------------------------
        # DATA DISPLAY FRAME
        # --------------------------------------------------------
        data_frame = ttk.LabelFrame(self.root, text=" Incoming UWB Data ", padding=10)
        data_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        self.data_text = tk.Text(data_frame, height=10, state=tk.DISABLED, font=('Courier', 10))
        self.data_text.pack(fill=tk.BOTH, expand=True)

    def send_discovery(self):
        self.cmd_sock.sendto(b'CMD:0:PING', (BROADCAST_IP, UDP_COMMAND_PORT))
        print('Sent discovery PING')

    def send_command(self, node_id, state):
        # Broadcast a PING command for discovery (node ID 0)
        self.cmd_sock.sendto(b'CMD:0:PING', (BROADCAST_IP, UDP_COMMAND_PORT))
        print('Sent discovery PING')
        # Normal command broadcast
        cmd_str = f"CMD:{node_id}:{state}"
        try:
            self.cmd_sock.sendto(cmd_str.encode(), (BROADCAST_IP, UDP_COMMAND_PORT))
            print(f"Broadcasted: {cmd_str}")
        except Exception as e:
            print(f"Error sending command: {e}")

    def update_ui_states(self):
        rx_node = self.current_receiver.get()
        
        for node in self.nodes:
            if node == rx_node:
                self.tx_buttons[node]['start'].state(['disabled'])
                self.tx_buttons[node]['stop'].state(['disabled'])
                self.tx_buttons[node]['status'].config(text="RECEIVING", foreground="blue")
            else:
                self.tx_buttons[node]['start'].state(['!disabled'])
                self.tx_buttons[node]['stop'].state(['!disabled'])
                
                if self.active_transmitter == node:
                    self.tx_buttons[node]['status'].config(text="TRANSMITTING", foreground="green")
                else:
                    self.tx_buttons[node]['status'].config(text="IDLE", foreground="gray")

    def on_receiver_change(self):
        rx_node = self.current_receiver.get()
        self.active_transmitter = None # Reset transmitter when receiver changes
        
        # Command new receiver to RX, others to IDLE
        for node in self.nodes:
            if node == rx_node:
                self.send_command(node, "RX")
            else:
                self.send_command(node, "IDLE")
        
        self.update_ui_states()
        self.log_data(f"--- Node {rx_node} configured as Receiver ---")

    def start_tx(self, node_id):
        # Stop previously active transmitter if it's different
        if self.active_transmitter is not None and self.active_transmitter != node_id:
            self.send_command(self.active_transmitter, "IDLE")
        # Set new active transmitter
        self.active_transmitter = node_id
        # Ensure the selected receiver stays in RX mode (re‑assert command)
        # Broadcast a discovery ping to all nodes (node ID 0)
        self.cmd_sock.sendto(b'CMD:0:PING', (BROADCAST_IP, UDP_COMMAND_PORT))
        print('Discovery ping sent')
        # Command the chosen node to start transmitting
        self.send_command(node_id, "TX")
        self.update_ui_states()
        self.log_data(f"--- Node {node_id} set to TRANSMIT, Receiver Node {self.current_receiver.get()} stays in RX ---")
        
    def stop_tx(self, node_id):
        if self.active_transmitter == node_id:
            self.active_transmitter = None
        self.send_command(node_id, "IDLE")
        self.update_ui_states()

    def log_data(self, message):
        def _log():
            self.data_text.config(state=tk.NORMAL)
            self.data_text.insert(tk.END, message + "\n")
            self.data_text.see(tk.END) # Auto-scroll
            self.data_text.config(state=tk.DISABLED)
        self.root.after(0, _log)

    def listen_for_data(self):
        while self.running:
            try:
                data, addr = self.data_sock.recvfrom(1024)
                message = data.decode('utf-8', errors='replace').strip()

                # ACK packets: "ACK:<nodeID>:<command>"
                if message.startswith("ACK:"):
                    parts = message.split(":", 2)
                    node = parts[1] if len(parts) > 1 else "?"
                    cmd  = parts[2] if len(parts) > 2 else "?"
                    # Record discovered node ID (ignore PING ACKs)
                    try:
                        nid = int(node)
                        self.discovered_nodes.add(nid)
                        self.discovered_label.config(text=f'Discovered Nodes: {sorted(self.discovered_nodes)}')
                    except ValueError:
                        pass
                    # Record discovered node ID (ignore node 0)
                    try:
                        nid = int(node)
                        if nid != 0:
                            self.discovered_nodes.add(nid)
                            self.discovered_label.config(text=f'Discovered Nodes: {sorted(self.discovered_nodes)}')
                    except ValueError:
                        pass
                    self.log_data(f"[ACK] Node {node} confirmed: {cmd}")

                # UWB payload: [timestamp, toa, rxNode, mac, txNode, rssi, fpPower]
                else:
                    try:
                        payload = json.loads(message)
                        if len(payload) >= 7:
                            ts, toa, rx_node, mac, tx_node, rssi, fp = payload
                            self.log_data(
                                f"[UWB] TX=Node{tx_node}  RX=Node{rx_node}  "
                                f"RSSI={rssi:.1f}dBm  FP={fp:.1f}dBm  ToA={toa}"
                            )
                        else:
                            self.log_data(f"[RAW] {message}")
                    except Exception:
                        self.log_data(f"[RAW] from {addr[0]}: {message}")

            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"UDP Listen Error: {e}")
                time.sleep(1)


    def on_close(self):
        self.running = False
        self.cmd_sock.close()
        self.data_sock.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = UwbDashboard(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
