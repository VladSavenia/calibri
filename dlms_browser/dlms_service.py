from __future__ import annotations

import threading
import time
import ast
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any, Callable

from gurux_common.io import Parity, StopBits
from gurux_dlms import GXReplyData
from gurux_dlms.enums import (
    AccessMode,
    Authentication,
    Conformance,
    DataType,
    InterfaceType,
    ObjectType,
    Security,
    Standard,
)
from gurux_dlms.objects import (
    GXDLMSAssociationLogicalName,
    GXDLMSAssociationShortName,
    GXDLMSDemandRegister,
    GXDLMSObject,
    GXDLMSExtendedRegister,
    GXDLMSProfileGeneric,
    GXDLMSRegister,
)
from gurux_dlms.secure import GXDLMSSecureClient
from gurux_serial import GXSerial

from .config import AppConfig

PARITY_MAP = {
    "NONE": Parity.NONE,
    "EVEN": Parity.EVEN,
    "ODD": Parity.ODD,
    "MARK": getattr(Parity, "MARK", Parity.NONE),
    "SPACE": getattr(Parity, "SPACE", Parity.NONE),
}

STOP_BITS_MAP = {
    1: StopBits.ONE,
    2: StopBits.TWO,
}

AUTH_MAP = {
    "NONE": Authentication.NONE,
    "LOW": Authentication.LOW,
    "HIGH": Authentication.HIGH,
    "HIGH_MD5": Authentication.HIGH_MD5,
    "HIGH_SHA1": Authentication.HIGH_SHA1,
    "HIGH_GMAC": Authentication.HIGH_GMAC,
    "HIGH_SHA256": Authentication.HIGH_SHA256,
    "HIGH_ECDSA": getattr(Authentication, "HIGH_ECDSA", Authentication.HIGH),
}

INTERFACE_MAP = {
    "HDLC": InterfaceType.HDLC,
    "HDLC_WITH_MODE_E": getattr(InterfaceType, "HDLC_WITH_MODE_E", InterfaceType.HDLC),
    "WRAPPER": getattr(InterfaceType, "WRAPPER", InterfaceType.HDLC),
    "PLC": getattr(InterfaceType, "PLC", InterfaceType.HDLC),
    "PLC_HDLC": getattr(InterfaceType, "PLC_HDLC", InterfaceType.HDLC),
}

STANDARD_MAP = {
    "DLMS": Standard.DLMS,
    "INDIA": getattr(Standard, "INDIA", Standard.DLMS),
    "ITALY": getattr(Standard, "ITALY", Standard.DLMS),
    "SAUDI_ARABIA": getattr(Standard, "SAUDI_ARABIA", Standard.DLMS),
    "IDIS": getattr(Standard, "IDIS", Standard.DLMS),
}

ADDRESS_SIZE_MAP = {
    "DEFAULT": 0,
    "AUTO": 0,
    "1_BYTE": 1,
    "2_BYTE": 2,
    "4_BYTE": 4,
}

OBJECT_TYPE_NAME_MAP = {
    1: "Data",
    3: "Register",
    4: "Extended Register",
    5: "Demand Register",
    6: "Register Activation",
    7: "Profile Generic",
    8: "Clock",
    9: "Script Table",
    10: "Schedule",
    11: "Special Days Table",
    12: "Association SN",
    15: "Association LN",
    17: "SAP Assignment",
    18: "Image Transfer",
    19: "IEC Local Port Setup",
    20: "Activity Calendar",
    21: "Register Monitor",
    22: "Action Schedule",
    23: "IEC HDLC Setup",
    24: "IEC Twisted Pair Setup",
    25: "M-Bus Slave Port Setup",
    26: "Utility Tables",
    27: "Modem Configuration",
    28: "Auto Connect",
    29: "Auto Answer",
    40: "Push Setup",
    41: "TCP UDP Setup",
    42: "IPv4 Setup",
    43: "MAC Address Setup",
    44: "PPP Setup",
    45: "GPRS Setup",
    46: "SMTP Setup",
    47: "GSM Diagnostic",
    48: "IP6 Setup",
    49: "Register Table",
    61: "Compact Data",
    62: "Tariff Plan",
    63: "Account",
    64: "Credit",
    65: "Charge",
    66: "Token Gateway",
    67: "Parameter Monitor",
    68: "Compact Data",
    70: "Disconnect Control",
    71: "Limiter",
    72: "MBus Client",
    73: "Wireless Mode Q Channel",
    74: "MBus Master Port Setup",
    76: "Llc Sscs Setup",
    80: "Security Setup",
    81: "Arbitrator",
    82: "Disconnect Control",
    90: "NTP Setup",
    91: "Message Handler",
    92: "Push Setup",
    93: "Data Protection",
    94: "Account Setup",
}


