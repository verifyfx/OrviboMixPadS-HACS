"""Account inventory is filtered to each explicitly configured MixPad."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.orvibo_mixpad.cloud import Snapshot
from custom_components.orvibo_mixpad.const import DOMAIN
from custom_components.orvibo_mixpad.models import Relay

FIRST = Relay("first-test-panel", "first-test-light", 1, "First light")
SECOND = Relay("second-test-panel", "second-test-light", 0, "Second light")
INVENTORY = Snapshot({r.key: r for r in (FIRST, SECOND)}, {FIRST.uid: "192.168.50.20"}, [], 1)
USER = {"mixpad_ip": "192.168.50.20", "username": "synthetic-user", "password": "synthetic-password",
        "cloud_enabled": True, "server": "usa.orvibo.com"}


async def test_ip_first_cloud_setup_imports_only_one_panel(hass):
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=INVENTORY)), \
         patch("custom_components.orvibo_mixpad.config_flow.identify_panel", new=AsyncMock(return_value=FIRST.uid)), \
         patch("custom_components.orvibo_mixpad.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        data = result["data"]
        assert data["selected_gateways"] == [FIRST.uid]
        assert data["initial_relays"] == [FIRST.as_row()]
        assert data["topology"]["gateways"] == {FIRST.uid: USER["mixpad_ip"]}
        assert "password" not in data


async def test_blank_uid_ambiguous_ip_asks_for_named_panel(hass):
    confirm = AsyncMock()
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=INVENTORY)), \
         patch("custom_components.orvibo_mixpad.config_flow.identify_panel", new=AsyncMock(return_value=None)), \
         patch("custom_components.orvibo_mixpad.config_flow.confirm_panel", new=confirm), \
         patch("custom_components.orvibo_mixpad.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER}, data=USER)
        assert result["step_id"] == "select_gateway"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"gateway_uid": FIRST.uid})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["initial_relays"] == [FIRST.as_row()]
        confirm.assert_awaited_once()


async def test_add_second_panel_in_options_preserves_first(hass):
    data = {"username": "synthetic-user", "password_hash": "SYNTHETIC-HASH", "cloud_enabled": True,
            "server": "usa.orvibo.com", "selected_gateways": [FIRST.uid],
            "initial_relays": [FIRST.as_row()],
            "topology": {"gateways": {FIRST.uid: USER["mixpad_ip"]}, "relays": []}}
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id="synthetic-account")
    entry.add_to_hass(hass)
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=INVENTORY)), \
         patch("custom_components.orvibo_mixpad.config_flow.identify_panel", new=AsyncMock(return_value=SECOND.uid)):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {
            "mixpad_ip": "192.168.50.21", "cloud_enabled": True, "refresh_seconds": 1800, "discovery": True})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        options = result["data"]
        assert options["selected_gateways"] == [FIRST.uid, SECOND.uid]
        assert options["topology"]["gateways"] == {FIRST.uid: "192.168.50.20", SECOND.uid: "192.168.50.21"}
        assert len(options["imported_relays"]) == 2
        assert "mixpad_ip" not in options


async def test_invalid_ip_fails_before_cloud_or_panel_requests(hass):
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock()) as validate:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER},
                                                         data=dict(USER, mixpad_ip="8.8.8.8"))
        assert result["errors"]["base"] == "invalid_ip"
        validate.assert_not_awaited()
