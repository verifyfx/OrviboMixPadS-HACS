"""Allowlisted diagnostics; never include account, topology or raw packets."""


async def async_get_config_entry_diagnostics(hass, entry):
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return {"loaded": False}
    return {"cloud_enabled": runtime.cloud is not None,
            "cloud_ok": runtime.cloud_ok,
            "inventory_completeness_verified": runtime.inventory_complete,
            "gateway_count": len(runtime.gateways),
            "connected_gateways": sum(g.connected for g in runtime.gateways.values()),
            "supported_relay_count": len(runtime.relays),
            "cloud_failures": runtime.cloud.failures if runtime.cloud else 0}
