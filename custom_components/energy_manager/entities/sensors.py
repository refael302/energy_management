"""
Energy Manager sensors – expose mode, forecast_remaining, battery_reserve_state, etc.
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
from homeassistant.const import UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import (
    BASELINE_PROFILE_BOOTSTRAP_KW,
    BASELINE_PROFILE_WINDOW_DAYS,
    BATTERY_POWER_STATE_OFF,
    BATTERY_POWER_STATE_OPTIONS,
    BATTERY_SOC_VERY_LOW_PERCENT,
    DOMAIN,
    EOD_BATTERY_TARGET_PLANNING_PERCENT,
    NAME,
)
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
            EnergyManagerModeReasonSensor(coordinator, entry),
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
            EnergyManagerHoursUntilSunriseSensor(coordinator, entry),
            EnergyManagerHoursUntilFirstPvSensor(coordinator, entry),
            EnergyManagerNightBridgeRelaxedSensor(coordinator, entry),
            EnergyManagerStrategyRecommendationSensor(coordinator, entry),
            EnergyManagerStrategyReasonSensor(coordinator, entry),
            EnergyManagerBatteryPowerStateSensor(coordinator, entry),
            EnergyManagerBatteryPowerLimitsSensor(coordinator, entry),
            EnergyManagerRecommendedToTurnOffSensor(coordinator, entry),
            EnergyManagerConsumersOnSensor(coordinator, entry),
            EnergyManagerBatteryRuntimeSensor(coordinator, entry),
            EnergyManagerBatteryTimeToFullSensor(coordinator, entry),
            EnergyManagerConsumerLearnedPowerSensor(coordinator, entry),
            EnergyManagerBaselineForecastSensor(coordinator, entry),
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


class EnergyManagerModeReasonSensor(EnergyManagerSensorBase):
    """Reason why the current energy mode (saving/normal/wasting) was chosen."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "mode_reason",
            "Mode Reason",
            icon="mdi:information-outline",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            self._attr_native_value = data.get("mode_reason", "")
        self.async_write_ha_state()


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
    """Forecast remaining today (kWh); hourly PV breakdown for today in attributes."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "forecast_remaining_kwh",
            "Forecast Remaining Today",
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.ENERGY,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is not None:
            if self._key in data:
                self._attr_native_value = data[self._key]
            self._attr_extra_state_attributes = {
                "hourly_forecast_today": data.get("forecast_today_remaining_hourly_kw")
                or [],
                "hourly_forecast_today_full": data.get("forecast_today_full_hourly_kw")
                or [],
                "forecast_today_hourly_times_iso": data.get(
                    "forecast_today_hourly_times_iso"
                )
                or [],
                "forecast_today_remaining_hourly_times_iso": data.get(
                    "forecast_today_remaining_hourly_times_iso"
                )
                or [],
                "current_hour_index": data.get("forecast_current_hour_index", -1),
            }
        self.async_write_ha_state()


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
    """Forecast solar production for tomorrow (kWh); hourly series for tomorrow in attributes."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "forecast_tomorrow_kwh",
            "Forecast Tomorrow",
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.ENERGY,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is not None:
            self._attr_native_value = data.get("forecast_tomorrow_kwh")
            self._attr_extra_state_attributes = {
                "hourly_forecast": data.get("forecast_tomorrow_hourly_kw") or [],
                "forecast_tomorrow_hourly_times_iso": data.get(
                    "forecast_tomorrow_hourly_times_iso"
                )
                or [],
            }
        self.async_write_ha_state()


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


class EnergyManagerHoursUntilSunriseSensor(EnergyManagerSensorBase):
    """Hours until next sunrise."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "hours_until_sunrise",
            "Hours Until Sunrise",
            icon="mdi:weather-sunset-up",
            state_class=SensorStateClass.MEASUREMENT,
            unit="h",
        )


class EnergyManagerHoursUntilFirstPvSensor(EnergyManagerSensorBase):
    """Whole hours until forecast PV exceeds threshold (from current slot)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "hours_until_first_pv",
            "Hours Until Forecast PV",
            icon="mdi:solar-panel",
            state_class=SensorStateClass.MEASUREMENT,
            unit="h",
            entity_category=EntityCategory.DIAGNOSTIC,
        )


class EnergyManagerNightBridgeRelaxedSensor(EnergyManagerSensorBase):
    """Whether next-hour PV check is relaxed (night bridge near sunrise)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "night_bridge_relaxed",
            "Night Bridge Relaxed",
            icon="mdi:bridge",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is not None:
            relaxed = data.get("night_bridge_relaxed")
            self._attr_native_value = "on" if relaxed else "off"
        self.async_write_ha_state()


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


class EnergyManagerBatteryPowerStateSensor(EnergyManagerSensorBase):
    """Unified battery direction/level: off, charge, max_charge, discharge, max_discharge."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "battery_power_state",
            "Battery power state",
            icon="mdi:battery-sync",
            device_class=SensorDeviceClass.ENUM,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        self._attr_options = list(BATTERY_POWER_STATE_OPTIONS)

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            self._attr_native_value = data.get(
                "battery_power_state", BATTERY_POWER_STATE_OFF
            )
            self._attr_extra_state_attributes = {
                "charge_state": data.get("charge_state"),
                "discharge_state": data.get("discharge_state"),
            }
        self.async_write_ha_state()


