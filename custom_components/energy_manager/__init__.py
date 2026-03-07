"""Energy Manager – Home Assistant integration for solar energy management."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN, NAME
from .coordinator import EnergyManagerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


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
            identifiers=our_identifiers,
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
