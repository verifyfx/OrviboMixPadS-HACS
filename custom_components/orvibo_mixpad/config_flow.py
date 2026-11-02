"""Account setup with multiple hubs, hub management, settings and reauth."""

import hashlib
import json

try:
    import probatio as vol
except ImportError:  # HA versions before the schema-library migration.
    import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import request_gate
from .cloud import CloudAccount, CloudAuthError, CloudError, password_digest
from .const import CLOUD_HOSTS, DEFAULT_HOST, DEFAULT_REFRESH, DOMAIN
from .local import Gateway
from .models import Relay, private_ipv4
from .onboarding import DuplicatePanelError, PanelBatch, panel_addresses, panel_choices
from .protocol import AuthenticationError, ProtocolError
from .transport import make_transport

JSON_INPUT = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
HUB_IPS = selector.TextSelector(selector.TextSelectorConfig(multiple=True))
PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


def password_field():
    return vol.Secret("password") if hasattr(vol, "Secret") else "password"


def parse_topology(raw):
    """Advanced local-only metadata; endpoints and IDs are never guessed."""
    data = json.loads(raw)
    if (not isinstance(data, dict) or set(data) != {"gateways", "relays"}
            or not isinstance(data["gateways"], dict) or not isinstance(data["relays"], list)
            or len(data["gateways"]) > 100 or len(data["relays"]) > 10000):
        raise ValueError("Invalid topology")
    for uid, host in data["gateways"].items():
        if not uid or not private_ipv4(host):
            raise ValueError("Explicit private IPv4 address required")
    keys, rows = set(), []
    for row in data["relays"]:
        relay = Relay.from_row(row)
        if relay.uid not in data["gateways"] or relay.key in keys:
            raise ValueError("Missing gateway or duplicate relay")
        keys.add(relay.key)
        rows.append(relay.as_row())
    return {"gateways": data["gateways"], "relays": rows}


async def validate(hass, data):
    """Cloud reads and explicit local handshakes only; no power commands."""
    result = None
    if data["cloud_enabled"]:
        account = CloudAccount(data["username"], data["password_hash"], request_gate(hass),
                               make_transport(async_get_clientsession(hass), data["server"]))
        try:
            result = await account.refresh()
        finally:
            await account.close()
    for uid, host in data["topology"]["gateways"].items():
        gateway = Gateway(host, uid, data["username"], data["password_hash"], trusted_host=True)
        try:
            await gateway.connect()
        finally:
            await gateway.close()
    return result


def cloud_only(data):
    return dict(data, topology={"gateways": {}, "relays": []})


def flow_error(error):
    if isinstance(error, DuplicatePanelError):
        return "duplicate_panel"
    if isinstance(error, (CloudAuthError, AuthenticationError)):
        return "invalid_auth"
    return "cannot_connect"


def entry_relays(entry):
    runtime = getattr(entry, "runtime_data", None)
    if runtime:
        return list(runtime.relays.values())
    rows = entry.data.get("initial_relays", []) + entry.options.get("imported_relays", [])
    return list({relay.key: relay for relay in (Relay.from_row(row) for row in rows)}.values())


def hub_summary(entry):
    """Private account details are rendered only in the user's HA options UI."""
    runtime = getattr(entry, "runtime_data", None)
    manual = entry.options.get("topology", entry.data["topology"])["gateways"]
    grouped = {}
    for relay in entry_relays(entry):
        grouped.setdefault(relay.uid, []).append(relay.name)
    for uid in manual:
        grouped.setdefault(uid, [])
    lines = []
    for index, (uid, names) in enumerate(sorted(grouped.items()), 1):
        host = manual.get(uid) or (runtime.hosts.get(uid) if runtime else entry.data.get("initial_hosts", {}).get(uid))
        gateway = runtime.gateways.get(uid) if runtime else None
        status = "Connected" if gateway and gateway.connected else "Disconnected" if uid in manual else "IP setup needed"
        label = ", ".join(names[:2]) or f"MixPad {index}"
        lines.append(f"- {label}: {host or 'No IP address'} — {status}")
    return "\n".join(lines) or "No hubs configured yet."


