"""
Energy Manager sensors – expose mode, available_power, forecast_remaining, battery_reserve_state, etc.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN, NAME
from ..coordinator import EnergyManagerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Energy Manager sensors from a config entry."""
    coordinator: EnergyManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EnergyManagerModeSensor(coordinator, entry),
            EnergyManagerAvailablePowerSensor(coordinator, entry),
            EnergyManagerBatterySocSensor(coordinator, entry),
            EnergyManagerSolarProductionSensor(coordinator, entry),
            EnergyManagerHouseConsumptionSensor(coordinator, entry),
            EnergyManagerBatteryPowerSensor(coordinator, entry),
            EnergyManagerForecastRemainingSensor(coordinator, entry),
            EnergyManagerForecastNextHourSensor(coordinator, entry),
            EnergyManagerForecastCurrentPowerSensor(coordinator, entry),
            EnergyManagerForecastTomorrowSensor(coordinator, entry),
            EnergyManagerBatteryReserveStateSensor(coordinator, entry),
            EnergyManagerDailyMarginSensor(coordinator, entry),
            EnergyManagerNeededEnergyTodaySensor(coordinator, entry),
            EnergyManagerPvRemainingSafeSensor(coordinator, entry),
            EnergyManagerHoursUntilEodSensor(coordinator, entry),
            EnergyManagerStrategyRecommendationSensor(coordinator, entry),
            EnergyManagerStrategyReasonSensor(coordinator, entry),
            EnergyManagerChargeStateSensor(coordinator, entry),
            EnergyManagerDischargeStateSensor(coordinator, entry),
            EnergyManagerCanTurnOnHeavyConsumerSensor(coordinator, entry),
            EnergyManagerCanWasteEnergySensor(coordinator, entry),
            EnergyManagerRecommendedToTurnOffSensor(coordinator, entry),
        ]
    )


class EnergyManagerSensorBase(CoordinatorEntity[EnergyManagerCoordinator], SensorEntity):
    """Base class for Energy Manager sensors."""

    def __init__(
        self,
        coordinator: EnergyManagerCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str | None = None,
        device_class: str | None = None,
        state_class: str | None = None,
        unit: str | None = None,
        entity_category: EntityCategory | None = None,
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
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._attr_entity_category = entity_category

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data and self._key in data:
            self._attr_native_value = data[self._key]
        self.async_write_ha_state()


class EnergyManagerModeSensor(EnergyManagerSensorBase):
    """Current energy manager mode: saving / normal / wasting."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "energy_manager_mode",
            "Energy Manager Mode",
            icon="mdi:leaf",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            self._attr_native_value = data.get("energy_manager_mode", "unknown")
        self.async_write_ha_state()


class EnergyManagerAvailablePowerSensor(EnergyManagerSensorBase):
    """Available power (solar + battery - house consumption) in kW."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "available_power_kw",
            "Available Power",
            icon="mdi:flash",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfPower.KILO_WATT,
        )


class EnergyManagerBatterySocSensor(EnergyManagerSensorBase):
    """Battery state of charge (%)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "battery_soc",
            "Battery SOC",
            icon="mdi:battery",
            state_class=SensorStateClass.MEASUREMENT,
            unit="%",
        )


class EnergyManagerSolarProductionSensor(EnergyManagerSensorBase):
    """Current solar production (kW)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "solar_production_kw",
            "Solar Production",
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfPower.KILO_WATT,
        )


class EnergyManagerHouseConsumptionSensor(EnergyManagerSensorBase):
    """Current house consumption (kW)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "house_consumption_kw",
            "House Consumption",
            icon="mdi:home-lightning-bolt",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfPower.KILO_WATT,
        )


class EnergyManagerBatteryPowerSensor(EnergyManagerSensorBase):
    """Battery power (kW); positive = discharge, negative = charge."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "battery_power_kw",
            "Battery Power",
            icon="mdi:battery-charging",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfPower.KILO_WATT,
        )


class EnergyManagerForecastRemainingSensor(EnergyManagerSensorBase):
    """Forecast remaining today (kWh)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "forecast_remaining_kwh",
            "Forecast Remaining Today",
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
        )


class EnergyManagerForecastNextHourSensor(EnergyManagerSensorBase):
    """Forecast energy for next hour (kWh)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "forecast_next_hour_kwh",
            "Forecast Next Hour",
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
        )


