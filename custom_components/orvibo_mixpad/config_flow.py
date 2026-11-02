"""Account-scoped UI setup, manual topology, options and reauthentication."""

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
from .protocol import AuthenticationError, ProtocolError
from .transport import make_transport

EMPTY_TOPOLOGY = '{"gateways":{},"relays":[]}'
JSON_INPUT = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


def password_field():
    """Use HA's secret schema marker when supported, as well as a password UI."""
    return vol.Secret("password") if hasattr(vol, "Secret") else "password"


def parse_topology(raw):
    """No endpoint defaults, network scans, unsupported devices or ambiguous IDs."""
    data = json.loads(raw)
    if (not isinstance(data, dict) or set(data) != {"gateways", "relays"}
            or not isinstance(data["gateways"], dict) or not isinstance(data["relays"], list)
            or len(data["gateways"]) > 100 or len(data["relays"]) > 10000):
        raise ValueError("Invalid topology")
    for uid, host in data["gateways"].items():
        if not uid or not private_ipv4(host):
            raise ValueError("Explicit private IPv4 address required")
    keys = set()
    rows = []
    for row in data["relays"]:
        relay = Relay.from_row(row)
        if relay.uid not in data["gateways"] or relay.key in keys:
            raise ValueError("Missing gateway or duplicate relay")
        keys.add(relay.key)
        rows.append(relay.as_row())
    return {"gateways": data["gateways"], "relays": rows}


async def validate(hass, data):
    """Only handshake/login and read-only cloud APIs; never control a relay."""
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


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                topology = parse_topology(user_input["topology"])
                cloud = user_input["cloud_enabled"]
                if not cloud and not topology["relays"]:
                    raise ValueError("Local-only setup requires relay metadata")
                data = {"username": user_input["username"].strip(),
                        "password_hash": password_digest(user_input["password"]),
                        "server": user_input["server"], "cloud_enabled": cloud, "topology": topology}
                if not data["username"]:
                    raise ValueError("Username required")
                # One entry per account, including local-only mode, to share all gateways.
                unique = hashlib.sha256(data["username"].encode()).hexdigest()
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                snapshot = await validate(self.hass, data)
                if snapshot:
                    data["initial_relays"] = [r.as_row() for r in snapshot.relays.values()]
                    data["initial_hosts"] = snapshot.hosts
                return self.async_create_entry(title="ORVIBO MixPad S", data=data)
            except (ValueError, TypeError, KeyError):
                errors["base"] = "invalid_topology"
            except (CloudAuthError, AuthenticationError):
                errors["base"] = "invalid_auth"
            except (CloudError, ProtocolError, OSError, TimeoutError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required("username"): str,
            vol.Required(password_field()): PASSWORD,
            vol.Required("cloud_enabled", default=False): bool,
            vol.Required("server", default=DEFAULT_HOST): vol.In(CLOUD_HOSTS),
            vol.Required("topology", default=EMPTY_TOPOLOGY): JSON_INPUT,
        }))

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
                await validate(self.hass, data)
                return self.async_update_reload_and_abort(entry, data_updates={
                    "password_hash": data["password_hash"]})
            except (CloudAuthError, AuthenticationError):
                errors["base"] = "invalid_auth"
            except (CloudError, ProtocolError, OSError, TimeoutError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="reauth_confirm", errors=errors,
                                    data_schema=vol.Schema({vol.Required(password_field()): PASSWORD}))


class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        errors = {}
        if user_input is not None:
            try:
                topology = parse_topology(user_input["topology"])
                if not user_input["cloud_enabled"] and not topology["relays"] and not entry.data.get("initial_relays"):
                    raise ValueError("Local-only setup requires metadata")
                data = dict(entry.data, cloud_enabled=user_input["cloud_enabled"], topology=topology)
                # Avoid a login on every refresh-interval edit.
                if user_input["cloud_enabled"] and not entry.options.get("cloud_enabled", entry.data["cloud_enabled"]):
                    await validate(self.hass, data)
                return self.async_create_entry(title="", data=dict(user_input, topology=topology))
            except (ValueError, TypeError, KeyError):
                errors["base"] = "invalid_topology"
            except (CloudAuthError, AuthenticationError):
                errors["base"] = "invalid_auth"
            except (CloudError, ProtocolError, OSError, TimeoutError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="init", errors=errors, data_schema=vol.Schema({
            vol.Required("cloud_enabled", default=entry.options.get("cloud_enabled", entry.data["cloud_enabled"])): bool,
            vol.Required("refresh_seconds", default=entry.options.get("refresh_seconds", DEFAULT_REFRESH)): vol.All(
                vol.Coerce(int), vol.Range(min=900, max=86400)),
            vol.Required("discovery", default=entry.options.get("discovery", True)): bool,
            vol.Required("topology", default=json.dumps(entry.options.get("topology", entry.data["topology"]))): JSON_INPUT,
        }))
