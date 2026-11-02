"""One connection, reader and command queue per gateway, shared by relays."""

from __future__ import annotations

import asyncio
import contextlib
import random
import secrets
import time

from .models import State
from .protocol import DEFAULT_KEY, EMPTY_SESSION, AuthenticationError, ProtocolError, decode, encode


class Gateway:
    def __init__(self, host, uid, username, password_hash, changed=lambda: None,
                 *, trusted_host=False, port=8088, interval=1.0, timeout=8):
        self.host, self.uid = host, uid
        self.username, self.password_hash = username, password_hash
        self.trusted_host, self.port = trusted_host, port
        self.changed, self.interval, self.timeout = changed, max(1, interval), timeout
        self.connected = False
        self.states = {}
        self.relays = {}
        self._session, self._key = EMPTY_SESSION, DEFAULT_KEY
        self._serial = secrets.randbelow(1000000000)
        self._pending = {}
        self._request_lock, self._control_lock = asyncio.Lock(), asyncio.Lock()
        self._last_control = -float("inf")
        self._writer = self._reader_task = None
        self.auth_failed = False

    def add(self, relay):
        self.relays[relay.key] = relay
        self.states.setdefault(relay.key, State())

    async def connect(self):
        await self.close()
        try:
            async with asyncio.timeout(15):
                reader, self._writer = await asyncio.open_connection(self.host, self.port)
                self._reader_task = asyncio.create_task(self._read(reader))
                hello = await self.request({
                    "cmd": 0, "source": "ZhiJia365", "softwareVersion": "50103309",
                    "sysVersion": "Android14_34", "hardwareVersion": "Google Pixel 8",
                    "language": "zh", "identifier": secrets.token_hex(5),
                    "phoneName": "Pixel 8", "clientType": 1,
                }, bootstrap=True)
                if hello.get("status") != 0:
                    raise ProtocolError("Hello rejected")
                login = await self.request({"cmd": 2, "userName": self.username,
                                            "password": self.password_hash,
                                            "clientType": 1, "source": "ZhiJia365"})
                if login.get("status") != 0:
                    self.auth_failed = True
                    raise AuthenticationError("Gateway login rejected")
                identities = [message[field] for message in (hello, login)
                              for field in ("uid", "gatewayUid", "gatewayUID") if message.get(field)]
                if any(v != self.uid for v in identities):
                    raise ProtocolError("Gateway identity mismatch")
                if not identities and not self.trusted_host:
                    raise ProtocolError("Discovery requires a handshake UID; specify a trusted IP")
                self.connected = True
                self.changed()
        except BaseException:
            await self.close()
            raise

    async def request(self, payload, *, bootstrap=False):
        async with asyncio.timeout(self.timeout):
            async with self._request_lock:
                if not self._writer or self._writer.is_closing():
                    raise ProtocolError("Gateway disconnected")
                self._serial += 2
                payload = dict(payload, serial=self._serial, uniSerial=self._serial + 1,
                               ver="5.1.3.309", serverRecord=False,
                               debugInfo="Android_ZhiJia365_34_5.1.3.309")
                future = asyncio.get_running_loop().create_future()
                self._pending[self._serial] = (payload["cmd"], future)
                try:
                    self._writer.write(encode(payload,
                                              DEFAULT_KEY if bootstrap else self._key,
                                              EMPTY_SESSION if bootstrap else self._session,
                                              b"pk" if bootstrap else b"dk"))
                    await self._writer.drain()
                    return await future
                finally:
                    self._pending.pop(payload["serial"], None)
                    if not future.done():
                        future.cancel()

    def _install_session(self, message, frame):
        raw = message.get("sessionKey") or message.get("key")
        if not isinstance(raw, str):
            raise ProtocolError("Missing session key")
        try:
            key = bytes.fromhex(raw)
        except ValueError:
            key = raw.encode()
        if len(key) not in (16, 24, 32) or frame[10:42] == EMPTY_SESSION:
            raise ProtocolError("Invalid session")
        # Install inside the sole reader before consuming coalesced DK frames.
        self._key, self._session = key, frame[10:42]

    async def _read(self, reader):
        try:
            while True:
                head = await reader.readexactly(4)
                size = int.from_bytes(head[2:4], "big")
                if head[:2] != b"hd" or size < 58 or (size - 42) % 16:
                    raise ProtocolError("Invalid frame header")
                frame = head + await reader.readexactly(size - 4)
                message = decode(frame, self._session, self._key,
                                 bootstrap=self._session == EMPTY_SESSION)
                pending = self._pending.get(message.get("serial"))
                if pending and message.get("cmd") == pending[0]:
                    if message.get("cmd") == 0 and message.get("status") == 0:
                        self._install_session(message, frame)
                    if not pending[1].done():
                        pending[1].set_result(message)
                if self.connected and message.get("cmd") == 42:
                    self._push(message)
        except (OSError, EOFError, ValueError, TypeError, ProtocolError):
            pass
        finally:
            self.connected = False
            for _, future in tuple(self._pending.values()):
                if not future.done():
                    future.set_exception(ProtocolError("Gateway disconnected"))
            if self._writer:
                self._writer.close()
            for state in self.states.values():
                state.reset()
            self.changed()

    def _push(self, message):
        if message.get("uid") not in (None, "", self.uid):
            return
        keys = [key for key, relay in self.relays.items()
                if relay.device_id == message.get("deviceId")
                and ("endpoint" not in message or relay.endpoint == message["endpoint"])]
        # A push without endpoint must identify exactly one relay.
        if len(keys) == 1:
            self.states[keys[0]].push(message.get("value1"))
            self.changed()

    async def power(self, relay, on):
        async with self._control_lock:
            if relay.key not in self.relays:
                raise ProtocolError("Relay no longer supported")
            state = self.states[relay.key]
            if not self.connected:
                raise ProtocolError("Gateway disconnected")
            await asyncio.sleep(max(0, self.interval - (time.monotonic() - self._last_control)))
            if not self.connected or relay.key not in self.relays:
                raise ProtocolError("Gateway or relay unavailable")
            self._last_control = time.monotonic()
            revision = state.revision
            state.pending = True
            state.mark_local()
            try:
                response = await self.request({
                    "cmd": 15, "uid": self.uid, "deviceId": relay.device_id,
                    "endpoint": relay.endpoint, "userName": self.username,
                    "source": "ZhiJia365", "groupId": "", "order": "on" if on else "off",
                    "value1": 0 if on else 1, "value2": 255 if on else 0,
                    "value3": 0, "value4": 0, "encryption": 1, "delayTime": 0,
                    "qualityOfService": 1, "defaultResponse": 1, "propertyResponse": 0,
                })
                if response.get("status") != 0:
                    raise ProtocolError("Gateway rejected relay command")
                if state.revision == revision:
                    state.on, state.assumed, state.source = on, True, "local_command"
            except (TimeoutError, OSError, ProtocolError):
                # Never replay a possibly delivered power command.
                if state.revision == revision:
                    state.reset()
                raise
            finally:
                state.pending = False
                state.mark_local()
                self.changed()

    async def run(self):
        delay = 2
        try:
            while not self.auth_failed:
                try:
                    if not self.connected:
                        await self.connect()
                    delay = 2
                    while self.connected:
                        await asyncio.sleep(30)
                        if self.connected:
                            reply = await self.request({"cmd": 32, "clientType": 1})
                            if reply.get("status", 0) != 0:
                                raise ProtocolError("Heartbeat rejected")
                except AuthenticationError:
                    self.auth_failed = True
                except (TimeoutError, OSError, ProtocolError):
                    pass
                await self.close()
                if not self.auth_failed:
                    await asyncio.sleep(delay + random.uniform(0, delay / 4))
                    delay = min(120, delay * 2)
        finally:
            await self.close()

    async def close(self):
        self.connected = False
        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        if self._writer:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()
            self._writer = None
        self._session, self._key = EMPTY_SESSION, DEFAULT_KEY
        for state in self.states.values():
            state.reset()
        self.changed()
