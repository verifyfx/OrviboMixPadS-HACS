"""Panel-first onboarding: explicit IP plus account-owned supported inventory."""

from copy import deepcopy

from .local import Gateway
from .models import private_ipv4
from .protocol import ProtocolError


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