class EnergyManagerForecastCurrentPowerSensor(EnergyManagerSensorBase):
    """Forecast current solar power (kW)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "forecast_current_power_kw",
            "Forecast Current Power",
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfPower.KILO_WATT,
        )


class EnergyManagerForecastTomorrowSensor(EnergyManagerSensorBase):
    """Forecast solar production for tomorrow (kWh)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "forecast_tomorrow_kwh",
            "Forecast Tomorrow",
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
        )


class EnergyManagerBatteryReserveStateSensor(EnergyManagerSensorBase):
    """Battery reserve state: very low / low / medium / high / full."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "battery_reserve_state",
            "Battery Reserve State",
            icon="mdi:battery-charging",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            self._attr_native_value = data.get("battery_reserve_state", "unknown")
        self.async_write_ha_state()


class EnergyManagerDailyMarginSensor(EnergyManagerSensorBase):
    """Daily margin (kWh): PV remaining safe - needed energy today."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "daily_margin_kwh",
            "Daily Margin",
            icon="mdi:delta",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
        )


class EnergyManagerNeededEnergyTodaySensor(EnergyManagerSensorBase):
    """Needed energy until end of day (kWh)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "needed_energy_today_kwh",
            "Needed Energy Today",
            icon="mdi:flash",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
        )


class EnergyManagerPvRemainingSafeSensor(EnergyManagerSensorBase):
    """PV remaining today with safety factor applied (kWh)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "pv_remaining_today_safe_kwh",
            "PV Remaining Today (Safe)",
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
        )


class EnergyManagerHoursUntilEodSensor(EnergyManagerSensorBase):
    """Hours until end of day (sunset)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "hours_until_eod",
            "Hours Until End of Day",
            icon="mdi:clock-outline",
            state_class=SensorStateClass.MEASUREMENT,
            unit="h",
        )


class EnergyManagerStrategyRecommendationSensor(EnergyManagerSensorBase):
    """Strategy level: low / medium / high / full."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "strategy_recommendation",
            "Strategy Recommendation",
            icon="mdi:strategy",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            self._attr_native_value = data.get("strategy_recommendation", "unknown")
        self.async_write_ha_state()


class EnergyManagerStrategyReasonSensor(EnergyManagerSensorBase):
    """Reason for current battery strategy recommendation."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "strategy_reason",
            "Strategy Reason",
            icon="mdi:text-box",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            self._attr_native_value = data.get("strategy_reason", "")
        self.async_write_ha_state()


class EnergyManagerChargeStateSensor(EnergyManagerSensorBase):
    """Battery charge state: off / on / max."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "charge_state",
            "Charge State",
            icon="mdi:battery-arrow-up",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            self._attr_native_value = data.get("charge_state", "unknown")
        self.async_write_ha_state()


class EnergyManagerDischargeStateSensor(EnergyManagerSensorBase):
    """Battery discharge state: off / on / max."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "discharge_state",
            "Discharge State",
            icon="mdi:battery-arrow-down",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            self._attr_native_value = data.get("discharge_state", "unknown")
        self.async_write_ha_state()


class EnergyManagerCanTurnOnHeavyConsumerSensor(EnergyManagerSensorBase):
    """Whether a heavy consumer can be turned on (on/off)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "can_turn_on_heavy_consumer",
            "Can Turn On Heavy Consumer",
            icon="mdi:power-plug",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            val = data.get("can_turn_on_heavy_consumer", False)
            self._attr_native_value = "on" if val else "off"
        self.async_write_ha_state()


class EnergyManagerCanWasteEnergySensor(EnergyManagerSensorBase):
    """Whether energy wasting mode is allowed (on/off)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "can_waste_energy",
            "Can Waste Energy",
            icon="mdi:flash",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            val = data.get("can_waste_energy", False)
            self._attr_native_value = "on" if val else "off"
        self.async_write_ha_state()


class EnergyManagerRecommendedToTurnOffSensor(EnergyManagerSensorBase):
    """Recommendation to turn off intermediate devices when battery low and forecast short. State on = recommendation active."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "recommended_to_turn_off",
            "Recommended to turn off",
            icon="mdi:lightbulb-off-outline",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        entity_ids: list[str] = []
        if data:
            entity_ids = data.get("recommended_to_turn_off_entity_ids") or []
        self._attr_native_value = "on" if entity_ids else "off"
        self._attr_extra_state_attributes = {"entity_id": entity_ids}
        self.async_write_ha_state()
