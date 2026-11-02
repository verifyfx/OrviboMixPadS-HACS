"""Entry lifecycle and additive inventory reconciliation."""

import asyncio
import contextlib
import random

from homeassistant.helpers.storage import Store

from .cloud import CloudAccount, CloudAuthError, CloudError
from .const import DEFAULT_REFRESH, DOMAIN
from .discovery import discover
from .local import Gateway
from .models import Relay, private_ipv4
from .transport import make_transport


class Runtime:
    def __init__(self, hass, entry, session, gate):
        self.hass, self.entry = hass, entry
        self.listeners = set()
        self.gateways, self.relays = {}, {}
        self.tasks = []
        self.gateway_tasks = {}
        self.hosts = {}
        self.closed = False
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.cloud = None
        self.cloud_ok = False
        self.inventory_complete = False
        self.selected = entry.options.get("selected_gateways", entry.data.get("selected_gateways"))
        if entry.options.get("cloud_enabled", entry.data["cloud_enabled"]):
            self.cloud = CloudAccount(entry.data["username"], entry.data["password_hash"], gate,
                                      make_transport(session, entry.data["server"]))

    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    def changed(self):
        if not self.closed:
            for listener in tuple(self.listeners):
                listener()

    def _background(self, coro, name):
        task = self.entry.async_create_background_task(self.hass, coro, name)
        self.tasks.append(task)
        return task

    async def start(self):
        cached = await self.store.async_load()
        if cached is None:
            cached = {"hosts": self.entry.data.get("initial_hosts", {}),
                      "relays": self.entry.data.get("initial_relays", [])}
        self.hosts.update({uid: host for uid, host in cached.get("hosts", {}).items()
                           if isinstance(uid, str) and private_ipv4(host)})
        cached_uids = {row.get("uid") for row in cached.get("relays", []) if isinstance(row, dict)}
        cached_uids.update(cached.get("imported_gateway_uids", []))
        imported = [row for row in self.entry.options.get("imported_relays", []) if row.get("uid") not in cached_uids]
        for row in cached.get("relays", []) + imported:
            try:
                relay = Relay.from_row(row)
            except ValueError:
                continue
            if self.selected is None or relay.uid in self.selected:
                self.relays[relay.key] = relay
        self.manual = self.entry.options.get("topology", self.entry.data["topology"])
        self.hosts.update(self.manual["gateways"])
        for row in self.manual["relays"]:
            relay = Relay.from_row(row)
            if self.selected is None or relay.uid in self.selected:
                self.relays[relay.key] = relay
        # Start known addresses immediately; cloud outages never block local startup.
        self._reconcile()
        self._background(self._poll(), "ORVIBO account inventory")

    def _reconcile(self):
        for relay in self.relays.values():
            host = self.hosts.get(relay.uid)
            if not host:
                continue
            gateway = self.gateways.get(relay.uid)
            if gateway is None:
                gateway = self.gateways[relay.uid] = Gateway(
                    host, relay.uid, self.entry.data["username"], self.entry.data["password_hash"],
                    self.changed, trusted_host=relay.uid in self.manual["gateways"])
                gateway.add(relay)
                self.gateway_tasks[relay.uid] = self._background(
                    self._run_gateway(gateway), "ORVIBO local gateway")
            else:
                gateway.add(relay)
        self.changed()

    async def _run_gateway(self, gateway):
        await gateway.run()
        if gateway.auth_failed and not self.closed:
            self.entry.async_start_reauth(self.hass)

    async def _resolve(self):
        known = {relay.uid for relay in self.relays.values()}
        candidates = {}
        if self.entry.options.get("discovery", True):
            try:
                candidates = await discover(known)
            except OSError:
                pass
        # Cloud addresses are also candidates; each requires TCP UID confirmation.
        candidates = self.hosts | candidates
        for uid, host in candidates.items():
            if uid in self.manual["gateways"]:
                continue
            gateway = self.gateways.get(uid)
            if gateway and (gateway.connected or gateway.auth_failed):
                continue
            if gateway and gateway.host != host:
                task = self.gateway_tasks[uid]
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                self.gateways.pop(uid)
            self.hosts[uid] = host
        self._reconcile()

    async def _refresh_cloud(self):
        try:
            snapshot = await self.cloud.refresh()
        except CloudAuthError:
            self.cloud_ok = False
            self.entry.async_start_reauth(self.hass)
            return
        except CloudError:
            self.cloud_ok = False
            return
        self.cloud_ok = True
        self.inventory_complete = snapshot.complete
        manual_keys = {Relay.from_row(row).key for row in self.manual["relays"]}
        for key, relay in tuple(self.relays.items()):
            observed = (snapshot.observed_devices or {}).get((relay.uid, relay.device_id))
            if observed is not None and key not in observed and key not in manual_keys:
                # Explicit changed metadata can revoke support; absence cannot.
                self.relays.pop(key)
                gateway = self.gateways.get(relay.uid)
                if gateway:
                    gateway.relays.pop(key, None)
        self.relays.update({key: relay for key, relay in snapshot.relays.items()
                            if self.selected is None or relay.uid in self.selected})
        active_uids = {relay.uid for relay in self.relays.values()}
        for uid in tuple(self.gateways):
            if uid not in active_uids:
                task = self.gateway_tasks.pop(uid)
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                await self.gateways.pop(uid).close()
        # Never change a connected gateway based on a cloud address alone.
        for uid, host in snapshot.hosts.items():
            if uid not in self.manual["gateways"] and (self.selected is None or uid in self.selected):
                self.hosts[uid] = host
        self._reconcile()
        by_device = {}
        for relay in self.relays.values():
            by_device.setdefault(relay.device_id, []).append(relay)
        for row in snapshot.statuses:
            if not isinstance(row.get("deviceId"), str):
                continue
            matches = [relay for relay in by_device.get(row.get("deviceId"), [])
                       if row.get("uid") in (None, "", relay.uid)
                       and ("endpoint" not in row or row["endpoint"] == relay.endpoint)]
            if len(matches) != 1:
                continue
            relay = matches[0]
            gateway = self.gateways.get(relay.uid)
            if gateway:
                gateway.states[relay.key].cloud(row, snapshot.started)
        await self.store.async_save({"hosts": self.hosts,
                                     "relays": [r.as_row() for r in self.relays.values()],
                                     "imported_gateway_uids": self.selected or []})
        self.changed()

    async def _poll(self):
        try:
            await self._resolve()
            while True:
                if self.cloud and not self.cloud.auth_failed:
                    await self._refresh_cloud()
                await asyncio.sleep(self.entry.options.get("refresh_seconds", DEFAULT_REFRESH) * random.uniform(1, 1.15))
                await self._resolve()
        except asyncio.CancelledError:
            raise

    async def close(self):
        self.closed = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.cloud:
            await self.cloud.close()
        for gateway in self.gateways.values():
            await gateway.close()
        self.listeners.clear()

    async def remove_cache(self):
        await self.store.async_remove()
