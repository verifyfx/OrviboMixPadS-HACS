"""Fake account service, synthetic topology and state races."""

import asyncio
import time
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from . import bootstrap  # noqa: F401
from custom_components.orvibo_mixpad.cloud import (
    CloudAccount, CloudAuthError, CloudError, RequestGate, retry_after, signed,
)
from custom_components.orvibo_mixpad.models import Relay, State, inventory, private_ipv4


def table():
    return {"device": [{"uid": "gw-test", "deviceId": "panel", "deviceType": 114},
                        {"uid": "gw-test", "deviceId": "relay-test", "deviceType": 1,
                         "endpoint": 1, "deviceName": "Test relay"},
                        {"uid": "gw-test", "deviceId": "lock-test", "deviceType": 7, "endpoint": 0}],
            "gateway": [{"uid": "gw-test", "localStaticIP": "192.168.50.20:8088"}],
            "deviceStatus": [{"deviceId": "relay-test", "value1": 0, "updateTimeSec": 123}]}


class FakeCloud:
    def __init__(self):
        self.calls = []
        self.data = table()
        self.reject_once = False
        self.reject_login = False

    async def __call__(self, path, params, form):
        self.calls.append((path, params, form))
        await asyncio.sleep(0)
        if form:
            return 200, {}, {"status": 1 if self.reject_login else 0,
                             "data": {"access_token": "synthetic-token", "user_id": "synthetic-user", "expires_in": 3600}}
        if self.reject_once:
            self.reject_once = False
            return 401, {}, None
        if path.endswith("users"):
            return 200, {}, {"code": 0, "data": [{"familyId": "z-test-opaque-family"}]}
        return 200, {}, {"code": 0, "data": self.data}


class CloudTests(unittest.IsolatedAsyncioTestCase):
    def make_account(self):
        fake = FakeCloud()
        account = CloudAccount("synthetic-user", "SYNTHETIC-HASH", RequestGate(0), fake, jitter=lambda: 0)
        self.addAsyncCleanup(account.close)
        return account, fake

    async def test_coalescing_token_cache_inventory_types(self):
        account, fake = self.make_account()
        a, b = await asyncio.gather(account.refresh(), account.refresh())
        self.assertIs(a, b)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(len(a.relays), 1)
        self.assertFalse(a.complete)
        self.assertEqual(next(iter(a.relays.values())).endpoint, 1)
        self.assertEqual(a.hosts, {"gw-test": "192.168.50.20"})
        await account.refresh()
        self.assertEqual(len(fake.calls), 3)
        account.cached_at = time.monotonic() - 61
        fake.data["device"].append({"uid": "gw-test", "deviceId": "new-relay", "endpoint": 0, "deviceType": 1})
        self.assertEqual(len((await account.refresh()).relays), 2)
        self.assertEqual(sum(c[2] for c in fake.calls), 1)

    async def test_bounded_token_renewal(self):
        account, fake = self.make_account()
        fake.reject_once = True
        await account.refresh()
        self.assertEqual(sum(c[2] for c in fake.calls), 2)

    async def test_partial_gateway_table_does_not_revoke_known_relay(self):
        account, fake = self.make_account()
        fake.data["device"] = fake.data["device"][1:]
        snapshot = await account.refresh()
        self.assertFalse(snapshot.relays)
        self.assertEqual(snapshot.observed_devices[("gw-test", "relay-test")],
                         {("gw-test", "relay-test", 1)})

    async def test_login_failure_stops_until_reauth(self):
        account, fake = self.make_account()
        fake.reject_login = True
        for _ in range(2):
            with self.assertRaises(CloudAuthError):
                await account.refresh()
        self.assertEqual(len(fake.calls), 1)

    async def test_pagination_not_silently_complete_and_backoff(self):
        account, fake = self.make_account()
        fake.data["hasNext"] = True
        with self.assertRaises(CloudError):
            await account.refresh()
        count = len(fake.calls)
        with self.assertRaises(CloudError):
            await account.refresh()
        self.assertEqual(len(fake.calls), count)
        self.assertGreater(account.retry_at - time.monotonic(), 59)
        self.assertIsNone(account.cached)

    async def test_global_429_and_spacing(self):
        gate = RequestGate(.03)
        times = []
        async def ok(*args):
            times.append(time.monotonic())
            return 200, {}, {"code": 0}
        await asyncio.gather(gate.request(ok, "/a", {}), gate.request(ok, "/b", {}))
        self.assertGreaterEqual(times[1] - times[0], .029)
        async def limited(*args):
            return 429, {"Retry-After": "180"}, None
        with self.assertRaises(CloudError):
            await gate.request(limited, "/a", {})
        self.assertGreater(gate.blocked_until - time.monotonic(), 179)
        with self.assertRaises(CloudError):
            await gate.request(ok, "/another-account", {})
        self.assertEqual(len(times), 2)

    async def test_cancel_waiter_does_not_cancel_shared_refresh(self):
        account, _ = self.make_account()
        waiter = asyncio.create_task(account.refresh())
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertIsNotNone(await account.refresh())


class ModelTests(unittest.TestCase):
    def test_cloud_local_races(self):
        state = State()
        started = time.monotonic()
        state.push(0)
        row = {"value1": 1, "updateTimeSec": time.time() + 1}
        self.assertFalse(state.cloud(row, started))
        state.pending = True
        self.assertFalse(state.cloud(row, time.monotonic() + 1))
        state.pending = False
        row["updateTimeSec"] = state.local_wall - 1
        self.assertFalse(state.cloud(row, time.monotonic() + 1))
        row["updateTimeSec"] = time.time() + 1
        self.assertTrue(state.cloud(row, time.monotonic() + 1))
        self.assertFalse(state.on)
        self.assertTrue(state.assumed)
        row["updateTimeSec"] = float("nan")
        self.assertFalse(state.cloud(row, time.monotonic() + 1))

    def test_missing_endpoint_not_guessed(self):
        with self.assertRaises(ValueError):
            Relay.from_row({"uid": "test", "deviceId": "test", "deviceType": 1})
        self.assertIsNone(private_ipv4("127.0.0.1"))
        self.assertIsNone(private_ipv4("169.254.169.254"))
        with self.assertRaises(ValueError):
            inventory({"device": [None]})

    def test_retry_after_and_signing(self):
        self.assertEqual(retry_after("120"), 120)
        value = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=180), usegmt=True)
        self.assertGreater(retry_after(value), 178)
        self.assertEqual(retry_after("nan"), 60)
        self.assertEqual(signed({"b": "", "a": 0})["sign"], signed({"a": 0})["sign"])
