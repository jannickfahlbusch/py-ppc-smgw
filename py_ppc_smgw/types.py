from dataclasses import dataclass
from datetime import datetime


@dataclass
class Reading:
    value: str
    timestamp: datetime
    obis: str


type OBISCode = str


@dataclass
class Meter:
    mid: str
    name: str


@dataclass
class MeterEntry:
    value: float
    unit: int
    scaler: int
    status: int
    capture_time: datetime
    obis: OBISCode
    signature: str

    @property
    def value_kwh(self) -> float:
        raw: float = self.value * (10**self.scaler)
        if self.unit == 30:  # Wh
            return raw / 1000.0
        return raw


@dataclass
class TariffProfile:
    tid: str
    name: str


@dataclass
class FirmwareVersion:
    component: str
    version: str
    checksum: str


@dataclass
class LogEntry:
    record_number: int
    timestamp: datetime
    level: str
    vendor_id: str
    event_id: int
    outcome: str


@dataclass
class DeviceInfo:
    firmware_versions: list[FirmwareVersion]
    tariff_profiles: list[TariffProfile]
