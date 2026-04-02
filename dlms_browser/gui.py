from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

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
        self.settings_summary_var = tk.StringVar(value="")
        self.current_logical_name: str | None = None
        self.attribute_vars: dict[int, tk.StringVar] = {}

        self.type_nodes: dict[str, str] = {}
        self.node_to_ln: dict[str, str] = {}
        self.serial_ports: list[str] = []

        self._build_ui()
        self._restore_cached_tree()
        self._refresh_ports()
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill=tk.X)
        settings_group = ttk.LabelFrame(top, text="Connection settings", padding=8)
        settings_group.pack(fill=tk.X, expand=True)
        for col in range(4):
            settings_group.columnconfigure(col, weight=1)

        ttk.Button(settings_group, text="Serial / COM...", command=self._open_serial_settings).grid(row=0, column=0, sticky="ew", padx=3, pady=2)
        ttk.Button(settings_group, text="Addressing...", command=self._open_address_settings).grid(row=0, column=1, sticky="ew", padx=3, pady=2)
        ttk.Button(settings_group, text="Security & Session...", command=self._open_security_settings).grid(row=0, column=2, sticky="ew", padx=3, pady=2)
        ttk.Button(settings_group, text="HDLC & Profile...", command=self._open_link_settings).grid(row=0, column=3, sticky="ew", padx=3, pady=2)
        ttk.Label(settings_group, textvariable=self.settings_summary_var).grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=(6, 0))
        self._update_settings_summary()

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
        details_toolbar = ttk.Frame(details_group)
        details_toolbar.pack(fill=tk.X, pady=(0, 6))
        self.details_title_var = tk.StringVar(value="Select object to load attributes")
        ttk.Label(details_toolbar, textvariable=self.details_title_var).pack(side=tk.LEFT)
        self.write_button = tk.Button(
            details_toolbar,
            text="WRITE",
            bg="#0b6b3a",
            fg="white",
            activebackground="#0f8f4e",
            activeforeground="white",
            font=("TkDefaultFont", 9, "bold"),
            relief=tk.RAISED,
            padx=12,
            pady=3,
            command=self._write_attributes,
            state=tk.DISABLED,
        )
        self.write_button.pack(side=tk.RIGHT)

        self.details_canvas = tk.Canvas(details_group, highlightthickness=0)
        details_scroll = ttk.Scrollbar(details_group, orient=tk.VERTICAL, command=self.details_canvas.yview)
        self.details_canvas.configure(yscrollcommand=details_scroll.set)
        self.details_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        details_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.details_frame = ttk.Frame(self.details_canvas)
        self.details_canvas_window = self.details_canvas.create_window((0, 0), window=self.details_frame, anchor="nw")
        self.details_frame.bind("<Configure>", self._on_details_frame_configure)
        self.details_canvas.bind("<Configure>", self._on_details_canvas_configure)

        log_group = ttk.LabelFrame(right, text="Exchange log", padding=6)
        log_group.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.log_text = ScrolledText(log_group, wrap="word", height=14, state="disabled")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _update_settings_summary(self) -> None:
        self.settings_summary_var.set(
            f"COM={self.port_var.get().strip() or '<none>'}, baud={self.baud_var.get().strip() or '?'} | "
            f"client={self.client_addr_var.get().strip() or '?'}, logical={self.logical_server_var.get().strip() or '?'}, physical={self.physical_server_var.get().strip() or '?'} | "
            f"auth={self.auth_var.get().strip() or 'NONE'}, interface={self.interface_var.get().strip() or 'HDLC'}"
        )

    def _open_settings_window(self, title: str, rows: list[dict[str, object]]) -> None:
        window = tk.Toplevel(self)
        window.title(title)
        window.transient(self)
        window.grab_set()
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        for col in range(2):
            frame.columnconfigure(col, weight=1 if col == 1 else 0)

        for idx, row in enumerate(rows):
            ttk.Label(frame, text=row["label"]).grid(row=idx, column=0, sticky="w", padx=(0, 8), pady=3)
            kind = row["kind"]
            var = row["var"]
            if kind == "combo":
                widget = ttk.Combobox(frame, textvariable=var, values=row["values"], state="readonly")
                widget.grid(row=idx, column=1, sticky="ew", pady=3)
            elif kind == "check":
                widget = ttk.Checkbutton(frame, variable=var)
                widget.grid(row=idx, column=1, sticky="w", pady=3)
            else:
                options = {"textvariable": var}
                if row.get("show"):
                    options["show"] = row["show"]
                widget = ttk.Entry(frame, **options)
                widget.grid(row=idx, column=1, sticky="ew", pady=3)

        footer = ttk.Frame(frame)
        footer.grid(row=len(rows), column=0, columnspan=2, sticky="e", pady=(8, 0))

        def save_and_close() -> None:
            self._update_settings_summary()
            window.destroy()

        ttk.Button(footer, text="Close", command=save_and_close).pack(side=tk.RIGHT)

    def _open_serial_settings(self) -> None:
        self._refresh_ports()
        self._open_settings_window(
            "Serial / COM settings",
            [
                {"label": "Port", "var": self.port_var, "kind": "combo", "values": self.serial_ports},
                {"label": "Baud rate", "var": self.baud_var, "kind": "entry"},
                {"label": "Data bits", "var": self.data_bits_var, "kind": "entry"},
                {"label": "Parity", "var": self.parity_var, "kind": "combo", "values": ["NONE", "EVEN", "ODD", "MARK", "SPACE"]},
                {"label": "Stop bits", "var": self.stop_bits_var, "kind": "combo", "values": ["1", "2"]},
            ],
        )

    def _open_address_settings(self) -> None:
        self._open_settings_window(
            "DLMS addressing settings",
            [
                {"label": "Client address", "var": self.client_addr_var, "kind": "entry"},
                {"label": "Server raw address", "var": self.server_addr_var, "kind": "entry"},
                {"label": "Logical server", "var": self.logical_server_var, "kind": "entry"},
                {"label": "Physical server", "var": self.physical_server_var, "kind": "entry"},
                {"label": "Address type", "var": self.address_type_var, "kind": "combo", "values": ["DEFAULT", "1_BYTE", "2_BYTE", "4_BYTE"]},
                {"label": "Broadcast", "var": self.broadcast_var, "kind": "check"},
                {"label": "Use LN referencing", "var": self.ln_ref_var, "kind": "check"},
            ],
        )

    def _open_security_settings(self) -> None:
        self._open_settings_window(
            "Security and session settings",
            [
                {"label": "Authentication", "var": self.auth_var, "kind": "combo", "values": ["NONE", "LOW", "HIGH", "HIGH_MD5", "HIGH_SHA1", "HIGH_GMAC", "HIGH_SHA256"]},
                {"label": "Password / secret", "var": self.password_var, "kind": "entry", "show": "*"},
                {"label": "Wait time (HH:MM:SS)", "var": self.wait_time_var, "kind": "entry"},
                {"label": "Resend count", "var": self.resend_count_var, "kind": "entry"},
                {"label": "Inactivity timeout", "var": self.inactivity_timeout_var, "kind": "entry"},
                {"label": "Trace level", "var": self.trace_var, "kind": "combo", "values": ["INFO", "WARNING", "ERROR", "DEBUG"]},
            ],
        )

    def _open_link_settings(self) -> None:
        self._open_settings_window(
            "HDLC and profile settings",
            [
                {"label": "Interface", "var": self.interface_var, "kind": "combo", "values": ["HDLC", "HDLC_WITH_MODE_E", "WRAPPER", "PLC", "PLC_HDLC"]},
                {"label": "Standard", "var": self.standard_var, "kind": "combo", "values": ["DLMS", "IDIS", "INDIA", "ITALY", "SAUDI_ARABIA"]},
                {"label": "HDLC window size", "var": self.window_var, "kind": "entry"},
                {"label": "HDLC frame size", "var": self.frame_var, "kind": "entry"},
                {"label": "Manufacturer ID", "var": self.manufacturer_var, "kind": "entry"},
            ],
        )

    def _refresh_ports(self) -> None:
        ports = self.service.list_serial_ports()
        self.serial_ports = ports
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
            self._update_settings_summary()
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
        self._update_settings_summary()

    def _disconnect(self) -> None:
        def work():
            self._collect_config().save(self.config_path)
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
        self.app_config.object_tree = [
            {
                "object_type": obj.object_type,
                "object_type_id": obj.object_type_id,
                "short_name": obj.short_name,
                "logical_name": obj.logical_name,
                "version": obj.version,
                "description": obj.description,
            }
            for obj in objects
        ]
        self.app_config.save(self.config_path)
        self.status_var.set(f"Loaded {len(objects)} objects")

    def _restore_cached_tree(self) -> None:
        cached = self.app_config.object_tree or []
        if not cached:
            return
        self.tree.delete(*self.tree.get_children())
        self.type_nodes.clear()
        self.node_to_ln.clear()
        for item in sorted(cached, key=lambda x: (int(x.get("object_type_id", 0)), str(x.get("logical_name", "")))):
            object_type = str(item.get("object_type", "Unknown"))
            parent = self.type_nodes.get(object_type)
            if not parent:
                parent = self.tree.insert("", "end", text=object_type, values=("", ""), open=False)
                self.type_nodes[object_type] = parent
            short_name = int(item.get("short_name", 0))
            version = int(item.get("version", 0))
            label = f"v{version} / SN {short_name}" if short_name else f"v{version}"
            logical_name = str(item.get("logical_name", ""))
            node = self.tree.insert(parent, "end", text=label, values=(logical_name, str(item.get("description", ""))))
            if logical_name:
                self.node_to_ln[node] = logical_name
        self.status_var.set(f"Loaded cached tree ({len(cached)} objects)")

    def _show_attributes(self, logical_name: str, attrs) -> None:
        for child in self.details_frame.winfo_children():
            child.destroy()
        self.current_logical_name = logical_name
        self.attribute_vars.clear()
        self.details_title_var.set(f"Logical Name: {logical_name}")

        ttk.Label(self.details_frame, text="Attribute", font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        ttk.Label(self.details_frame, text="Value", font=("TkDefaultFont", 9, "bold")).grid(row=0, column=1, sticky="w", pady=(0, 4))
        self.details_frame.columnconfigure(1, weight=1)

        writable_count = 0
        for row_idx, item in enumerate(attrs, start=1):
            if len(item) >= 3:
                index, value, is_writable = item[0], item[1], bool(item[2])
            else:
                index, value, is_writable = item[0], item[1], True
            ttk.Label(self.details_frame, text=str(index)).grid(row=row_idx, column=0, sticky="nw", padx=(0, 8), pady=3)
            var = tk.StringVar(value=self._format_attribute_value(value))
            entry = ttk.Entry(self.details_frame, textvariable=var)
            entry.grid(row=row_idx, column=1, sticky="ew", pady=3)
            if is_writable:
                self.attribute_vars[int(index)] = var
                writable_count += 1
            else:
                entry.state(["readonly"])

        self.write_button.configure(state=tk.NORMAL if self.attribute_vars else tk.DISABLED)
        readonly_count = len(attrs) - writable_count
        self.status_var.set(
            f"Attributes loaded for {logical_name}. Writable: {writable_count}, read-only: {readonly_count}"
        )

    def _clear_tree_and_details(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.type_nodes.clear()
        self.node_to_ln.clear()
        for child in self.details_frame.winfo_children():
            child.destroy()
        self.attribute_vars.clear()
        self.current_logical_name = None
        self.details_title_var.set("Select object to load attributes")
        self.write_button.configure(state=tk.DISABLED)

    @staticmethod
    def _format_attribute_value(value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    def _on_details_frame_configure(self, _event=None) -> None:
        self.details_canvas.configure(scrollregion=self.details_canvas.bbox("all"))

    def _on_details_canvas_configure(self, event=None) -> None:
        if event is not None:
            self.details_canvas.itemconfigure(self.details_canvas_window, width=event.width)

    def _write_attributes(self) -> None:
        logical_name = self.current_logical_name
        if not logical_name:
            messagebox.showwarning("Write attributes", "Select an object first.")
            return
        values = {index: var.get() for index, var in self.attribute_vars.items()}

        def work():
            self.service.write_object_attributes(logical_name, values)
            return logical_name, self.service.read_object_attributes(logical_name), "write_ok"

        self._run_worker(f"Writing attributes for {logical_name}...", work)

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
                elif isinstance(payload, tuple) and len(payload) == 3 and payload[2] == "write_ok":
                    self._show_attributes(payload[0], payload[1])
                    self.status_var.set(f"Attributes written for {payload[0]}")
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
