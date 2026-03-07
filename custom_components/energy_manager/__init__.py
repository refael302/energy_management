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
    # Create or get device and link to config entry so entities show under it
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title or NAME,
        manufacturer=NAME,
    )
    coordinator = EnergyManagerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Link any existing entities that were created without device_id to this device
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