def _hexify(data: Any) -> str:
    if data is None:
        return "<none>"
    if isinstance(data, str):
        return data
    if isinstance(data, (bytes, bytearray)):
        return " ".join(f"{b:02X}" for b in data)
    if hasattr(data, "__iter__") and not isinstance(data, (dict, list, tuple, set)):
        try:
            return " ".join(f"{int(b) & 0xFF:02X}" for b in data)
        except Exception:
            return str(data)
    return str(data)


def _parse_time_to_ms(value: str, default_ms: int) -> int:
    text = (value or "").strip()
    if not text:
        return default_ms
    if ":" not in text:
        return max(int(float(text) * 1000), 1)
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError("Time value must be in HH:MM:SS format or seconds.")
    hours, minutes, seconds = (int(p) for p in parts)
    total_seconds = (hours * 3600) + (minutes * 60) + seconds
    return max(total_seconds * 1000, 1)


def _parse_wait_time_to_ms(value: str) -> int:
    return _parse_time_to_ms(value, 5000)


def _parse_secret(value: str) -> str | bytes | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.lower().startswith("0x"):
        return bytes.fromhex(text[2:])
    return text


def _parse_attribute_input(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    try:
        return ast.literal_eval(text)
    except Exception:
        return value


def _enum_to_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        pass
    if isinstance(value, IntEnum):
        return int(value.value)
    raw_value = getattr(value, "value", None)
    if raw_value is not None:
        try:
            return int(raw_value)
        except Exception:
            pass
    text = str(value)
    digits = ''.join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 999999


def _object_type_display(value: Any) -> tuple[int, str]:
    object_id = _enum_to_int(value)
    pretty = OBJECT_TYPE_NAME_MAP.get(object_id)
    if pretty:
        return object_id, f"{object_id:>3} - {pretty}"
    text = str(value).replace('_', ' ').title()
    return object_id, f"{object_id:>3} - {text}"


def _is_writable_access_mode(access_mode: Any) -> bool:
    if access_mode in (AccessMode.WRITE, AccessMode.READ_WRITE, AccessMode.AUTHENTICATED_WRITE, AccessMode.AUTHENTICATED_READ_WRITE):
        return True
    mode_name = str(getattr(access_mode, "name", access_mode)).upper().replace("-", "_")
    if mode_name in {"WRITE", "READ_WRITE", "AUTHENTICATED_WRITE", "AUTHENTICATED_READ_WRITE"}:
        return True
    try:
        raw_value = getattr(access_mode, "value", access_mode)
        mode_value = int(raw_value)
    except Exception:
        return False
    return mode_value in (
        int(AccessMode.WRITE),
        int(AccessMode.READ_WRITE),
        int(AccessMode.AUTHENTICATED_WRITE),
        int(AccessMode.AUTHENTICATED_READ_WRITE),
    )


def _access_mode_is_known(access_mode: Any) -> bool:
    try:
        return int(access_mode) >= 0
    except Exception:
        return False


def _get_attribute_access(obj: GXDLMSObject, index: int) -> tuple[Any, bool]:
    if index == 1:
        return AccessMode.READ, True
    attributes = getattr(obj, "attributes", None)
    if attributes is None or not hasattr(attributes, "find"):
        return obj.getAccess(index), False
    attribute_access = attributes.find(index)
    if attribute_access is None:
        return obj.getAccess(index), False
    return attribute_access.access, True


def _format_attribute_access(access_mode: Any, access_known: bool) -> str:
    if not access_known:
        return f"Unknown ({access_mode})"
    return str(access_mode)


@dataclass
class DlmsObjectInfo:
    object_type: str
    object_type_id: int
    short_name: int
    logical_name: str
    version: int
    description: str


class SimpleGXDLMSReader:
    """Small GUI-oriented wrapper derived from Gurux example client logic."""

    def __init__(
        self,
        client: GXDLMSSecureClient,
        media: GXSerial,
        wait_time_ms: int = 5000,
        resend_count: int = 2,
        logger: Callable[[str, str], None] | None = None,
    ):
        self.client = client
        self.media = media
        self.wait_time = wait_time_ms
        self.resend_count = max(int(resend_count), 0)
        self.logger = logger or (lambda _kind, _msg: None)
        self.last_activity_monotonic = time.monotonic()

    def _log(self, kind: str, message: str) -> None:
        self.logger(kind, message)

    def _touch_activity(self) -> None:
        self.last_activity_monotonic = time.monotonic()

    def seconds_since_activity(self) -> float:
        return max(time.monotonic() - self.last_activity_monotonic, 0.0)

    def close(self) -> None:
        if self.media and self.media.isOpen():
            self._log("event", "Closing DLMS session.")
            try:
                if self.client.ciphering and self.client.ciphering.security != Security.NONE:
                    reply = GXReplyData()
                    self.read_data_block(self.client.releaseRequest(), reply)
            except Exception as exc:
                self._log("event", f"Release request failed: {exc}")
            try:
                reply = GXReplyData()
                self.read_dlms_packet(self.client.disconnectRequest(), reply)
            except Exception as exc:
                self._log("event", f"Disconnect request failed: {exc}")
            try:
                self.media.close()
                self._log("event", "Serial port closed.")
            except Exception as exc:
                self._log("event", f"Failed to close serial port: {exc}")

    def _receive_parameters(self):
        from gurux_common import ReceiveParameters

        p = ReceiveParameters()
        p.eop = 0x7E
        p.allData = True
        p.waitTime = self.wait_time
        p.count = 5
        return p

    def read_dlms_packet(self, data: Any, reply: GXReplyData | None = None) -> GXReplyData:
        from gurux_common import TimeoutException
        from gurux_dlms import GXByteBuffer, GXDLMSException

        if reply is None:
            reply = GXReplyData()

        if isinstance(data, (list, tuple)):
            for frame in data:
                reply.clear()
                self.read_dlms_packet(frame, reply)
            return reply

        if not data:
            self._log("event", "Skipping empty DLMS frame.")
            return reply

        p = self._receive_parameters()
        rd = GXByteBuffer()
        notify = GXReplyData()
        max_attempts = 1 + self.resend_count

        with self.media.getSynchronous():
            self._log("tx", _hexify(data))
            self.media.send(data)
            self._touch_activity()
            attempt = 1
            while not self.client.getData(rd, reply, notify):
                while not self.media.receive(p):
                    if attempt >= max_attempts:
                        raise TimeoutException("Failed to receive reply from the meter.")
                    attempt += 1
                    self._log("event", f"No reply from meter. Retry {attempt - 1}/{self.resend_count}.")
                    self._log("tx", _hexify(data))
                    self.media.send(data)
                    self._touch_activity()
                if p.reply is not None:
                    self._log("rx", _hexify(p.reply))
                    rd.set(p.reply)
                    self._touch_activity()
                p.reply = None

        if rd.size:
            self._log("frame", f"Accumulated RX length: {rd.size} byte(s)")
        if reply.error != 0:
            raise GXDLMSException(reply.error)
        return reply

    def read_data_block(self, data: Any, reply: GXReplyData) -> bool:
        if not data:
            return True
        if isinstance(data, (list, tuple)):
            for frame in data:
                reply.clear()
                self.read_data_block(frame, reply)
            return reply.error == 0
        self.read_dlms_packet(data, reply)
        while reply.isMoreData():
            more = None if reply.isStreaming() else self.client.receiverReady(reply)
            self._log("event", "Meter indicates more data. Requesting next block.")
            self.read_dlms_packet(more, reply)
        return reply.error == 0

    def initialize_connection(self) -> None:
        self._log("event", "Starting DLMS connection sequence.")
        reply = GXReplyData()
        data = self.client.snrmRequest()
        if data:
            self._log("event", "Sending SNRM request.")
            self.read_dlms_packet(data, reply)
            self.client.parseUAResponse(reply.data)
            self._log(
                "event",
                f"UA response parsed successfully. HDLC window={self.client.hdlcSettings.windowSizeTX}, frame={self.client.hdlcSettings.maxInfoTX}.",
            )
        reply.clear()
        self._log("event", "Sending AARQ request.")
        self.read_data_block(self.client.aarqRequest(), reply)
        self.client.parseAareResponse(reply.data)
        self._log("event", "AARE response parsed successfully.")
        if self.client.authentication > Authentication.LOW:
            reply.clear()
            self._log("event", "Authenticating.")
            for frame in self.client.getApplicationAssociationRequest():
                self.read_dlms_packet(frame, reply)
            self.client.parseApplicationAssociationResponse(reply.data)
            self._log("event", "Application association established.")
        self._touch_activity()

    def keep_alive(self) -> None:
        """Use a safe application-level keep-alive.

        Raw HDLC keepAlive supervisory frames are known to fail with many meters.
        A more compatible approach is to read attribute 1 (logical name) of the
        current association object.
        """
        self._log("event", "Sending application keep-alive request.")

        target = None
        if getattr(self.client, "objects", None):
            try:
                if self.client.useLogicalNameReferencing:
                    target = self.client.objects.findByLN(ObjectType.ASSOCIATION_LOGICAL_NAME, "0.0.40.0.0.255")
                else:
                    target = self.client.objects.findByLN(ObjectType.ASSOCIATION_SHORT_NAME, "0.0.40.0.0.255")
            except Exception:
                target = None

        if target is None:
            try:
                if self.client.useLogicalNameReferencing:
                    target = GXDLMSAssociationLogicalName("0.0.40.0.0.255")
                else:
                    target = GXDLMSAssociationShortName()
            except Exception as exc:
                raise RuntimeError(f"Unable to build association keep-alive object: {exc}")

        data = self.client.read(target, 1)
        if isinstance(data, (list, tuple)) and len(data) == 1:
            data = data[0]
        reply = GXReplyData()
        self.read_data_block(data, reply)
        try:
            self.client.updateValue(target, 1, reply.value)
        except Exception:
            pass
        self._log("event", "Keep-alive reply received.")

    def get_association_view(self) -> None:
        self._log("event", "Reading association view.")
        reply = GXReplyData()
        self.read_data_block(self.client.getObjectsRequest(), reply)
        self.client.parseObjects(reply.data, True, False)
        self._log("event", f"Association view loaded: {len(self.client.objects)} object(s).")

    def read(self, item: Any, attribute_index: int) -> Any:
        self._log("event", f"Reading attribute {attribute_index} of {getattr(item, 'logicalName', '<unknown>')}.")
        data = self.client.read(item, attribute_index)[0]
        reply = GXReplyData()
        self.read_data_block(data, reply)
        if item.getDataType(attribute_index) == DataType.NONE:
            item.setDataType(attribute_index, reply.valueType)
        return self.client.updateValue(item, attribute_index, reply.value)

    def read_scaler_and_units(self) -> None:
        objs = self.client.objects.getObjects(
            [ObjectType.REGISTER, ObjectType.EXTENDED_REGISTER, ObjectType.DEMAND_REGISTER]
        )
        self._log("event", f"Reading scaler/unit data for {len(objs)} register-like object(s).")
        for obj in objs:
            try:
                if isinstance(obj, (GXDLMSRegister, GXDLMSExtendedRegister)) and obj.canRead(3):
                    self.read(obj, 3)
                elif isinstance(obj, GXDLMSDemandRegister) and obj.canRead(4):
                    self.read(obj, 4)
            except Exception as exc:
                self._log("event", f"Scaler/unit read skipped for {getattr(obj, 'logicalName', '<unknown>')}: {exc}")

    def read_profile_generic_columns(self) -> None:
        profiles = self.client.objects.getObjects(ObjectType.PROFILE_GENERIC)
        self._log("event", f"Reading columns for {len(profiles)} profile generic object(s).")
        for pg in profiles:
            try:
                if isinstance(pg, GXDLMSProfileGeneric) and pg.canRead(3):
                    self.read(pg, 3)
            except Exception as exc:
                self._log("event", f"Profile columns read skipped for {getattr(pg, 'logicalName', '<unknown>')}: {exc}")


class DlmsBrowserService:
    def __init__(self, config: AppConfig, logger: Callable[[str, str], None] | None = None):
        self.config = config
        self.logger = logger or (lambda _kind, _msg: None)
        self.media: GXSerial | None = None
        self.client: GXDLMSSecureClient | None = None
        self.reader: SimpleGXDLMSReader | None = None
        self._keepalive_thread: threading.Thread | None = None
        self._keepalive_stop = threading.Event()

    def _log(self, kind: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logger(kind, f"[{timestamp}] {message}")

    @staticmethod
    def list_serial_ports() -> list[str]:
        try:
            return list(GXSerial.getPortNames())
        except Exception:
            try:
                from serial.tools import list_ports
                return [p.device for p in list_ports.comports()]
            except Exception:
                return []

    def _resolve_server_address(self, client: GXDLMSSecureClient) -> int:
        from gurux_dlms import GXDLMSClient

        dlms = self.config.dlms
        logical = int(dlms.logical_server)
        physical = int(dlms.physical_server)
        address_size = ADDRESS_SIZE_MAP.get(dlms.address_type.strip().upper(), 0)
        broadcast = bool(dlms.broadcast)

        methods_to_try: list[tuple[str, tuple[Any, ...]]] = []
        if address_size:
            methods_to_try.extend(
                [
                    ("getServerAddress", (logical, physical, address_size, broadcast)),
                    ("getServerAddress", (logical, physical, address_size)),
                    ("getServerAddress2", (logical, physical, address_size, broadcast)),
                    ("getServerAddress2", (logical, physical, address_size)),
                ]
            )
        methods_to_try.extend(
            [
                ("getServerAddress", (logical, physical, broadcast)),
                ("getServerAddress", (logical, physical)),
                ("getServerAddress2", (logical, physical, 0, broadcast)),
                ("getServerAddress2", (logical, physical, 0)),
            ]
        )

        for method_name, args in methods_to_try:
            method = getattr(GXDLMSClient, method_name, None)
            if not callable(method):
                continue
            try:
                value = int(method(*args))
                self._log(
                    "event",
                    f"Server address resolved from logical={logical}, physical={physical}, address_type={dlms.address_type}, broadcast={broadcast}: {value}.",
                )
                return value
            except TypeError:
                continue
            except Exception as exc:
                self._log("event", f"Server address helper {method_name}{args} failed: {exc}")

        fallback = int(dlms.server_address)
        self._log(
            "event",
            f"Falling back to raw server address {fallback}. Could not compose address from logical/physical settings.",
        )
        return fallback

    def _build_client(self) -> GXDLMSSecureClient:
        dlms = self.config.dlms
        auth_name = dlms.authentication.strip().upper()
        interface_name = dlms.interface_type.strip().upper()
        standard_name = dlms.standard.strip().upper()
        password = _parse_secret(dlms.password)

        client = GXDLMSSecureClient(
            dlms.use_logical_name_referencing,
            dlms.client_address,
            dlms.server_address,
            AUTH_MAP[auth_name],
            password,
            INTERFACE_MAP[interface_name],
        )
        client.serverAddress = self._resolve_server_address(client)
        dlms.server_address = int(client.serverAddress)
        client.standard = STANDARD_MAP[standard_name]
        client.hdlcSettings.windowSizeRX = dlms.hdlc_window_size
        client.hdlcSettings.windowSizeTX = dlms.hdlc_window_size
        client.hdlcSettings.maxInfoRX = dlms.hdlc_frame_size
        client.hdlcSettings.maxInfoTX = dlms.hdlc_frame_size
        if dlms.manufacturer_id:
            client.manufacturerId = dlms.manufacturer_id
        client.proposedConformance |= Conformance.MULTIPLE_REFERENCES
        secret_mode = "hex-bytes" if isinstance(password, (bytes, bytearray)) else ("text" if password else "empty")
        self._log(
            "event",
            f"DLMS client built: client={dlms.client_address}, server={client.serverAddress}, auth={auth_name}, interface={interface_name}, LN={dlms.use_logical_name_referencing}, wait={dlms.wait_time}, resend={dlms.resend_count}, inactivity_timeout={dlms.inactivity_timeout}, secret={secret_mode}.",
        )
        return client

    def _build_media(self) -> GXSerial:
        serial_cfg = self.config.serial
        media = GXSerial(None)
        media.port = serial_cfg.port
        media.baudRate = serial_cfg.baud_rate
        media.dataBits = serial_cfg.data_bits
        media.parity = PARITY_MAP[serial_cfg.parity.strip().upper()]
        media.stopBits = STOP_BITS_MAP[serial_cfg.stop_bits]
        self._log(
            "event",
            f"Serial media configured: port={serial_cfg.port}, baud={serial_cfg.baud_rate}, data_bits={serial_cfg.data_bits}, parity={serial_cfg.parity}, stop_bits={serial_cfg.stop_bits}.",
        )
        return media

    def _stop_keepalive(self) -> None:
        self._keepalive_stop.set()
        thread = self._keepalive_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._keepalive_thread = None
        self._keepalive_stop = threading.Event()

    def _keepalive_loop(self, interval_ms: int) -> None:
        check_period = max(min(interval_ms / 4000.0, 1.0), 0.25)
        while not self._keepalive_stop.wait(check_period):
            reader = self.reader
            media = self.media
            if not reader or not media or not media.isOpen():
                continue
            if (reader.seconds_since_activity() * 1000.0) < interval_ms:
                continue
            try:
                idle = reader.seconds_since_activity()
                self._log("event", f"Inactivity timeout reached after {idle:.1f}s. Sending keep-alive request.")
                reader.keep_alive()
            except Exception as exc:
                self._log("event", f"Keep-alive failed: {exc}. Background keep-alive stopped.")
                break

    def _start_keepalive(self) -> None:
        interval_ms = _parse_time_to_ms(self.config.dlms.inactivity_timeout, 40000)
        self._stop_keepalive()
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop,
            args=(interval_ms,),
            daemon=True,
            name="dlms-keepalive",
        )
        self._keepalive_thread.start()
        self._log("event", f"Keep-alive background task started. Interval={self.config.dlms.inactivity_timeout}.")

    def connect(self) -> None:
        self.disconnect()
        self.client = self._build_client()
        self.media = self._build_media()
        wait_time_ms = _parse_wait_time_to_ms(self.config.dlms.wait_time)
        try:
            self._log("event", f"Opening serial port {self.media.port}.")
            self.media.open()
            self._log("event", f"Serial port {self.media.port} opened.")
            self.reader = SimpleGXDLMSReader(
                self.client,
                self.media,
                wait_time_ms=wait_time_ms,
                resend_count=self.config.dlms.resend_count,
                logger=self._log,
            )
            self.reader.initialize_connection()
            self._hydrate_objects_from_config_cache()
            self._log("event", "Keep-alive mode: reading association object attribute 1.")
            self._start_keepalive()
            self._log("event", "Connection established successfully.")
        except Exception:
            self._log("event", "Connection failed. Releasing resources.")
            self.disconnect()
            raise

    def _hydrate_objects_from_config_cache(self) -> None:
        if not self.client:
            return
        cached = getattr(self.config, "object_tree", None) or []
        if not cached:
            return
        self.client.objects.clear()
        hydrated = 0
        for item in cached:
            try:
                object_type_id = int(item.get("object_type_id", 0))
                logical_name = str(item.get("logical_name", ""))
                short_name = int(item.get("short_name", 0))
                version = int(item.get("version", 0))
                if not logical_name:
                    continue
                object_type = ObjectType(object_type_id)
                obj = self.client.createObject(object_type)
                if obj is None:
                    obj = GXDLMSObject(object_type, logical_name, short_name)
                obj.logicalName = logical_name
                obj.shortName = short_name
                obj.version = version
                self.client.objects.append(obj)
                hydrated += 1
            except Exception as exc:
                self._log("event", f"Skipping cached object entry due to parse error: {exc}")
        if hydrated:
            self._log("event", f"Loaded {hydrated} object(s) from cached tree without association read.")

    def disconnect(self) -> None:
        self._stop_keepalive()
        if self.reader:
            try:
                self.reader.close()
            finally:
                self.reader = None
        elif self.media and self.media.isOpen():
            try:
                self._log("event", f"Closing serial port {self.media.port}.")
                self.media.close()
                self._log("event", f"Serial port {self.media.port} closed.")
            except Exception as exc:
                self._log("event", f"Failed to close serial port: {exc}")
        self.media = None
        self.client = None

    def load_objects(self) -> list[DlmsObjectInfo]:
        if not self.reader or not self.client:
            raise RuntimeError("Not connected.")
        self.reader.get_association_view()
        self.reader.read_scaler_and_units()
        self.reader.read_profile_generic_columns()
        result: list[DlmsObjectInfo] = []
        for obj in self.client.objects:
            object_type_id, object_type_display = _object_type_display(getattr(obj, "objectType", ObjectType.NONE))
            result.append(
                DlmsObjectInfo(
                    object_type=object_type_display,
                    object_type_id=object_type_id,
                    short_name=getattr(obj, "shortName", 0),
                    logical_name=getattr(obj, "logicalName", ""),
                    version=getattr(obj, "version", 0),
                    description=getattr(obj, "description", "") or "",
                )
            )
        self._log("event", f"Object list prepared: {len(result)} item(s).")
        return result

    def read_object_attributes(self, logical_name: str) -> list[tuple[int, Any, bool, str]]:
        if not self.reader or not self.client:
            raise RuntimeError("Not connected.")
        obj = self.client.objects.findByLN(ObjectType.NONE, logical_name)
        if not obj:
            self._log(
                "event",
                f"Object {logical_name} not found in current session cache. Reloading association view and retrying.",
            )
            self.reader.get_association_view()
            obj = self.client.objects.findByLN(ObjectType.NONE, logical_name)
        if not obj:
            raise ValueError(
                f"Object {logical_name} not found. Read object tree first or ensure the object exists on the meter."
            )
        values: list[tuple[int, Any, bool, str]] = []
        for index in obj.getAttributeIndexToRead(True):
            access_mode, access_known = _get_attribute_access(obj, index)
            access_known = access_known and _access_mode_is_known(access_mode)
            writable = access_known and _is_writable_access_mode(access_mode)
            access_text = _format_attribute_access(access_mode, access_known)
            try:
                if obj.canRead(index):
                    value = self.reader.read(obj, index)
                    values.append((index, value, writable, access_text))
            except Exception as exc:
                self._log("event", f"Attribute read failed for {logical_name}:{index}: {exc}")
                values.append((index, f"<read error: {exc}>", writable, access_text))
        return values

    def write_object_attributes(self, logical_name: str, values: dict[int, str]) -> None:
        if not self.reader or not self.client:
            raise RuntimeError("Not connected.")
        obj = self.client.objects.findByLN(ObjectType.NONE, logical_name)
        if not obj:
            raise ValueError(f"Object {logical_name} not found. Read object tree first.")

        for index, raw_value in values.items():
            try:
                index = int(index)
                access_mode, access_known = _get_attribute_access(obj, index)
                access_known = access_known and _access_mode_is_known(access_mode)
                if access_known and not _is_writable_access_mode(access_mode):
                    self._log(
                        "event",
                        f"Association reports read-only for {logical_name}:{index} "
                        f"(access={access_mode}). Trying write anyway.",
                    )
                parsed_value = _parse_attribute_input(raw_value)
                self._log("event", f"Writing attribute {index} for {logical_name}.")
                self.client.updateValue(obj, index, parsed_value)
                request = self.client.write(obj, index)
                reply = GXReplyData()
                self.reader.read_data_block(request, reply)
                try:
                    self.client.updateValue(obj, index, parsed_value)
                except Exception:
                    pass
            except Exception as exc:
                details = str(exc)
                if "read-write denied" in details.lower() or "readwritedenied" in details.lower():
                    details = (
                        f"{details}. Meter denied write for this attribute. "
                        "Check authorization/security level and object access rights."
                    )
                raise RuntimeError(f"Failed to write {logical_name}:{index}: {details}") from exc