class EnergyManagerBatteryPowerLimitsSensor(EnergyManagerSensorBase):
    """Effective max discharge power (kW) from learned peaks; charge peak and learn metadata in attributes."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "battery_power_limits",
            "Battery power limits",
            icon="mdi:battery-charging-high",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data:
            self._attr_native_value = data.get("battery_effective_max_discharge_kw")
            self._attr_extra_state_attributes = {
                "effective_max_charge_kw": data.get("battery_effective_max_charge_kw"),
                "learned_max_discharge_kw": data.get("battery_learned_max_discharge_kw"),
                "learned_max_charge_kw": data.get("battery_learned_max_charge_kw"),
                "manual_max_discharge_kw": data.get("battery_peak_manual_discharge_kw"),
                "manual_max_charge_kw": data.get("battery_peak_manual_charge_kw"),
                "sample_ticks": data.get("battery_peak_sample_ticks"),
                "learn_state": data.get("battery_peak_learn_state"),
            }
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


class EnergyManagerConsumersOnSensor(EnergyManagerSensorBase):
    """Number of configured consumer switches/input_booleans that are currently on (displayed as on/total)."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "consumers_on_count",
            "Consumers On",
            icon="mdi:counter",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is not None:
            on_count = data.get("consumers_on_count", 0)
            total = data.get("consumers_total", 0)
            self._attr_native_value = f"{on_count}/{total}"
            self._attr_extra_state_attributes = {
                "on_count": on_count,
                "total": total,
            }
        self.async_write_ha_state()


class EnergyManagerBatteryRuntimeSensor(EnergyManagerSensorBase):
    """Time until SOC reaches very low: PV vs baseline forecast, else instantaneous discharge."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "battery_runtime_hours",
            "Battery Runtime",
            icon="mdi:battery-clock",
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfTime.HOURS,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        self._attr_unique_id = f"{entry.entry_id}_battery_runtime_hhmm"

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is not None:
            hrs = data.get("battery_runtime_hours")
            self._attr_extra_state_attributes = {
                "hhmm": data.get("battery_runtime_hhmm", "99:59"),
                "edge_time_iso": data.get("battery_horizon_to_very_low_edge_iso"),
                "method": data.get("battery_horizon_method", "instantaneous"),
                "target_soc_percent": BATTERY_SOC_VERY_LOW_PERCENT,
                "hourly_projection": data.get("battery_horizon_hourly") or [],
            }
            if hrs is None:
                self._attr_available = False
            else:
                self._attr_available = True
                self._attr_native_value = round(float(hrs), 4)
        self.async_write_ha_state()


class EnergyManagerBaselineForecastSensor(EnergyManagerSensorBase):
    """Learned baseline house load (kW) for the current local hour; hourly profile and daily estimate in attributes."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "baseline_forecast_kw",
            "Baseline forecast",
            icon="mdi:home-lightning-bolt-outline",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is not None:
            self._attr_native_value = data.get("baseline_forecast_kw", BASELINE_PROFILE_BOOTSTRAP_KW)
            hourly = data.get("baseline_hourly_forecast_kw") or []
            hour_map = {str(h): hourly[h] for h in range(min(24, len(hourly)))}
            self._attr_extra_state_attributes = {
                "hourly_forecast_kw": hour_map,
                "estimated_daily_kwh": data.get("baseline_estimated_daily_kwh"),
                "completed_days": data.get("baseline_completed_days"),
                "window_days": BASELINE_PROFILE_WINDOW_DAYS,
                "sample_recorded_last_update": data.get("baseline_sample_recorded"),
            }
        self.async_write_ha_state()


class EnergyManagerConsumerLearnedPowerSensor(EnergyManagerSensorBase):
    """Sum of learned per-consumer power (kW); attributes list each consumer and pending sample counts."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "consumer_learned_power_kw",
            "Consumer Learned Power",
            icon="mdi:transmission-tower",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is not None:
            self._attr_native_value = data.get("consumer_learned_power_kw", 0.0)
            self._attr_extra_state_attributes = {
                "consumers_kw": data.get("consumer_learned_kw") or {},
                "pending_samples": data.get("consumer_learn_pending_samples") or {},
            }
        self.async_write_ha_state()


class EnergyManagerBatteryTimeToFullSensor(EnergyManagerSensorBase):
    """Time until SOC reaches planning full: PV vs baseline forecast, else instantaneous charge."""

    def __init__(self, coordinator: EnergyManagerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator,
            entry,
            "battery_time_to_full_hours",
            "Battery Time To Full",
            icon="mdi:battery-clock-outline",
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.MEASUREMENT,
            unit=UnitOfTime.HOURS,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        self._attr_unique_id = f"{entry.entry_id}_battery_time_to_full_hhmm"

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is not None:
            hrs = data.get("battery_time_to_full_hours")
            self._attr_extra_state_attributes = {
                "hhmm": data.get("battery_time_to_full_hhmm", "99:59"),
                "edge_time_iso": data.get("battery_horizon_to_full_edge_iso"),
                "method": data.get("battery_horizon_method", "instantaneous"),
                "target_soc_percent": EOD_BATTERY_TARGET_PLANNING_PERCENT,
                "hourly_projection": data.get("battery_horizon_hourly") or [],
            }
            if hrs is None:
                self._attr_available = False
            else:
                self._attr_available = True
                self._attr_native_value = round(float(hrs), 4)
        self.async_write_ha_state()
