"""
Energy Manager switches – Manual Mode Override, Manual Strategy Override,
per-consumer cycle control (quick neutral).
"""

from __future__ import annotations

import logging
import re

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import (
    CONF_CONSUMER_CYCLE_ENABLED,
    CONF_CONSUMERS,
    CONF_CONSUMER_SWITCH_ENTITY_ID,
    CONF_MANUAL_MODE_OVERRIDE,
    CONF_MANUAL_OVERRIDE,
    CONF_MANUAL_STRATEGY_OVERRIDE,
    DOMAIN,
    NAME,
)
from ..consumer_cycle import is_consumer_cycle_enabled
from ..coordinator import EnergyManagerCoordinator, _normalize_consumers

_LOGGER = logging.getLogger(__name__)


def _entity_slug(entity_id: str) -> str:
    """ASCII slug safe for entity object_id / unique_id suffix."""
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", entity_id).strip("_")
    return slug or "consumer"


def _consumer_label(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state is not None:
        friendly = state.attributes.get("friendly_name")
        if isinstance(friendly, str) and friendly.strip():
            return friendly.strip()
    if "." in entity_id:
        return entity_id.split(".", 1)[1]
    return entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Manager switches from a config entry."""
    coordinator: EnergyManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    merged = {**entry.data, **(entry.options or {})}
    consumers = _normalize_consumers(merged.get(CONF_CONSUMERS))

    entities: list[SwitchEntity] = [
        ManualModeOverrideSwitch(coordinator, entry),
        ManualStrategyOverrideSwitch(coordinator, entry),
    ]
    cycle_count = 0
    for consumer in consumers:
        switch_eid = consumer.get(CONF_CONSUMER_SWITCH_ENTITY_ID)
        if isinstance(switch_eid, str) and switch_eid:
            entities.append(ConsumerCycleSwitch(coordinator, entry, switch_eid))
            cycle_count += 1
    async_add_entities(entities)
    _LOGGER.info(
        "Energy Manager: registered %d consumer cycle switch(es) for entry %s",
        cycle_count,
        entry.entry_id,
    )


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


class ConsumerCycleSwitch(CoordinatorEntity[EnergyManagerCoordinator], SwitchEntity):
    """Per-consumer switch: on = integration auto-controls; off = quick neutral (out of cycle)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:sync"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EnergyManagerCoordinator,
        entry: ConfigEntry,
        consumer_entity_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._consumer_entity_id = consumer_entity_id
        slug = _entity_slug(consumer_entity_id)
        self._object_slug = slug
        self._attr_unique_id = f"{entry.entry_id}_consumer_cycle_{slug}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title or NAME,
            manufacturer=NAME,
        )
        # ASCII fallback until async_added_to_hass (Hebrew names break object_id slug).
        self._attr_name = f"{slug} auto control"

    @property
    def suggested_object_id(self) -> str:
        return f"consumer_cycle_{self._object_slug}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        label = _consumer_label(self.hass, self._consumer_entity_id)
        self._attr_name = f"{label} auto control"
        self.async_write_ha_state()

    def _enabled_map(self) -> dict[str, bool]:
        options = self._entry.options or {}
        raw = options.get(CONF_CONSUMER_CYCLE_ENABLED) or {}
        if isinstance(raw, dict):
            return {str(k): bool(v) for k, v in raw.items()}
        return {}

    @property
    def is_on(self) -> bool:
        return is_consumer_cycle_enabled(self._consumer_entity_id, self._enabled_map())

    @property
    def icon(self) -> str:
        return "mdi:sync" if self.is_on else "mdi:sync-off"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"consumer_entity_id": self._consumer_entity_id}

    async def _set_cycle_enabled(self, enabled: bool) -> None:
        options = dict(self._entry.options or {})
        enabled_map = dict(options.get(CONF_CONSUMER_CYCLE_ENABLED) or {})
        enabled_map[self._consumer_entity_id] = enabled
        options[CONF_CONSUMER_CYCLE_ENABLED] = enabled_map
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set_cycle_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_cycle_enabled(False)
