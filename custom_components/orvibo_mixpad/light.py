"""Strict on/off relays with push state and dynamic additive discovery."""

import json

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .models import State
from .protocol import ProtocolError

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = entry.runtime_data
    known = set()

    def add_new():
        new = [relay for key, relay in runtime.relays.items() if key not in known]
        known.update(relay.key for relay in new)
        async_add_entities([RelayLight(runtime, relay) for relay in new])

    entry.async_on_unload(runtime.subscribe(add_new))
    add_new()


class RelayLight(LightEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, runtime, relay):
        self.runtime, self.relay = runtime, relay
        self._attr_unique_id = json.dumps(relay.key, separators=(",", ":"))
        self._attr_name = relay.name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, json.dumps([relay.uid, relay.device_id]))},
            manufacturer="ORVIBO", name=relay.name, model="Type-1 relay via MixPad")

    @property
    def gateway(self):
        return self.runtime.gateways.get(self.relay.uid)

    @property
    def relay_state(self):
        return self.gateway.states[self.relay.key] if self.gateway else State()

    @property
    def available(self):
        return bool(self.gateway and self.gateway.connected and self.relay.key in self.gateway.relays)

    @property
    def is_on(self):
        return self.relay_state.on

    @property
    def assumed_state(self):
        return self.relay_state.assumed

    @property
    def extra_state_attributes(self):
        return {"state_source": self.relay_state.source}

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.subscribe(self.async_write_ha_state))

    async def async_turn_on(self, **kwargs):
        await self._power(True)

    async def async_turn_off(self, **kwargs):
        await self._power(False)

    async def _power(self, on):
        try:
            if not self.gateway:
                raise ProtocolError("Gateway unavailable")
            await self.gateway.power(self.relay, on)
        except (OSError, TimeoutError, ProtocolError):
            raise HomeAssistantError("Local relay command failed; state may be unknown") from None
