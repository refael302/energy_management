"""
Energy Manager switches – Manual Mode Override, Manual Strategy Override.
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import (
    CONF_MANUAL_MODE_OVERRIDE,
    CONF_MANUAL_OVERRIDE,
    CONF_MANUAL_STRATEGY_OVERRIDE,
    DOMAIN,
    NAME,
)
from ..coordinator import EnergyManagerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Manager switches from a config entry."""
    coordinator: EnergyManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ManualModeOverrideSwitch(coordinator, entry),
        ManualStrategyOverrideSwitch(coordinator, entry),
    ])


class _BaseOverrideSwitch(
    CoordinatorEntity[EnergyManagerCoordinator], SwitchEntity
):
    """Base for manual override switches."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: EnergyManagerCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or NAME,
            manufacturer=NAME,
        )
        self._attr_icon = icon

    def _is_on(self) -> bool:
        data = self._entry.data or {}
        options = self._entry.options or {}
        if self._key in options:
            return bool(options[self._key])
        return bool(options.get(CONF_MANUAL_OVERRIDE, data.get(CONF_MANUAL_OVERRIDE, False)))

    async def _update_value(self, value: bool) -> None:
        options = dict(self._entry.options or {})
        options[self._key] = value
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ManualModeOverrideSwitch(_BaseOverrideSwitch):
    """Switch to use Manual Mode select; when off, mode is computed by the decision engine."""

    _attr_icon = "mdi:hand-back-right"
    _attr_name = "Manual Mode Override"

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, CONF_MANUAL_MODE_OVERRIDE, "Manual Mode Override", "mdi:hand-back-right")

    @property
    def is_on(self) -> bool:
        return self._is_on()

    async def async_turn_on(self, **kwargs) -> None:
        await self._update_value(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._update_value(False)


class ManualStrategyOverrideSwitch(_BaseOverrideSwitch):
    """Switch to use Manual Strategy select; when off, strategy is computed by recommend_battery_strategy."""

    _attr_icon = "mdi:strategy"
    _attr_name = "Manual Strategy Override"

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, CONF_MANUAL_STRATEGY_OVERRIDE, "Manual Strategy Override", "mdi:strategy")

    @property
    def is_on(self) -> bool:
        return self._is_on()

    async def async_turn_on(self, **kwargs) -> None:
        await self._update_value(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._update_value(False)
