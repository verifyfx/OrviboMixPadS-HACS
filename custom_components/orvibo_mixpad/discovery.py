"""Bounded UDP cmd86 discovery, researched from upstream MIT implementation.

UDP announcements use a public bootstrap key and are NOT authenticated identity.
Only match known inventory UIDs; a TCP handshake must subsequently confirm UID.
"""

import asyncio
import secrets
import socket

from .models import private_ipv4
from .protocol import ProtocolError, decode, encode


class Discovery(asyncio.DatagramProtocol):
    def __init__(self, known):
        self.known = set(known)
        self.candidates = {}
        self.conflicts = set()

    def datagram_received(self, data, addr):
        host = private_ipv4(addr[0])
        if not host or len(data) > 8192:
            return
        try:
            message = decode(data, bootstrap=True)
        except ProtocolError:
            return
        uid = message.get("uid")
        if not isinstance(uid, str) or uid not in self.known:
            return
        if uid in self.candidates and self.candidates[uid] != host:
            self.conflicts.add(uid)
        if uid not in self.conflicts:
            self.candidates[uid] = host


def request_packet():
    serial = secrets.randbelow(1000000000)
    return encode({"cmd": 86, "serial": serial, "uniSerial": serial,
                   "clientType": 1, "serverRecord": False, "ver": "5.1.3.309"})


async def discover(known, timeout=2):
    if not known:
        return {}
    protocol = Discovery(known)
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: protocol, family=socket.AF_INET, local_addr=("0.0.0.0", 0), allow_broadcast=True)
    try:
        transport.sendto(request_packet(), ("255.255.255.255", 10000))
        await asyncio.sleep(min(5, max(0, timeout)))
        return {uid: host for uid, host in protocol.candidates.items() if uid not in protocol.conflicts}
    finally:
        transport.close()
