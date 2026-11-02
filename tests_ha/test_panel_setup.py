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
USER = {"mixpad_ips": ["192.168.50.20"], "username": "synthetic-user", "password": "synthetic-password",
        "cloud_enabled": True, "server": "usa.orvibo.com"}


async def test_ip_first_cloud_setup_imports_only_one_panel(hass):
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=INVENTORY)), \
         patch("custom_components.orvibo_mixpad.onboarding.identify_panel", new=AsyncMock(return_value=FIRST.uid)), \
         patch("custom_components.orvibo_mixpad.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        data = result["data"]
        assert data["selected_gateways"] == [FIRST.uid]
        assert data["initial_relays"] == [FIRST.as_row()]
        assert data["topology"]["gateways"] == {FIRST.uid: USER["mixpad_ips"][0]}
        assert "password" not in data


async def test_blank_uid_ambiguous_ip_asks_for_named_panel(hass):
    confirm = AsyncMock()
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=INVENTORY)), \
         patch("custom_components.orvibo_mixpad.onboarding.identify_panel", new=AsyncMock(return_value=None)), \
         patch("custom_components.orvibo_mixpad.onboarding.confirm_panel", new=confirm), \
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
            "topology": {"gateways": {FIRST.uid: USER["mixpad_ips"][0]}, "relays": []}}
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id="synthetic-account")
    entry.add_to_hass(hass)
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=INVENTORY)), \
         patch("custom_components.orvibo_mixpad.onboarding.identify_panel", new=AsyncMock(return_value=SECOND.uid)):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "hubs"})
        result = await hass.config_entries.options.async_configure(result["flow_id"], {
            "mixpad_ips": ["192.168.50.21"]})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        options = result["data"]
        assert options["selected_gateways"] == [FIRST.uid, SECOND.uid]
        assert options["topology"]["gateways"] == {FIRST.uid: "192.168.50.20", SECOND.uid: "192.168.50.21"}
        assert len(options["imported_relays"]) == 2
        assert "mixpad_ip" not in options


async def test_invalid_ip_fails_before_cloud_or_panel_requests(hass):
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock()) as validate:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER},
                                                         data=dict(USER, mixpad_ips=["8.8.8.8"]))
        assert result["errors"]["base"] == "invalid_ip"
        validate.assert_not_awaited()


async def test_multiple_hubs_on_first_screen_cloud_defaults_on(hass):
    identify = AsyncMock(side_effect=[FIRST.uid, SECOND.uid])
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=INVENTORY)) as validate, \
         patch("custom_components.orvibo_mixpad.onboarding.identify_panel", new=identify), \
         patch("custom_components.orvibo_mixpad.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        supplied = dict(USER, mixpad_ips=["192.168.50.20", "192.168.50.21"])
        supplied.pop("cloud_enabled")
        result = await hass.config_entries.flow.async_configure(result["flow_id"], supplied)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["cloud_enabled"] is True
        assert result["data"]["selected_gateways"] == [FIRST.uid, SECOND.uid]
        assert len(result["data"]["initial_relays"]) == 2
        validate.assert_awaited_once()
        assert identify.await_count == 2


async def test_multiple_hubs_with_ambiguous_second_panel(hass):
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=INVENTORY)), \
         patch("custom_components.orvibo_mixpad.onboarding.identify_panel", new=AsyncMock(side_effect=[FIRST.uid, None])), \
         patch("custom_components.orvibo_mixpad.onboarding.confirm_panel", new=AsyncMock()), \
         patch("custom_components.orvibo_mixpad.async_setup_entry", new=AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER},
                                                         data=dict(USER, mixpad_ips=["192.168.50.20", "192.168.50.21"]))
        assert result["step_id"] == "select_gateway"
        assert result["description_placeholders"]["current"] == "2"
        assert result["description_placeholders"]["total"] == "2"
        assert not hass.config_entries.async_entries(DOMAIN)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"gateway_uid": SECOND.uid})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert len(result["data"]["selected_gateways"]) == 2


async def test_failed_second_hub_does_not_create_partial_entry(hass):
    from custom_components.orvibo_mixpad.protocol import ProtocolError
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock(return_value=INVENTORY)), \
         patch("custom_components.orvibo_mixpad.onboarding.identify_panel", new=AsyncMock(
             side_effect=[FIRST.uid, ProtocolError("synthetic failure")])):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER},
                                                         data=dict(USER, mixpad_ips=["192.168.50.20", "192.168.50.21"]))
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "cannot_connect"
        assert not hass.config_entries.async_entries(DOMAIN)


async def test_options_menu_shows_hubs_and_preserves_cloud_opt_out(hass):
    data = {"username": "synthetic-user", "password_hash": "SYNTHETIC-HASH", "cloud_enabled": False,
            "server": "usa.orvibo.com", "initial_relays": [FIRST.as_row()],
            "topology": {"gateways": {FIRST.uid: "192.168.50.20"}, "relays": []}}
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id="synthetic-account")
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["hubs", "settings"]
    assert "192.168.50.20" in result["description_placeholders"]["hubs"]
    with patch("custom_components.orvibo_mixpad.config_flow.validate", new=AsyncMock()) as validate:
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
        result = await hass.config_entries.options.async_configure(result["flow_id"], {
            "refresh_seconds": 1800, "discovery": True})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["cloud_enabled"] is False
        validate.assert_not_awaited()
