"""
Energy Manager switches – Manual Override, etc.
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import CONF_MANUAL_OVERRIDE, DOMAIN, NAME
from ..coordinator import EnergyManagerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Manager switches from a config entry."""
    coordinator: EnergyManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ManualOverrideSwitch(coordinator, entry)])


class ManualOverrideSwitch(
    CoordinatorEntity[EnergyManagerCoordinator], SwitchEntity
):
    """Switch to enable/disable manual override (no auto mode/strategy changes)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:hand-back-right"
    _attr_name = "Manual Override"

    def __init__(
        self,
        coordinator: EnergyManagerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_manual_override"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or NAME,
            manufacturer=NAME,
        )

    @property
    def is_on(self) -> bool:
        """Return True if manual override is enabled."""
        data = self._entry.data or {}
        options = self._entry.options or {}
        return bool(options.get(CONF_MANUAL_OVERRIDE, data.get(CONF_MANUAL_OVERRIDE, False)))

    async def async_turn_on(self, **kwargs) -> None:
        """Enable manual override."""
        await self._update_override(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable manual override."""
        await self._update_override(False)

    async def _update_override(self, value: bool) -> None:
        options = dict(self._entry.options or {})
        options[CONF_MANUAL_OVERRIDE] = value
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
