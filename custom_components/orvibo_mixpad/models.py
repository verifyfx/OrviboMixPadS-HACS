"""Strict inventory and state models, independent of Home Assistant."""

from __future__ import annotations

import ipaddress
import math
import time
from dataclasses import dataclass


def private_ipv4(value):
    """Accept only explicit LAN IPv4 endpoints; no DNS/URLs or public targets."""
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError, ipaddress.AddressValueError):
        return None
    networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    return str(address) if any(address in ipaddress.ip_network(n) for n in networks) else None


@dataclass(frozen=True)
class Relay:
    """Only proven type-1 relay endpoints are admitted."""

    uid: str
    device_id: str
    endpoint: int
    name: str

    @property
    def key(self):
        return (self.uid, self.device_id, self.endpoint)

    @classmethod
    def from_row(cls, row):
        if not isinstance(row, dict) or type(row.get("deviceType")) is not int or row["deviceType"] != 1:
            raise ValueError("Only deviceType 1 relays are supported")
        uid, device_id, endpoint = row.get("uid"), row.get("deviceId"), row.get("endpoint")
        if (not isinstance(uid, str) or not uid or len(uid) > 128
                or not isinstance(device_id, str) or not device_id or len(device_id) > 128
                or type(endpoint) is not int or not 0 <= endpoint <= 255):
            raise ValueError("Relay requires UID, device ID and actual endpoint")
        name = row.get("deviceName")
        return cls(uid, device_id, endpoint, name if isinstance(name, str) else "Relay")

    def as_row(self):
        return {"uid": self.uid, "deviceId": self.device_id, "endpoint": self.endpoint,
                "deviceName": self.name, "deviceType": 1}


@dataclass
class State:
    """Preserve newer local evidence when applying delayed cloud snapshots."""

    on: bool | None = None
    assumed: bool = True
    source: str | None = None
    revision: int = 0
    local_at: float = 0
    local_wall: float = 0
    cloud_at: float = 0
    pending: bool = False

    def reset(self):
        self.on, self.assumed, self.source = None, True, None
        self.revision += 1

    def mark_local(self):
        self.local_at, self.local_wall = time.monotonic(), time.time()

    def push(self, value):
        if type(value) is not int or value not in (0, 1):
            return
        self.on, self.assumed, self.source = value == 0, False, "local_push"
        self.revision += 1
        self.mark_local()

    def cloud(self, row, started):
        if self.pending or self.local_at >= started or type(row.get("value1")) is not int:
            return False
        if row["value1"] not in (0, 1):
            return False
        try:
            updated = float(row.get("updateTimeSec", 0))
        except (ValueError, TypeError):
            return False
        if not math.isfinite(updated) or updated <= max(self.local_wall, self.cloud_at):
            return False
        self.on, self.assumed, self.source = row["value1"] == 0, True, "cloud_snapshot"
        self.cloud_at = updated
        return True


def inventory(data):
    """Parse supported inventory without inferring endpoints or gateway ownership."""
    if not isinstance(data, dict):
        raise ValueError("Invalid inventory")
    for name in ("device", "gateway", "deviceStatus"):
        if not isinstance(data.get(name, []), list):
            raise ValueError("Invalid inventory table")
        if any(not isinstance(row, dict) for row in data.get(name, [])):
            raise ValueError("Invalid inventory row")
    devices = data.get("device", [])
    mixpads = {r.get("uid") for r in devices if r.get("deviceType") == 114 and r.get("uid")}
    relays = {}
    for row in devices:
        try:
            relay = Relay.from_row(row)
        except ValueError:
            continue
        if relay.uid in mixpads:
            relays[relay.key] = relay
    hosts = {}
    for row in data.get("gateway", []):
        uid = row.get("uid")
        if uid not in mixpads:
            continue
        # Upstream documents localStaticIP, including optional :port suffix.
        value = row.get("localStaticIP") or row.get("ip")
        host = private_ipv4(value.split(":", 1)[0]) if isinstance(value, str) else None
        if host:
            hosts[uid] = host
    return relays, hosts
