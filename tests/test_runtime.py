"""Offline account lifecycle tests with a minimal HA storage adapter."""

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from . import bootstrap  # noqa: F401


class MemoryStore:
    saved = None

    def __init__(self, *args):
        pass

    async def async_load(self):
        return None

    async def async_save(self, data):
        self.saved = data


storage = types.ModuleType("homeassistant.helpers.storage")
storage.Store = MemoryStore
# Only pure offline tests import this adapter; real HA runs in a separate process.
with patch.dict(sys.modules, {"homeassistant": types.ModuleType("homeassistant"),
                              "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
                              "homeassistant.helpers.storage": storage}):
    from custom_components.orvibo_mixpad.runtime import Runtime

from custom_components.orvibo_mixpad.cloud import Snapshot  # noqa: E402
from custom_components.orvibo_mixpad.models import Relay  # noqa: E402


class Entry:
    entry_id = "synthetic-entry"
    data = {"username": "synthetic-user", "password_hash": "SYNTHETIC-HASH", "cloud_enabled": False,
            "topology": {"gateways": {"test-gateway": "192.168.50.20"}, "relays": [
                {"uid": "test-gateway", "deviceId": "test-relay", "endpoint": 1,
                 "deviceType": 1, "deviceName": "Test relay"}]}}
    options = {"discovery": False}

    def async_create_background_task(self, hass, coro, name):
        return asyncio.create_task(coro, name=name)

    def async_start_reauth(self, hass):
        pass


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.run_patch = patch("custom_components.orvibo_mixpad.runtime.Gateway.run", new=AsyncMock())
        self.run_patch.start()
        self.runtime = Runtime(None, Entry(), None, None)
        await self.runtime.start()

    async def asyncTearDown(self):
        await self.runtime.close()
        self.run_patch.stop()

    async def test_additions_share_gateway_and_unload(self):
        calls = []
        self.runtime.subscribe(lambda: calls.append(1))
        relay = Relay("test-gateway", "new-test-relay", 0, "New relay")
        self.runtime.relays[relay.key] = relay
        self.runtime._reconcile()
        self.runtime._reconcile()
        self.assertEqual(len(self.runtime.gateways), 1)
        self.assertEqual(len(self.runtime.gateways["test-gateway"].states), 2)
        self.assertEqual(len(calls), 2)
        await self.runtime.close()
        self.assertFalse(self.runtime.listeners)
        self.assertTrue(all(t.done() for t in self.runtime.tasks))

    async def test_cloud_failure_preserves_local_availability(self):
        from custom_components.orvibo_mixpad.cloud import CloudError
        gateway = self.runtime.gateways["test-gateway"]
        gateway.connected = True
        self.runtime.cloud = types.SimpleNamespace(refresh=AsyncMock(side_effect=CloudError("test")), close=AsyncMock())
        await self.runtime._refresh_cloud()
        self.assertTrue(gateway.connected)
        self.assertFalse(self.runtime.cloud_ok)

    async def test_cache_wins_over_initial_cloud_inventory(self):
        await self.runtime.close()
        entry = Entry()
        entry.data = dict(Entry.data, initial_relays=[{
            "uid": "cloud-gateway", "deviceId": "obsolete-relay", "endpoint": 0,
            "deviceType": 1}], initial_hosts={"cloud-gateway": "192.168.50.30"})
        self.runtime = Runtime(None, entry, None, None)
        self.runtime.store.async_load = AsyncMock(return_value={
            "relays": [], "hosts": {"cloud-gateway": "192.168.50.31"}})
        await self.runtime.start()
        self.assertNotIn(("cloud-gateway", "obsolete-relay", 0), self.runtime.relays)
        self.assertEqual(self.runtime.hosts["cloud-gateway"], "192.168.50.31")

    async def test_partial_absence_retains_devices_explicit_change_revokes(self):
        # Cloud-discovered metadata, not explicitly asserted manual relay metadata.
        relay = Relay("test-gateway", "cloud-test-relay", 0, "Cloud relay")
        self.runtime.relays[relay.key] = relay
        self.runtime._reconcile()
        snapshot = Snapshot({}, {}, [], 1, observed_devices={})
        self.runtime.cloud = types.SimpleNamespace(refresh=AsyncMock(return_value=snapshot), close=AsyncMock())
        await self.runtime._refresh_cloud()
        self.assertIn(relay.key, self.runtime.relays)
        snapshot.observed_devices = {(relay.uid, relay.device_id): set()}
        await self.runtime._refresh_cloud()
        self.assertNotIn(relay.key, self.runtime.relays)
        self.assertNotIn(relay.key, self.runtime.gateways[relay.uid].relays)

    async def test_discovery_address_replacement_does_not_grant_trust(self):
        self.runtime.manual = {"gateways": {}, "relays": []}
        self.runtime.entry = types.SimpleNamespace(**{
            "data": Entry.data, "options": {"discovery": True},
            "async_create_background_task": Entry().async_create_background_task})
        with patch("custom_components.orvibo_mixpad.runtime.discover", new=AsyncMock(
                return_value={"test-gateway": "192.168.50.21"})):
            await self.runtime._resolve()
        gateway = self.runtime.gateways["test-gateway"]
        self.assertEqual(gateway.host, "192.168.50.21")
        self.assertFalse(gateway.trusted_host)
