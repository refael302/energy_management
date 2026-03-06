"""
Data coordinator – polls sensors and forecast every 30s, runs decision engine and load manager.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_BASELINE_CONSUMPTION,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CURRENT_SENSOR,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_CONSUMER_DELAY,
    CONF_CONSUMER_SWITCHES,
    CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT,
    CONF_DISCHARGE_LIMIT_PERCENT,
    CONF_EOD_BATTERY_TARGET,
    CONF_HOUSE_CONSUMPTION_SENSOR,
    CONF_LATITUDE,
    CONF_LIGHTS_TO_TURN_OFF,
    CONF_LONGITUDE,
    CONF_MAX_BATTERY_CURRENT_AMPS,
    CONF_MINIMUM_BATTERY_RESERVE,
    CONF_SAFETY_FORECAST_FACTOR,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_STRINGS,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .engine import DecisionEngine, EnergyModel, ForecastEngine, LoadManager

_LOGGER = logging.getLogger(__name__)


def _float_state(hass: HomeAssistant, entity_id: str) -> float:
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        return 0.0
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return 0.0


def _hours_until_sunset(hass: HomeAssistant) -> float:
    sun = hass.states.get("sun.sun")
    if sun is None:
        return 0.0
    next_set = sun.attributes.get("next_setting")
    if next_set is None:
        return 0.0
    try:
        from homeassistant.util import dt as dt_util
        end_ts = dt_util.as_timestamp(next_set)
        now_ts = datetime.now(timezone.utc).timestamp()
        return max(0.0, round((end_ts - now_ts) / 3600, 2))
    except Exception:
        return 0.0


class EnergyManagerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Fetches sensor data and forecast every UPDATE_INTERVAL, updates EnergyModel,
    runs DecisionEngine, applies LoadManager, and exposes data for sensors.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        data = dict(entry.data)
        data.update(entry.options or {})
        self._config = data
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.model = EnergyModel(
            battery_capacity_kwh=float(data.get(CONF_BATTERY_CAPACITY, 20)),
            baseline_consumption_kw=float(data.get(CONF_BASELINE_CONSUMPTION, 0.8)),
            eod_battery_target_percent=float(data.get(CONF_EOD_BATTERY_TARGET, 90)),
            emergency_reserve_percent=float(data.get(CONF_MINIMUM_BATTERY_RESERVE, 20)),
            safety_forecast_factor_percent=float(data.get(CONF_SAFETY_FORECAST_FACTOR, 90)),
            max_battery_current_amps=float(data.get(CONF_MAX_BATTERY_CURRENT_AMPS, 36)),
            discharge_limit_percent=float(data.get(CONF_DISCHARGE_LIMIT_PERCENT, 80)),
            discharge_limit_deadband_percent=float(
                data.get(CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT, 5)
            ),
        )
        self.forecast_engine = ForecastEngine(
            latitude=float(data.get(CONF_LATITUDE, 32.08)),
            longitude=float(data.get(CONF_LONGITUDE, 34.78)),
            strings=data.get(CONF_STRINGS, []),
        )
        self.decision_engine = DecisionEngine(
            manual_override=bool(data.get("manual_override", False))
        )
        consumer_switches = data.get(CONF_CONSUMER_SWITCHES) or []
        if isinstance(consumer_switches, str):
            consumer_switches = [consumer_switches]
        lights = data.get(CONF_LIGHTS_TO_TURN_OFF) or []
        if isinstance(lights, str):
            lights = [lights]
        self.load_manager = LoadManager(
            hass,
            consumer_switches,
            lights,
            int(data.get(CONF_CONSUMER_DELAY, 5)),
        )
        self._entity_ids = {
            "battery_soc": data.get(CONF_BATTERY_SOC_SENSOR),
            "battery_power": data.get(CONF_BATTERY_POWER_SENSOR),
            "solar": data.get(CONF_SOLAR_PRODUCTION_SENSOR),
            "house": data.get(CONF_HOUSE_CONSUMPTION_SENSOR),
            "battery_current": data.get(CONF_BATTERY_CURRENT_SENSOR),
        }
        self._prev_discharge_state: str = ""
        self._last_decision: Any = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch sensors, forecast, update model, run decision, apply load manager."""
        try:
            # 1. Sensor values (power in W -> kW where needed)
            soc = _float_state(self.hass, self._entity_ids["battery_soc"] or "")
            battery_power_w = _float_state(self.hass, self._entity_ids["battery_power"] or "")
            solar_w = _float_state(self.hass, self._entity_ids["solar"] or "")
            house_w = _float_state(self.hass, self._entity_ids["house"] or "")
            battery_current = None
            if self._entity_ids.get("battery_current"):
                battery_current = _float_state(
                    self.hass, self._entity_ids["battery_current"]
                )

            self.model.battery_soc = soc
            self.model.battery_power_kw = battery_power_w / 1000.0
            self.model.solar_production_kw = solar_w / 1000.0
            self.model.house_consumption_kw = house_w / 1000.0
            self.model.battery_current = battery_current if battery_current != 0.0 else None

            # 2. Forecast
            forecast = await self.forecast_engine.fetch_and_compute(
                self.hass, datetime.now(timezone.utc)
            )
            self.model.forecast_next_hour_kwh = forecast.forecast_next_hour_kwh
            self.model.forecast_today_remaining_kwh = forecast.forecast_today_remaining_kwh
            self.model.hours_until_eod = _hours_until_sunset(self.hass)

            # 3. Derived
            self.model.update_derived()

            # 4. Decision engine (charge state duration: assume ~0.5 min per update)
            self.decision_engine.update_charge_state_duration(
                self.model.charge_state, UPDATE_INTERVAL / 60.0
            )
            decision = self.decision_engine.decide(self.model)
            self._last_decision = decision

            # 5. Load manager actions
            super_saving = self.model.battery_status == "very low"
            await self.load_manager.apply_mode(
                decision.system_mode,
                self.model.can_turn_on_heavy_consumer,
                super_saving=super_saving,
            )

            # 6. Discharge over limit: turn off one consumer when discharge_state -> max
            if (
                self.model.discharge_state == "max"
                and self._prev_discharge_state != "max"
            ):
                await self.load_manager.discharge_over_limit_turn_off_one(
                    self._config.get(CONF_CONSUMER_SWITCHES) or []
                )
            self._prev_discharge_state = self.model.discharge_state

            # 7. Expose for sensors
            return {
                "model": self.model,
                "forecast": forecast,
                "decision": decision,
                "battery_soc": soc,
                "battery_power_kw": self.model.battery_power_kw,
                "solar_production_kw": self.model.solar_production_kw,
                "house_consumption_kw": self.model.house_consumption_kw,
                "forecast_next_hour_kwh": forecast.forecast_next_hour_kwh,
                "forecast_today_remaining_kwh": forecast.forecast_today_remaining_kwh,
                "forecast_tomorrow_kwh": forecast.forecast_tomorrow_kwh,
                "forecast_current_power_kw": forecast.forecast_current_power_kw,
                "energy_manager_mode": decision.system_mode,
                "strategy_recommendation": decision.strategy_recommendation,
                "strategy_reason": decision.strategy_reason,
                "available_power_kw": self.model.solar_production_kw
                + self.model.battery_power_kw
                - self.model.house_consumption_kw,
                "forecast_remaining_kwh": forecast.forecast_today_remaining_kwh,
                "battery_reserve_state": self.model.battery_status,
                "daily_margin_kwh": self.model.daily_margin_kwh,
                "can_turn_on_heavy_consumer": self.model.can_turn_on_heavy_consumer,
            }
        except Exception as e:
            _LOGGER.exception("Error updating energy manager: %s", e)
            raise UpdateFailed(str(e)) from e

