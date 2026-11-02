"""Fake TCP gateway validates framing, identity, push races and lifecycle."""

import asyncio
import contextlib
import time
import unittest

from . import bootstrap  # noqa: F401
from custom_components.orvibo_mixpad.local import Gateway
from custom_components.orvibo_mixpad.models import Relay
from custom_components.orvibo_mixpad.protocol import (
    DEFAULT_KEY, EMPTY_SESSION, AuthenticationError, ProtocolError, decode, encode,
)

UID = "test-gateway"
KEY = b"0123456789abcdef"
SESSION = b"s" * 32
RELAY = Relay(UID, "test-relay", 1, "Test relay")


class FakeGateway:
    def __init__(self):
        self.commands = []
        self.writers = set()
        self.handlers = set()
        self.uid = UID
        self.auth = 0
        self.push = True
        self.ack = True

    async def serve(self, reader, writer):
        self.writers.add(writer)
        self.handlers.add(asyncio.current_task())
        session = EMPTY_SESSION
        try:
            while True:
                head = await reader.readexactly(4)
                frame = head + await reader.readexactly(int.from_bytes(head[2:4], "big") - 4)
                message = decode(frame, session, KEY, bootstrap=session == EMPTY_SESSION)
                cmd = message["cmd"]
                self.commands.append((message, time.monotonic()))
                response = {"cmd": cmd, "serial": message["serial"], "status": 0}
                if cmd == 0:
                    response.update(sessionKey=KEY.hex(), uid=self.uid)
                    packet = encode(response, DEFAULT_KEY, SESSION)
                    session = SESSION
                else:
                    if cmd == 2:
                        response.update(uid=self.uid, status=self.auth)
                    if cmd == 15 and not self.ack:
                        continue
                    packet = encode(response, KEY, SESSION, b"dk")
                    if cmd == 15 and self.push:
                        # Opposite state arrives before ack: push must win.
                        packet = encode({"cmd": 42, "uid": UID, "deviceId": "test-relay",
                                         "endpoint": 1, "value1": 1}, KEY, SESSION, b"dk") + packet
                # Deliberately fragment the header and encrypted body.
                for chunk in (packet[:3], packet[3:13], packet[13:]):
                    writer.write(chunk)
                    await writer.drain()
                    await asyncio.sleep(0)
        except (EOFError, ConnectionError):
            pass
        finally:
            writer.close()
            self.writers.discard(writer)
            self.handlers.discard(asyncio.current_task())


class ProtocolTests(unittest.TestCase):
    def test_crc_session_kind_and_length(self):
        frame = encode({"cmd": 42}, KEY, SESSION, b"dk")
        self.assertEqual(decode(frame, SESSION, KEY), {"cmd": 42})
        corrupt = bytearray(frame)
        corrupt[-1] ^= 1
        for packet, session in ((bytes(corrupt), SESSION), (frame, b"x" * 32), (frame[:-1], SESSION)):
            with self.assertRaises(ProtocolError):
                decode(packet, session, KEY)
        with self.assertRaises(ProtocolError):
            decode(encode({"cmd": 42}))  # bootstrap frames forbidden after Hello


class LocalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeGateway()
        self.server = await asyncio.start_server(self.fake.serve, "127.0.0.1", 0)
        self.gateway = Gateway("127.0.0.1", UID, "test-user", "TEST-HASH",
                               port=self.server.sockets[0].getsockname()[1], timeout=0.15)
        self.gateway.add(RELAY)

    async def asyncTearDown(self):
        await self.gateway.close()
        for writer in tuple(self.fake.writers):
            writer.close()
        self.server.close()
        await self.server.wait_closed()
        await asyncio.gather(*self.fake.handlers, return_exceptions=True)

    async def test_fragmentation_nonzero_endpoint_push_beats_ack(self):
        await self.gateway.connect()
        await self.gateway.power(RELAY, True)
        self.assertFalse(self.gateway.states[RELAY.key].on)
        self.assertFalse(self.gateway.states[RELAY.key].assumed)
        cmd = self.fake.commands[-1][0]
        self.assertEqual((cmd["cmd"], cmd["endpoint"], cmd["value1"]), (15, 1, 0))

    async def test_blank_uid_only_explicit_host(self):
        self.fake.uid = ""
        with self.assertRaises(ProtocolError):
            await self.gateway.connect()
        self.gateway.trusted_host = True
        await self.gateway.connect()
        self.assertTrue(self.gateway.connected)
        self.assertEqual(self.gateway.uid, UID)

    async def test_read_only_identity_probe_cannot_control(self):
        self.gateway.uid = None
        self.gateway.trusted_host = True
        await self.gateway.connect()
        self.assertEqual(self.gateway.peer_uid, UID)
        with self.assertRaises(ProtocolError):
            await self.gateway.power(RELAY, True)
        self.assertFalse(any(m["cmd"] == 15 for m, _ in self.fake.commands))

    async def test_conflicting_uid_and_auth(self):
        self.fake.uid = "different-gateway"
        self.gateway.trusted_host = True
        with self.assertRaises(ProtocolError):
            await self.gateway.connect()
        self.fake.uid, self.fake.auth = UID, 1
        with self.assertRaises(AuthenticationError):
            await self.gateway.connect()

    async def test_shared_throttle_and_assumed_ack(self):
        self.fake.push = False
        other = Relay(UID, "second-relay", 0, "Second relay")
        self.gateway.add(other)
        await self.gateway.connect()
        await asyncio.gather(self.gateway.power(RELAY, True), self.gateway.power(other, False))
        controls = [t for m, t in self.fake.commands if m["cmd"] == 15]
        self.assertGreaterEqual(controls[1] - controls[0], 0.99)
        self.assertTrue(self.gateway.states[RELAY.key].assumed)

    async def test_timeout_never_replayed_state_unknown(self):
        self.fake.push, self.fake.ack = False, False
        await self.gateway.connect()
        with self.assertRaises(TimeoutError):
            await self.gateway.power(RELAY, True)
        self.assertIsNone(self.gateway.states[RELAY.key].on)
        self.assertEqual(sum(m["cmd"] == 15 for m, _ in self.fake.commands), 1)

    async def test_push_routing_unknown_value_disconnect_reconnect(self):
        await self.gateway.connect()
        self.gateway._push({"uid": "other", "deviceId": RELAY.device_id, "value1": 0})
        self.assertIsNone(self.gateway.states[RELAY.key].on)
        self.gateway._push({"uid": UID, "deviceId": RELAY.device_id, "value1": 3})
        self.assertIsNone(self.gateway.states[RELAY.key].on)
        self.gateway._push({"uid": UID, "deviceId": RELAY.device_id, "value1": 0})
        self.assertTrue(self.gateway.states[RELAY.key].on)
        await self.gateway.close()
        await self.gateway.connect()
        self.assertIsNone(self.gateway.states[RELAY.key].on)

    async def test_run_cancellation_cleans_reader(self):
        task = asyncio.create_task(self.gateway.run())
        for _ in range(100):
            if self.gateway.connected:
                break
            await asyncio.sleep(.01)
        self.assertTrue(self.gateway.connected)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self.assertIsNone(self.gateway._reader_task)
        self.assertFalse(self.gateway.connected)
