from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SerialConfig:
    port: str = "COM1"
    baud_rate: int = 9600
    data_bits: int = 8
    parity: str = "NONE"
    stop_bits: int = 1


@dataclass
class DlmsConfig:
    client_address: int = 16
    server_address: int = 1
    logical_server: int = 1
    physical_server: int = 1
    address_type: str = "DEFAULT"
    broadcast: bool = False
    wait_time: str = "00:00:05"
    resend_count: int = 2
    inactivity_timeout: str = "00:00:40"
    use_logical_name_referencing: bool = True
    authentication: str = "NONE"
    password: str = ""
    interface_type: str = "HDLC"
    trace_level: str = "INFO"
    hdlc_window_size: int = 1
    hdlc_frame_size: int = 436
    manufacturer_id: str = ""
    standard: str = "DLMS"
    invocation_counter_ln: str = ""


@dataclass
class AppConfig:
    serial: SerialConfig = field(default_factory=SerialConfig)
    dlms: DlmsConfig = field(default_factory=DlmsConfig)

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        path = Path(path)
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            serial=SerialConfig(**data.get("serial", {})),
            dlms=DlmsConfig(**data.get("dlms", {})),
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
