"""Run with the real Home Assistant fixture in Linux CI."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orvibo_mixpad.cloud import password_digest
from custom_components.orvibo_mixpad.const import DOMAIN
from custom_components.orvibo_mixpad.models import Relay

TOPOLOGY = {"gateways": {"test-gateway": "192.168.50.20"}, "relays": [
    {"uid": "test-gateway", "deviceId": "test-relay", "endpoint": 1,
     "deviceType": 1, "deviceName": "Test relay"}]}
DATA = {"username": "synthetic-user", "password_hash": password_digest("synthetic-password"),
        "server": "usa.orvibo.com", "cloud_enabled": False, "topology": TOPOLOGY}


async def test_manual_flow_and_duplicate(hass):
    import json
    user = {"username": "synthetic-user", "password": "synthetic-password",
            "cloud_enabled": False, "server": "usa.orvibo.com", "topology": json.dumps(TOPOLOGY)}
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=None)), \
         patch("custom_components.orvibo_mixpad.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert "password" not in result["data"]
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER}, data=user)
        assert result["reason"] == "already_configured"


async def test_setup_dynamic_additions_and_unload(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options={"discovery": False}, unique_id="test-account")
    entry.add_to_hass(hass)
    with patch("custom_components.orvibo_mixpad.runtime.Gateway.run", new=AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        runtime = entry.runtime_data
        assert len(runtime.gateways) == 1
        assert len(hass.states.async_all("light")) == 1
        gateway = runtime.gateways["test-gateway"]
        gateway.connected = True
        gateway.states[next(iter(runtime.relays))].push(0)
        runtime.changed()
        await hass.async_block_till_done()
        assert hass.states.async_all("light")[0].state == "on"
        relay = Relay("test-gateway", "second-test-relay", 0, "Second test relay")
        runtime.relays[relay.key] = relay
        runtime._reconcile()
        await hass.async_block_till_done()
        assert len(runtime.gateways) == 1
        assert len(hass.states.async_all("light")) == 2
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert not runtime.listeners
        assert all(task.done() for task in runtime.tasks)


async def test_options_and_reauth(hass):
    import json
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="test-account")
    entry.add_to_hass(hass)
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock()), \
         patch("homeassistant.config_entries.ConfigEntries.async_reload", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {
            "cloud_enabled": False, "refresh_seconds": 3600, "discovery": False,
            "topology": json.dumps(TOPOLOGY)})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        result = await hass.config_entries.flow.async_init(DOMAIN, context={
            "source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id}, data=entry.data)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "updated-synthetic"})
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data["password_hash"] == password_digest("updated-synthetic")
