"""Energy Manager – Home Assistant integration for solar energy management."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er

from .const import DOMAIN, NAME, SERVICE_RESET_CONSUMER_LEARN
from .coordinator import EnergyManagerCoordinator
from .engine.consumer_learn_cache import consumer_learn_fingerprint

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.SELECT]

RESET_CONSUMER_LEARN_SCHEMA = vol.Schema(
    {vol.Optional("config_entry_id"): cv.string}
)


async def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_RESET_CONSUMER_LEARN):
        return

    async def handle_reset_consumer_learn(call: ServiceCall) -> None:
        entry_id = call.data.get("config_entry_id")
        domain_data = hass.data.get(DOMAIN)
        if not isinstance(domain_data, dict):
            return
        if entry_id:
            targets = [entry_id] if entry_id in domain_data else []
        else:
            targets = [
                k
                for k, v in domain_data.items()
                if isinstance(k, str) and hasattr(v, "consumer_learner")
            ]
        for eid in targets:
            coord = domain_data.get(eid)
            if coord is None or not hasattr(coord, "consumer_learner"):
                continue
            cfg = {**coord.entry.data, **(coord.entry.options or {})}
            fp = consumer_learn_fingerprint(cfg)
            await coord.consumer_learner.async_reset(fp)
            if coord.data is not None:
                coord.async_set_updated_data(
                    {
                        **coord.data,
                        "consumer_learned_kw": coord.consumer_learner.get_learned_kw(),
                        "consumer_learned_power_kw": 0.0,
                        "consumer_learn_pending_samples": coord.consumer_learner.get_pending_counts(),
                    }
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_CONSUMER_LEARN,
        handle_reset_consumer_learn,
        schema=RESET_CONSUMER_LEARN_SCHEMA,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Manager from a config entry."""
    if not isinstance(hass.data.get(DOMAIN), dict):
        hass.data[DOMAIN] = {}
    # Single device for this config entry (avoid duplicate "refael302" vs "Energy Manager")
    dev_reg = dr.async_get(hass)
    our_identifiers = {(DOMAIN, entry.entry_id)}
    devices_with_entry = [
        d for d in dev_reg.devices.values()
        if entry.entry_id in d.config_entries
    ]
    if devices_with_entry:
        # Use first device that already has our identifiers, or take the first and adopt it
        device = next(
            (d for d in devices_with_entry if d.identifiers == our_identifiers),
            devices_with_entry[0],
        )
        dev_reg.async_update_device(
            device.id,
            new_identifiers=our_identifiers,
            name=entry.title or NAME,
            manufacturer=NAME,
        )
        # Unlink other devices from this config entry so only one device remains
        for other in devices_with_entry:
            if other.id != device.id:
                dev_reg.async_update_device(other.id, remove_config_entry_id=entry.entry_id)
    else:
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers=our_identifiers,
            name=entry.title or NAME,
            manufacturer=NAME,
        )
    coordinator = EnergyManagerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Link all entities for this config entry to this device
    ent_reg = er.async_get(hass)
    for ent_entry in ent_reg.entities.values():
        if ent_entry.config_entry_id == entry.entry_id and ent_entry.device_id != device.id:
            ent_reg.async_update_entity(ent_entry.entity_id, device_id=device.id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        if isinstance(hass.data.get(DOMAIN), dict):
            hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