class PanelSelection:
    """Shared multi-hub selection step for setup and options."""

    async def _advance_hubs(self):
        try:
            if await self._batch.advance():
                return self._finish_hubs()
        except (ProtocolError, OSError, TimeoutError) as error:
            return self._hub_error(flow_error(error))
        return await self.async_step_select_gateway()

    async def async_step_select_gateway(self, user_input=None):
        errors = {}
        if user_input:
            try:
                await self._batch.confirm(user_input["gateway_uid"])
                return await self._advance_hubs()
            except (ProtocolError, OSError, TimeoutError) as error:
                errors["base"] = flow_error(error)
        return self.async_show_form(
            step_id="select_gateway", errors=errors,
            description_placeholders={"host": self._batch.host,
                                      "current": str(self._batch.index + 1), "total": str(len(self._batch.hosts))},
            data_schema=vol.Schema({vol.Required("gateway_uid"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[{"value": uid, "label": label}
                                                      for uid, label in self._batch.choices.items()]))}),
        )


class ConfigFlow(PanelSelection, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._user_values = {k: v for k, v in user_input.items() if k != "password"}
            cloud = user_input.get("cloud_enabled", True)
            try:
                hosts = panel_addresses(user_input.get("mixpad_ips", []), required=cloud)
            except ValueError:
                return self._hub_error("invalid_ip")
            try:
                data = {"username": user_input["username"].strip(),
                        "password_hash": password_digest(user_input["password"]),
                        "server": user_input["server"], "cloud_enabled": cloud,
                        "topology": {"gateways": {}, "relays": []}}
                if not data["username"]:
                    raise ValueError("Username required")
                await self.async_set_unique_id(hashlib.sha256(data["username"].encode()).hexdigest())
                self._abort_if_unique_id_configured()
                if not cloud:
                    self._local_data = data
                    return await self.async_step_local()
                snapshot = await validate(self.hass, data)
                if not panel_choices(snapshot):
                    return self._hub_error("no_supported_devices")
                self._batch = PanelBatch(hosts, data, snapshot)
                return await self._advance_hubs()
            except (ValueError, TypeError, KeyError):
                errors["base"] = "invalid_topology"
            except (CloudError, ProtocolError, OSError, TimeoutError) as error:
                errors["base"] = flow_error(error)
        return self._user_form(errors)

    def _hub_error(self, reason):
        return self._user_form({"base": reason})

    def _user_form(self, errors):
        values = getattr(self, "_user_values", {})
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required("username", default=values.get("username", "")): str,
            vol.Required(password_field()): PASSWORD,
            vol.Required("server", default=values.get("server", DEFAULT_HOST)): vol.In(CLOUD_HOSTS),
            vol.Required("mixpad_ips", default=values.get("mixpad_ips", [])): HUB_IPS,
            vol.Required("cloud_enabled", default=values.get("cloud_enabled", True)): bool,
        }))

    def _finish_hubs(self):
        data, snapshot = self._batch.data, self._batch.snapshot
        scope = self._batch.scope
        data["initial_relays"] = [r.as_row() for r in snapshot.relays.values() if r.uid in scope]
        data["initial_hosts"] = {uid: host for uid, host in snapshot.hosts.items() if uid in scope}
        data["selected_gateways"] = scope
        return self.async_create_entry(title="ORVIBO MixPad S", data=data)

    async def async_step_local(self, user_input=None):
        errors = {}
        if user_input:
            try:
                topology = parse_topology(user_input["topology"])
                if not topology["relays"]:
                    raise ValueError("Local-only setup requires relay metadata")
                data = dict(self._local_data, topology=topology)
                await validate(self.hass, data)
                return self.async_create_entry(title="ORVIBO MixPad S", data=data)
            except (ValueError, TypeError, KeyError):
                errors["base"] = "invalid_topology"
            except (ProtocolError, OSError, TimeoutError) as error:
                errors["base"] = flow_error(error)
        return self.async_show_form(step_id="local", errors=errors,
                                   data_schema=vol.Schema({vol.Required("topology"): JSON_INPUT}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input:
            entry = self._get_reauth_entry()
            data = dict(entry.data, password_hash=password_digest(user_input["password"]))
            data["cloud_enabled"] = entry.options.get("cloud_enabled", data["cloud_enabled"])
            data["topology"] = entry.options.get("topology", data["topology"])
            try:
                await validate(self.hass, cloud_only(data) if data["cloud_enabled"] else data)
                return self.async_update_reload_and_abort(entry, data_updates={"password_hash": data["password_hash"]})
            except (CloudError, ProtocolError, OSError, TimeoutError) as error:
                errors["base"] = flow_error(error)
        return self.async_show_form(step_id="reauth_confirm", errors=errors,
                                   data_schema=vol.Schema({vol.Required(password_field()): PASSWORD}))


class OptionsFlow(PanelSelection, config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["hubs", "settings"],
                                    description_placeholders={"hubs": hub_summary(self.config_entry)})

    async def async_step_hubs(self, user_input=None):
        entry = self.config_entry
        if user_input is not None:
            self._hub_ips = user_input.get("mixpad_ips", [])
            try:
                hosts = panel_addresses(self._hub_ips)
            except ValueError:
                return self._hub_error("invalid_ip")
            enabled = entry.options.get("cloud_enabled", entry.data["cloud_enabled"])
            if not enabled:
                return self._hub_error("cloud_required")
            topology = entry.options.get("topology", entry.data["topology"])
            data = dict(entry.data, cloud_enabled=True, topology=topology)
            try:
                runtime = getattr(entry, "runtime_data", None)
                snapshot = await runtime.cloud.refresh() if runtime and runtime.cloud else await validate(
                    self.hass, cloud_only(data))
                if not panel_choices(snapshot):
                    return self._hub_error("no_supported_devices")
                selected = entry.options.get("selected_gateways", entry.data.get("selected_gateways"))
                if selected is None:
                    selected = sorted({r.uid for r in entry_relays(entry)} | set(topology["gateways"]))
                self._batch = PanelBatch(hosts, data, snapshot, selected=selected)
                return await self._advance_hubs()
            except (CloudError, ProtocolError, OSError, TimeoutError) as error:
                return self._hub_error(flow_error(error))
        return self._hubs_form({})

    def _hub_error(self, reason):
        return self._hubs_form({"base": reason})

    def _hubs_form(self, errors):
        return self.async_show_form(step_id="hubs", errors=errors,
                                   description_placeholders={"hubs": hub_summary(self.config_entry)},
                                   data_schema=vol.Schema({vol.Required(
                                       "mixpad_ips", default=getattr(self, "_hub_ips", [])): HUB_IPS}))

    def _finish_hubs(self):
        entry, batch = self.config_entry, self._batch
        previous = {Relay.from_row(row).key: row for row in entry.options.get("imported_relays", [])}
        previous.update({r.key: r.as_row() for r in batch.snapshot.relays.values() if r.uid in batch.scope})
        options = dict(entry.options, topology=batch.data["topology"], selected_gateways=batch.scope,
                       imported_relays=list(previous.values()))
        return self.async_create_entry(title="", data=options)

    async def async_step_settings(self, user_input=None):
        entry = self.config_entry
        errors = {}
        if user_input is not None:
            try:
                topology = parse_topology(user_input["topology"]) if user_input.get("topology") else entry.options.get(
                    "topology", entry.data["topology"])
                if not user_input["cloud_enabled"] and not topology["relays"] and not entry_relays(entry):
                    raise ValueError("Local-only setup requires metadata")
                options = dict(entry.options, **user_input)
                options["topology"] = topology
                if user_input["cloud_enabled"] and not entry.options.get("cloud_enabled", entry.data["cloud_enabled"]):
                    await validate(self.hass, cloud_only(dict(entry.data, cloud_enabled=True)))
                return self.async_create_entry(title="", data=options)
            except (ValueError, TypeError, KeyError):
                errors["base"] = "invalid_topology"
            except (CloudError, ProtocolError, OSError, TimeoutError) as error:
                errors["base"] = flow_error(error)
        return self.async_show_form(step_id="settings", errors=errors, data_schema=vol.Schema({
            vol.Required("cloud_enabled", default=entry.options.get("cloud_enabled", entry.data["cloud_enabled"])): bool,
            vol.Required("refresh_seconds", default=entry.options.get("refresh_seconds", DEFAULT_REFRESH)): vol.All(
                vol.Coerce(int), vol.Range(min=900, max=86400)),
            vol.Required("discovery", default=entry.options.get("discovery", True)): bool,
            vol.Optional("topology"): JSON_INPUT,
        }))
