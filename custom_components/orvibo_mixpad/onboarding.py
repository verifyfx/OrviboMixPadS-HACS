"""Panel-first onboarding: explicit IP plus account-owned supported inventory."""

from copy import deepcopy

from .local import Gateway
from .models import private_ipv4
from .protocol import ProtocolError


class DuplicatePanelError(ProtocolError):
    """Two supplied addresses were identified as the same panel."""


def panel_addresses(value, *, required=True):
    """Validate all rows before any login; duplicate IP rows are harmless."""
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("Enter a list of MixPad IP addresses")
    hosts = []
    for raw in value:
        if not isinstance(raw, str):
            raise ValueError("Enter private LAN IPv4 addresses")
        host = private_ipv4(raw.strip())
        if not host:
            raise ValueError("Enter private LAN IPv4 addresses")
        if host not in hosts:
            hosts.append(host)
    if required and not hosts:
        raise ValueError("Enter at least one MixPad IP address")
    return hosts


def panel_choices(snapshot):
    """Describe panels by their relay names; users never have to enter a UID."""
    grouped = {}
    for relay in snapshot.relays.values():
        grouped.setdefault(relay.uid, []).append(relay.name)
    return {uid: f"MixPad {index} — {', '.join(names[:3])} ({len(names)} relays)"
            for index, (uid, names) in enumerate(sorted(grouped.items()), 1)}


async def identify_panel(host, data, snapshot):
    """Read-only Hello/login, then match identity or unambiguous cloud address.

    The user supplied this exact trusted IP. Blank identity is not synthesized:
    if cloud has no unique IP match, the flow must ask which account panel it is.
    """
    if not private_ipv4(host):
        raise ValueError("A private LAN IPv4 address is required")
    choices = panel_choices(snapshot)
    if not choices:
        raise ProtocolError("No supported account panels")
    gateway = Gateway(host, None, data["username"], data["password_hash"], trusted_host=True)
    try:
        await gateway.connect()
        peer = gateway.peer_uid
    finally:
        await gateway.close()
    matches = [uid for uid in choices if snapshot.hosts.get(uid) == host]
    if peer:
        if peer not in choices or (len(matches) == 1 and matches[0] != peer):
            raise ProtocolError("Gateway is not the expected account panel")
        return peer
    return matches[0] if len(matches) == 1 else None


async def confirm_panel(host, uid, data):
    """User selection permits blank UID, never a conflicting nonempty UID."""
    gateway = Gateway(host, uid, data["username"], data["password_hash"], trusted_host=True)
    try:
        await gateway.connect()
    finally:
        await gateway.close()


def import_panel(data, snapshot, uid, host, *, selected=None):
    """Persist explicit address trust; import exactly the selected gateway scope."""
    choices = panel_choices(snapshot)
    if uid not in choices or not private_ipv4(host):
        raise ValueError("Panel must belong to the account")
    topology = deepcopy(data["topology"])
    topology["gateways"][uid] = host
    scope = list(dict.fromkeys([*(selected or []), uid]))
    relays = [relay.as_row() for relay in snapshot.relays.values() if relay.uid in scope]
    return topology, scope, relays


class PanelBatch:
    """Resolve multiple supplied IPs atomically using one account snapshot."""

    def __init__(self, hosts, data, snapshot, selected=None):
        self.hosts = panel_addresses(hosts)
        self.data, self.snapshot = deepcopy(data), snapshot
        self.scope = list(selected or [])
        self.seen = set()
        self.index = 0

    @property
    def host(self):
        return self.hosts[self.index] if self.index < len(self.hosts) else None

    @property
    def choices(self):
        return {uid: label for uid, label in panel_choices(self.snapshot).items() if uid not in self.seen}

    def accept(self, uid):
        if uid in self.seen:
            raise DuplicatePanelError("The same MixPad was supplied more than once")
        topology, scope, _ = import_panel(self.data, self.snapshot, uid, self.host, selected=self.scope)
        self.data["topology"], self.scope = topology, scope
        self.seen.add(uid)
        self.index += 1

    async def advance(self):
        """Stop for explicit selection only when the current address is ambiguous."""
        while self.host is not None:
            uid = await identify_panel(self.host, self.data, self.snapshot)
            if uid is None:
                if not self.choices:
                    raise DuplicatePanelError("No remaining account panels match this address")
                return False
            self.accept(uid)
        return True

    async def confirm(self, uid):
        if uid not in self.choices:
            raise DuplicatePanelError("Panel already selected or outside this account")
        await confirm_panel(self.host, uid, self.data)
        self.accept(uid)
