from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import AppConfig
from .dlms_service import DlmsBrowserService


class DlmsBrowserApp(tk.Tk):
    def __init__(self, config_path: str | Path):
        super().__init__()
        self.title("DLMS/COSEM Browser (Gurux-based)")
        self.geometry("1360x860")

        self.config_path = Path(config_path)
        self.app_config = AppConfig.load(self.config_path)
        self.service = DlmsBrowserService(self.app_config, logger=self._push_log_event)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.is_busy = False

        self.port_var = tk.StringVar(value=self.app_config.serial.port)
        self.baud_var = tk.StringVar(value=str(self.app_config.serial.baud_rate))
        self.data_bits_var = tk.StringVar(value=str(self.app_config.serial.data_bits))
        self.parity_var = tk.StringVar(value=self.app_config.serial.parity)
        self.stop_bits_var = tk.StringVar(value=str(self.app_config.serial.stop_bits))

        self.client_addr_var = tk.StringVar(value=str(self.app_config.dlms.client_address))
        self.server_addr_var = tk.StringVar(value=str(self.app_config.dlms.server_address))
        self.logical_server_var = tk.StringVar(value=str(self.app_config.dlms.logical_server))
        self.physical_server_var = tk.StringVar(value=str(self.app_config.dlms.physical_server))
        self.address_type_var = tk.StringVar(value=self.app_config.dlms.address_type)
        self.broadcast_var = tk.BooleanVar(value=self.app_config.dlms.broadcast)
        self.wait_time_var = tk.StringVar(value=self.app_config.dlms.wait_time)
        self.resend_count_var = tk.StringVar(value=str(self.app_config.dlms.resend_count))
        self.inactivity_timeout_var = tk.StringVar(value=self.app_config.dlms.inactivity_timeout)
        self.auth_var = tk.StringVar(value=self.app_config.dlms.authentication)
        self.password_var = tk.StringVar(value=self.app_config.dlms.password)
        self.interface_var = tk.StringVar(value=self.app_config.dlms.interface_type)
        self.trace_var = tk.StringVar(value=self.app_config.dlms.trace_level)
        self.window_var = tk.StringVar(value=str(self.app_config.dlms.hdlc_window_size))
        self.frame_var = tk.StringVar(value=str(self.app_config.dlms.hdlc_frame_size))
        self.ln_ref_var = tk.BooleanVar(value=self.app_config.dlms.use_logical_name_referencing)
        self.standard_var = tk.StringVar(value=self.app_config.dlms.standard)
        self.manufacturer_var = tk.StringVar(value=self.app_config.dlms.manufacturer_id)

        self.status_var = tk.StringVar(value="Ready")

        self.type_nodes: dict[str, str] = {}
        self.node_to_ln: dict[str, str] = {}

        self._build_ui()
        self._refresh_ports()
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill=tk.X)

        serial_group = ttk.LabelFrame(top, text="Serial / COM", padding=8)
        serial_group.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        for col in range(4):
            serial_group.columnconfigure(col, weight=1)

        ttk.Label(serial_group, text="Port").grid(row=0, column=0, sticky="w")
        self.port_combo = ttk.Combobox(serial_group, textvariable=self.port_var, width=16)
        self.port_combo.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(serial_group, text="Refresh", command=self._refresh_ports).grid(row=0, column=2, padx=4)

        ttk.Label(serial_group, text="Baud").grid(row=1, column=0, sticky="w")
        ttk.Entry(serial_group, textvariable=self.baud_var, width=10).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(serial_group, text="Data bits").grid(row=1, column=2, sticky="w")
        ttk.Entry(serial_group, textvariable=self.data_bits_var, width=8).grid(row=1, column=3, sticky="w", padx=4)

        ttk.Label(serial_group, text="Parity").grid(row=2, column=0, sticky="w")
        ttk.Combobox(serial_group, textvariable=self.parity_var, values=["NONE", "EVEN", "ODD"], width=10).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(serial_group, text="Stop bits").grid(row=2, column=2, sticky="w")
        ttk.Combobox(serial_group, textvariable=self.stop_bits_var, values=["1", "2"], width=8).grid(row=2, column=3, sticky="w", padx=4)

        dlms_group = ttk.LabelFrame(top, text="DLMS / HDLC", padding=8)
        dlms_group.pack(side=tk.LEFT, fill=tk.X, expand=True)
        for col in range(6):
            dlms_group.columnconfigure(col, weight=1)

        ttk.Label(dlms_group, text="Client").grid(row=0, column=0, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.client_addr_var, width=10).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(dlms_group, text="Wait Time").grid(row=0, column=2, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.wait_time_var, width=12).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(dlms_group, text="Resend count").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(dlms_group, from_=0, to=10, textvariable=self.resend_count_var, width=6).grid(row=0, column=5, sticky="w", padx=4)

        ttk.Label(dlms_group, text="Address Type").grid(row=1, column=0, sticky="w")
        ttk.Combobox(dlms_group, textvariable=self.address_type_var, values=["DEFAULT", "1_BYTE", "2_BYTE", "4_BYTE"], width=12).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Checkbutton(dlms_group, text="Broadcast", variable=self.broadcast_var).grid(row=1, column=2, sticky="w")
        ttk.Label(dlms_group, text="Logical Server").grid(row=1, column=3, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.logical_server_var, width=8).grid(row=1, column=4, sticky="w", padx=4)
        ttk.Label(dlms_group, text="Physical Server").grid(row=2, column=0, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.physical_server_var, width=8).grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(dlms_group, text="Server raw").grid(row=2, column=2, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.server_addr_var, width=10).grid(row=2, column=3, sticky="w", padx=4)
        ttk.Label(dlms_group, text="Auth").grid(row=2, column=4, sticky="w")
        ttk.Combobox(
            dlms_group,
            textvariable=self.auth_var,
            values=["NONE", "LOW", "HIGH", "HIGH_MD5", "HIGH_SHA1", "HIGH_GMAC", "HIGH_SHA256"],
            width=16,
        ).grid(row=2, column=5, sticky="w", padx=4)

        ttk.Label(dlms_group, text="Password / secret").grid(row=3, column=0, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.password_var, width=16, show="*").grid(row=3, column=1, sticky="w", padx=4)
        ttk.Label(dlms_group, text="Inactivity Timeout").grid(row=3, column=2, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.inactivity_timeout_var, width=12).grid(row=3, column=3, sticky="w", padx=4)

        ttk.Label(dlms_group, text="Interface").grid(row=3, column=4, sticky="w")
        ttk.Combobox(dlms_group, textvariable=self.interface_var, values=["HDLC", "HDLC_WITH_MODE_E"], width=16).grid(row=3, column=5, sticky="w", padx=4)
        ttk.Label(dlms_group, text="Standard").grid(row=4, column=0, sticky="w")
        ttk.Combobox(dlms_group, textvariable=self.standard_var, values=["DLMS", "IDIS", "INDIA", "ITALY", "SAUDI_ARABIA"], width=16).grid(row=4, column=1, sticky="w", padx=4)

        ttk.Checkbutton(dlms_group, text="Use LN referencing", variable=self.ln_ref_var).grid(row=4, column=2, columnspan=2, sticky="w")
        ttk.Label(dlms_group, text="HDLC window").grid(row=4, column=4, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.window_var, width=10).grid(row=4, column=5, sticky="w", padx=4)
        ttk.Label(dlms_group, text="HDLC frame").grid(row=5, column=0, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.frame_var, width=10).grid(row=5, column=1, sticky="w", padx=4)

        ttk.Label(dlms_group, text="Manufacturer").grid(row=5, column=2, sticky="w")
        ttk.Entry(dlms_group, textvariable=self.manufacturer_var, width=16).grid(row=5, column=3, sticky="w", padx=4)

        toolbar = ttk.Frame(self, padding=(10, 0, 10, 8))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Save config", command=self._save_config).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Connect", command=self._connect).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Read object tree", command=self._read_tree).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Disconnect", command=self._disconnect).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Close port", command=self._close_port).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Clear log", command=self._clear_log).pack(side=tk.LEFT, padx=4)
        ttk.Label(toolbar, textvariable=self.status_var).pack(side=tk.RIGHT)

        content = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        content.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(content)
        right = ttk.Frame(content)
        content.add(left, weight=1)
        content.add(right, weight=1)

        self.tree = ttk.Treeview(left, columns=("ln", "desc"), show="tree headings")
        self.tree.heading("#0", text="Class / object")
        self.tree.heading("ln", text="Logical Name")
        self.tree.heading("desc", text="Description")
        self.tree.column("#0", width=260)
        self.tree.column("ln", width=160)
        self.tree.column("desc", width=360)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        details_group = ttk.LabelFrame(right, text="Object details", padding=6)
        details_group.pack(fill=tk.BOTH, expand=True)
        self.details = tk.Text(details_group, wrap="word", height=16)
        self.details.pack(fill=tk.BOTH, expand=True)

        log_group = ttk.LabelFrame(right, text="Exchange log", padding=6)
        log_group.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.log_text = ScrolledText(log_group, wrap="word", height=14, state="disabled")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _refresh_ports(self) -> None:
        ports = self.service.list_serial_ports()
        self.port_combo["values"] = ports
        if ports and self.port_var.get() not in ports:
            self.port_var.set(ports[0])

    def _collect_config(self) -> AppConfig:
        self.app_config.serial.port = self.port_var.get().strip()
        self.app_config.serial.baud_rate = int(self.baud_var.get())
        self.app_config.serial.data_bits = int(self.data_bits_var.get())
        self.app_config.serial.parity = self.parity_var.get().strip().upper()
        self.app_config.serial.stop_bits = int(self.stop_bits_var.get())

        self.app_config.dlms.client_address = int(self.client_addr_var.get())
        self.app_config.dlms.server_address = int(self.server_addr_var.get())
        self.app_config.dlms.logical_server = int(self.logical_server_var.get())
        self.app_config.dlms.physical_server = int(self.physical_server_var.get())
        self.app_config.dlms.address_type = self.address_type_var.get().strip().upper()
        self.app_config.dlms.broadcast = self.broadcast_var.get()
        self.app_config.dlms.wait_time = self.wait_time_var.get().strip()
        self.app_config.dlms.resend_count = int(self.resend_count_var.get())
        self.app_config.dlms.inactivity_timeout = self.inactivity_timeout_var.get().strip()
        self.app_config.dlms.authentication = self.auth_var.get().strip().upper()
        self.app_config.dlms.password = self.password_var.get()
        self.app_config.dlms.interface_type = self.interface_var.get().strip().upper()
        self.app_config.dlms.trace_level = self.trace_var.get().strip().upper()
        self.app_config.dlms.hdlc_window_size = int(self.window_var.get())
        self.app_config.dlms.hdlc_frame_size = int(self.frame_var.get())
        self.app_config.dlms.use_logical_name_referencing = self.ln_ref_var.get()
        self.app_config.dlms.standard = self.standard_var.get().strip().upper()
        self.app_config.dlms.manufacturer_id = self.manufacturer_var.get().strip().upper()
        return self.app_config

    def _save_config(self) -> None:
        try:
            self._collect_config().save(self.config_path)
            self.status_var.set(f"Config saved: {self.config_path}")
        except Exception as exc:
            messagebox.showerror("Save config", str(exc))

    def _run_worker(self, action: str, func) -> None:
        if self.is_busy:
            return
        self.is_busy = True
        self.status_var.set(action)
        threading.Thread(target=self._thread_entry, args=(func,), daemon=True).start()

    def _thread_entry(self, func) -> None:
        try:
            result = func()
            self.events.put(("ok", result))
        except Exception as exc:
            self.events.put(("error", exc))

    def _connect(self) -> None:
        def work():
            self._collect_config().save(self.config_path)
            self.service = DlmsBrowserService(self.app_config, logger=self._push_log_event)
            self.service.connect()
            self.server_addr_var.set(str(self.app_config.dlms.server_address))
            return "Connected"

        self._run_worker("Connecting...", work)

    def _disconnect(self) -> None:
        def work():
            self.service.disconnect()
            return "Disconnected"

        self._run_worker("Disconnecting...", work)

    def _read_tree(self) -> None:
        def work():
            return self.service.load_objects()

        self._run_worker("Reading association view...", work)

    def _close_port(self) -> None:
        def work():
            self.service.disconnect()
            return "Port closed"

        self._run_worker("Closing port...", work)

    def _push_log_event(self, kind: str, message: str) -> None:
        self.events.put(("log", (kind, message)))

    def _append_log(self, kind: str, message: str) -> None:
        prefix_map = {
            "tx": "TX",
            "rx": "RX",
            "event": "EV",
            "frame": "FR",
        }
        prefix = prefix_map.get(kind, kind.upper())
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{prefix}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")
        self.status_var.set("Log cleared")

    def _on_tree_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        node = selection[0]
        logical_name = self.node_to_ln.get(node)
        if not logical_name:
            return

        def work():
            return logical_name, self.service.read_object_attributes(logical_name)

        self._run_worker(f"Reading attributes for {logical_name}...", work)

    def _populate_tree(self, objects) -> None:
        self.tree.delete(*self.tree.get_children())
        self.type_nodes.clear()
        self.node_to_ln.clear()
        for obj in sorted(objects, key=lambda x: (x.object_type_id, x.logical_name)):
            parent = self.type_nodes.get(obj.object_type)
            if not parent:
                parent = self.tree.insert("", "end", text=obj.object_type, values=("", ""), open=False)
                self.type_nodes[obj.object_type] = parent
            label = f"v{obj.version} / SN {obj.short_name}" if obj.short_name else f"v{obj.version}"
            node = self.tree.insert(parent, "end", text=label, values=(obj.logical_name, obj.description))
            self.node_to_ln[node] = obj.logical_name
        self.status_var.set(f"Loaded {len(objects)} objects")

    def _show_attributes(self, logical_name: str, attrs) -> None:
        self.details.delete("1.0", tk.END)
        self.details.insert(tk.END, f"Logical Name: {logical_name}\n\n")
        for index, value in attrs:
            self.details.insert(tk.END, f"Attribute {index}:\n{value}\n\n")
        self.status_var.set(f"Attributes loaded for {logical_name}")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "error":
                    self.status_var.set("Error")
                    self._append_log("event", f"Operation failed: {payload}")
                    messagebox.showerror("DLMS browser", str(payload))
                elif kind == "log":
                    self._append_log(payload[0], payload[1])
                elif isinstance(payload, str):
                    self.status_var.set(payload)
                elif isinstance(payload, list):
                    self._populate_tree(payload)
                elif isinstance(payload, tuple) and len(payload) == 2:
                    self._show_attributes(payload[0], payload[1])
        except queue.Empty:
            pass
        finally:
            if self.events.empty():
                self.is_busy = False
        self.after(100, self._poll_events)

    def _on_close(self) -> None:
        try:
            self.service.disconnect()
        except Exception:
            pass
        self.destroy()
