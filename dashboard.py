import tkinter as tk
from tkinter import ttk
import socket
import threading
import json
import time
import os
import csv
from datetime import datetime

# ============================================================
# NETWORK CONFIGURATION
# ============================================================
UDP_LISTEN_PORT  = 4210   # Port ESP32s send data TO (laptop listens here)
UDP_COMMAND_PORT = 8888   # Port ESP32s listen for commands ON

def get_broadcast_ip():
    """Detect local subnet and return broadcast address (e.g. 192.168.x.255)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"
    finally:
        s.close()
    parts = local_ip.split(".")
    if len(parts) == 4:
        parts[3] = "255"
        return ".".join(parts)
    return "255.255.255.255"

BROADCAST_IP = get_broadcast_ip()  # Auto-computed at startup

# ============================================================
# CSV OUTPUT CONFIGURATION
# ============================================================
CSV_DIR = "RSSI_trial_results"
NODE_IDS = [1, 2, 3]  # Change if you have more/fewer nodes

# CSV header row
CSV_HEADER = ["timestamp_ms", "toa", "rx_node", "mac", "tx_node", "rssi_dBm", "fp_power_dBm", "wall_time"]

# ============================================================
# DASHBOARD APPLICATION
# ============================================================
class UwbDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32-DW1000 UWB Dashboard")
        self.root.geometry("760x680")

        self.nodes = NODE_IDS

        # State tracking
        self.current_receiver  = tk.IntVar(value=1)
        self.active_transmitter = None

        # UDP sockets
        self.cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.cmd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self.data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.data_sock.bind(("0.0.0.0", UDP_LISTEN_PORT))
        self.data_sock.settimeout(0.1)

        # Discovery
        self.discovered_nodes = set()

        # CSV writers: key = (rx_node, tx_node)
        self.csv_writers = {}
        self.csv_files   = {}
        self._init_csv_files()

        # Build UI
        self.setup_ui()

        # Background listener
        self.running = True
        self.listen_thread = threading.Thread(target=self.listen_for_data, daemon=True)
        self.listen_thread.start()

        # Send initial discovery ping
        self._send_discovery()

        # Periodic discovery
        self.discovery_after_id = None
        self._schedule_discovery()

        # Apply initial receiver state
        self.on_receiver_change()

        # Diagnostic: last payload time
        self.last_payload_time = None
        self._check_payload_timeout()

    # ----------------------------------------------------------
    # CSV INITIALISATION
    # ----------------------------------------------------------
    def _init_csv_files(self):
        """Create RSSI_trial_results/ and open one CSV per (rx, tx) pair."""
        os.makedirs(CSV_DIR, exist_ok=True)
        for rx in self.nodes:
            for tx in self.nodes:
                if rx == tx:
                    continue
                key      = (rx, tx)
                filename = os.path.join(CSV_DIR, f"Node{rx}_receives_from_Node{tx}.csv")
                f = open(filename, "a", newline="")
                writer = csv.writer(f)
                # Write header only if file is empty
                if f.tell() == 0:
                    writer.writerow(CSV_HEADER)
                self.csv_files[key]   = f
                self.csv_writers[key] = writer
        print(f"[CSV] Files initialised in '{CSV_DIR}/'")

    def _write_csv(self, rx_node, tx_node, row_data):
        """Append one row to the appropriate CSV file."""
        key = (rx_node, tx_node)
        if key in self.csv_writers:
            self.csv_writers[key].writerow(row_data)
            self.csv_files[key].flush()

    # ----------------------------------------------------------
    # UI SETUP
    # ----------------------------------------------------------
    def setup_ui(self):
        style = ttk.Style()
        style.configure("TButton", font=("Helvetica", 10))
        style.configure("TLabel",  font=("Helvetica", 11))

        # --- Receiver selection ---
        rx_frame = ttk.LabelFrame(self.root, text=" 1. Select Receiver Node ", padding=8)
        rx_frame.pack(fill=tk.X, padx=16, pady=(10, 4))

        for node in self.nodes:
            ttk.Radiobutton(rx_frame, text=f"Node {node}",
                            variable=self.current_receiver, value=node,
                            command=self.on_receiver_change).pack(side=tk.LEFT, padx=20)

        # --- Transmitter controls ---
        tx_frame = ttk.LabelFrame(self.root, text=" 2. Control Transmitters ", padding=8)
        tx_frame.pack(fill=tk.X, padx=16, pady=4)

        self.tx_buttons = {}
        for node in self.nodes:
            row = ttk.Frame(tx_frame)
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=f"Node {node}:", width=10).pack(side=tk.LEFT)
            ttk.Button(row, text="Start TX", command=lambda n=node: self.start_tx(n)).pack(side=tk.LEFT, padx=4)
            ttk.Button(row, text="Stop TX",  command=lambda n=node: self.stop_tx(n)).pack(side=tk.LEFT, padx=4)
            status = ttk.Label(row, text="IDLE", width=14, foreground="gray")
            status.pack(side=tk.LEFT, padx=16)
            self.tx_buttons[node] = {"status": status}

        # --- Status bar ---
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=16, pady=2)
        ttk.Label(status_frame, text="Network broadcast:").pack(side=tk.LEFT)
        ttk.Label(status_frame, text=BROADCAST_IP, foreground="blue").pack(side=tk.LEFT, padx=4)
        ttk.Label(status_frame, text="   Discovered nodes:").pack(side=tk.LEFT, padx=(16, 0))
        self.disc_label = ttk.Label(status_frame, text="none yet", foreground="darkgreen")
        self.disc_label.pack(side=tk.LEFT, padx=4)

        # --- Extra control buttons ---
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill=tk.X, padx=16, pady=4)
        ttk.Button(ctrl_frame, text="Resend Discovery Ping", command=self._send_discovery).pack(side=tk.LEFT, padx=4)
        self.status_label = ttk.Label(ctrl_frame, text="⏳ Waiting for payload...", foreground="orange")
        self.status_label.pack(side=tk.LEFT, padx=20)

        # --- UWB Payload display ---
        data_frame = ttk.LabelFrame(self.root, text=" Incoming UWB Payloads ", padding=8)
        data_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 10))

        # Header row inside text box area
        hdr = ttk.Label(data_frame,
                        text=f"{'Time':>10}  {'TX→RX':^9}  {'RSSI(dBm)':>10}  {'FP(dBm)':>9}  {'ToA':>18}  MAC",
                        font=("Courier", 9, "bold"), foreground="#333")
        hdr.pack(anchor=tk.W)

        self.data_text = tk.Text(data_frame, height=16, state=tk.DISABLED,
                                 font=("Courier", 10), bg="#0d1117", fg="#c9d1d9",
                                 insertbackground="white", relief=tk.FLAT)
        self.data_text.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

        # Tag colours
        self.data_text.tag_config("payload", foreground="#79c0ff")
        self.data_text.tag_config("info",    foreground="#8b949e")
        self.data_text.tag_config("warn",    foreground="#e3b341")
        self.data_text.tag_config("error",   foreground="#f85149")

        # Packet counter
        self.pkt_count = 0
        self.count_var = tk.StringVar(value="Packets received: 0")
        ttk.Label(self.root, textvariable=self.count_var).pack(pady=(0, 6))

    # ----------------------------------------------------------
    # NETWORK HELPERS
    # ----------------------------------------------------------
    def _send_discovery(self):
        """Broadcast CMD:0:PING so all nodes reply and reveal their IPs."""
        try:
            self.cmd_sock.sendto(b"CMD:0:PING", (BROADCAST_IP, UDP_COMMAND_PORT))
            print("[Discovery] Ping sent")
        except Exception as e:
            print(f"[Discovery] {e}")

    def _schedule_discovery(self):
        """Send a discovery ping every 5 seconds to keep ESPs informed."""
        self._send_discovery()
        self.discovery_after_id = self.root.after(5000, self._schedule_discovery)

    def send_command(self, node_id, state):
        cmd = f"CMD:{node_id}:{state}".encode()
        try:
            self.cmd_sock.sendto(cmd, (BROADCAST_IP, UDP_COMMAND_PORT))
            print(f"[CMD] → {cmd.decode()}")
        except Exception as e:
            print(f"[CMD] Error: {e}")

    # ----------------------------------------------------------
    # UI LOGIC
    # ----------------------------------------------------------
    def on_receiver_change(self):
        rx = self.current_receiver.get()
        self.active_transmitter = None
        for node in self.nodes:
            self.send_command(node, "RX" if node == rx else "IDLE")
        self._update_ui_states()
        self._log(f"Node {rx} → RECEIVER", tag="info")

    def start_tx(self, node_id):
        rx = self.current_receiver.get()
        if node_id == rx:
            self._log(f"Node {node_id} is the receiver, cannot TX", tag="warn")
            return
        if self.active_transmitter and self.active_transmitter != node_id:
            self.send_command(self.active_transmitter, "IDLE")
        self.active_transmitter = node_id
        self.send_command(node_id, "TX")
        self._update_ui_states()
        self._log(f"Node {node_id} → TRANSMIT  (Receiver: Node {rx})", tag="info")

    def stop_tx(self, node_id):
        if self.active_transmitter == node_id:
            self.active_transmitter = None
        self.send_command(node_id, "IDLE")
        self._update_ui_states()
        self._log(f"Node {node_id} → IDLE", tag="info")

    def _update_ui_states(self):
        rx = self.current_receiver.get()
        for node in self.nodes:
            if node == rx:
                self.tx_buttons[node]["status"].config(text="RECEIVING", foreground="blue")
            elif self.active_transmitter == node:
                self.tx_buttons[node]["status"].config(text="TRANSMITTING", foreground="green")
            else:
                self.tx_buttons[node]["status"].config(text="IDLE", foreground="gray")

    # ----------------------------------------------------------
    # TEXT WINDOW LOGGING
    # ----------------------------------------------------------
    def _log(self, message, tag="info"):
        def _do():
            self.data_text.config(state=tk.NORMAL)
            self.data_text.insert(tk.END, message + "\n", tag)
            self.data_text.see(tk.END)
            self.data_text.config(state=tk.DISABLED)
        self.root.after(0, _do)

    def _log_payload(self, ts_ms, toa, rx_node, mac, tx_node, rssi, fp_power):
        """Format and display one UWB payload line."""
        wall = datetime.now().strftime("%H:%M:%S")
        line = (f"{wall:>10}  "
                f"N{tx_node}→N{rx_node}  "
                f"{rssi:>+10.2f}  "
                f"{fp_power:>+9.2f}  "
                f"{toa:>18}  "
                f"{mac}")

        def _do():
            self.data_text.config(state=tk.NORMAL)
            self.data_text.insert(tk.END, line + "\n", "payload")
            self.data_text.see(tk.END)
            self.data_text.config(state=tk.DISABLED)
            self.pkt_count += 1
            self.count_var.set(f"Packets received: {self.pkt_count}")
            # Update status
            self.last_payload_time = time.time()
            self.status_label.config(text="✅ Receiving payloads", foreground="green")

        self.root.after(0, _do)

    # ----------------------------------------------------------
    # DIAGNOSTIC: payload timeout
    # ----------------------------------------------------------
    def _check_payload_timeout(self):
        """Show warning if no payload received for 30 seconds."""
        if self.last_payload_time is not None:
            elapsed = time.time() - self.last_payload_time
            if elapsed > 30:
                self.status_label.config(text="⚠️ No payload for 30s – check ESPs", foreground="red")
        else:
            # Never received any payload
            self.status_label.config(text="⏳ Waiting for payload...", foreground="orange")
        self.root.after(5000, self._check_payload_timeout)

    # ----------------------------------------------------------
    # UDP LISTENER (background thread)
    # ----------------------------------------------------------
    def listen_for_data(self):
        print(f"[UDP] Listening on 0.0.0.0:{UDP_LISTEN_PORT}")
        while self.running:
            try:
                raw, addr = self.data_sock.recvfrom(1024)
                message = raw.decode("utf-8", errors="replace").strip()

                # Debug: show that a packet arrived
                print(f"[UDP] Received {len(raw)} bytes from {addr[0]}: {message[:80]}")

                # --------------------------------------------------
                # ACK packets: "ACK:<nodeID>:<command>"
                # --------------------------------------------------
                if message.startswith("ACK:"):
                    parts  = message.split(":", 2)
                    node_s = parts[1] if len(parts) > 1 else "?"
                    cmd_s  = parts[2] if len(parts) > 2 else "?"
                    # Update discovered nodes
                    try:
                        nid = int(node_s)
                        if nid > 0:
                            self.discovered_nodes.add(nid)
                            txt = f"Discovered: {sorted(self.discovered_nodes)}"
                            self.root.after(0, lambda t=txt: self.disc_label.config(text=t))
                    except ValueError:
                        pass
                    # Only show non-PING ACKs in the text window (reduce noise)
                    if "PING" not in cmd_s:
                        self._log(f"[ACK] Node {node_s} → {cmd_s}", tag="info")

                # --------------------------------------------------
                # UWB payload: JSON array  [ts, toa, rx, mac, tx, rssi, fp]
                # --------------------------------------------------
                else:
                    try:
                        payload = json.loads(message)
                        if isinstance(payload, list) and len(payload) >= 7:
                            ts_ms    = payload[0]
                            toa      = payload[1]
                            rx_node  = int(payload[2])
                            mac      = str(payload[3])
                            tx_node  = int(payload[4])
                            rssi     = float(payload[5])
                            fp_power = float(payload[6])
                            wall_t   = datetime.now().isoformat()

                            # Display in text window
                            self._log_payload(ts_ms, toa, rx_node, mac, tx_node, rssi, fp_power)

                            # Save to CSV
                            self._write_csv(rx_node, tx_node,
                                            [ts_ms, toa, rx_node, mac, tx_node, rssi, fp_power, wall_t])
                        else:
                            # Unknown JSON, show as raw
                            self._log(f"[RAW] {message}", tag="warn")
                    except (json.JSONDecodeError, ValueError):
                        # Not JSON — show raw (helps debug unexpected formats)
                        self._log(f"[RAW] from {addr[0]}: {message}", tag="warn")

            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[UDP] Error: {e}")
                time.sleep(0.5)

    # ----------------------------------------------------------
    # CLEANUP
    # ----------------------------------------------------------
    def on_close(self):
        self.running = False
        if self.discovery_after_id:
            self.root.after_cancel(self.discovery_after_id)
        try:
            self.cmd_sock.close()
            self.data_sock.close()
        except Exception:
            pass
        for f in self.csv_files.values():
            try:
                f.close()
            except Exception:
                pass
        self.root.destroy()


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    print(f"[INFO] Broadcast IP  : {BROADCAST_IP}")
    print(f"[INFO] Listen port   : {UDP_LISTEN_PORT}")
    print(f"[INFO] Command port  : {UDP_COMMAND_PORT}")
    print(f"[INFO] CSV output dir: {CSV_DIR}/")
    root = tk.Tk()
    app  = UwbDashboard(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()