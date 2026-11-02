"""ORVIBO MixPad S local relay integration."""

from homeassistant.const import Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .cloud import RequestGate
from .const import DOMAIN
from .runtime import Runtime

PLATFORMS = [Platform.LIGHT]


def request_gate(hass):
    return hass.data.setdefault(f"{DOMAIN}_gate", RequestGate())


async def async_setup_entry(hass, entry):
    runtime = Runtime(hass, entry, async_get_clientsession(hass), request_gate(hass))
    entry.runtime_data = runtime
    try:
        await runtime.start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await runtime.close()
        raise
    entry.async_on_unload(entry.add_update_listener(_updated))
    return True


async def _updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.close()
        return True
    return False


async def async_remove_entry(hass, entry):
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
