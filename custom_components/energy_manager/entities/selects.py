"""
Energy Manager select entities – Manual Mode and Manual Strategy (for testing when Manual Override is on).
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import (
    CONF_MANUAL_MODE,
    CONF_MANUAL_STRATEGY,
    DOMAIN,
    NAME,
    STRATEGY_FULL,
    STRATEGY_HIGH,
    STRATEGY_LOW,
    STRATEGY_MEDIUM,
    STRATEGY_OPTIONS,
    SYSTEM_MODE_NORMAL,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)
from ..coordinator import EnergyManagerCoordinator

MANUAL_MODE_OPTIONS = [SYSTEM_MODE_SAVING, SYSTEM_MODE_NORMAL, SYSTEM_MODE_WASTING]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Manager select entities from a config entry."""
    coordinator: EnergyManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ManualModeSelect(coordinator, entry),
        ManualStrategySelect(coordinator, entry),
    ])


class _BaseSelect(
    CoordinatorEntity[EnergyManagerCoordinator], SelectEntity
):
    """Base for manual override select entities."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: EnergyManagerCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str,
        options: list[str],
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
        self._attr_options = options

    def _default_option(self) -> str:
        """Override in subclass to provide default when not set."""
        return self._attr_options[0] if self._attr_options else ""

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        data = self._entry.data or {}
        options = self._entry.options or {}
        value = options.get(self._key) or data.get(self._key)
        if value in self._attr_options:
            return value
        default = self._default_option()
        return default if default in self._attr_options else (self._attr_options[0] if self._attr_options else None)

    async def _update_option(self, value: str) -> None:
        opts = dict(self._entry.options or {})
        opts[self._key] = value
        self.hass.config_entries.async_update_entry(self._entry, options=opts)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ManualModeSelect(_BaseSelect):
    """Select for manual energy mode (saving / normal / wasting) when Manual Override is on."""

    def _default_option(self) -> str:
        return SYSTEM_MODE_NORMAL

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            CONF_MANUAL_MODE,
            "Manual Mode",
            "mdi:leaf",
            MANUAL_MODE_OPTIONS,
        )

    async def async_select_option(self, option: str) -> None:
        """Set the manual mode."""
        if option in self._attr_options:
            await self._update_option(option)


class ManualStrategySelect(_BaseSelect):
    """Select for manual strategy (low / medium / high / full) when Manual Override is on."""

    def _default_option(self) -> str:
        return STRATEGY_MEDIUM

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            CONF_MANUAL_STRATEGY,
            "Manual Strategy",
            "mdi:strategy",
            STRATEGY_OPTIONS,
        )

    async def async_select_option(self, option: str) -> None:
        """Set the manual strategy."""
        if option in self._attr_options:
            await self._update_option(option)
