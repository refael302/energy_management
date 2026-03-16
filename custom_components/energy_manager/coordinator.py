"""
Data coordinator – polls sensors and forecast every 30s, runs decision engine and load manager.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BATTERY_RUNTIME_MIN_SOC_PERCENT,
    CONF_BASELINE_CONSUMPTION,
    STRATEGY_MEDIUM,
    SYSTEM_MODE_NORMAL,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CURRENT_SENSOR,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_CONSUMER_DELAY,
    CONF_CONSUMER_SWITCHES,
    CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT,
    CONF_DISCHARGE_LIMIT_PERCENT,
    CONF_EOD_BATTERY_TARGET,
    CONF_FORECAST_PR,
    CONF_HOUSE_CONSUMPTION_SENSOR,
    CONF_INVERTER_SIZE_KW,
    CONF_LATITUDE,
    CONF_LIGHTS_TO_TURN_OFF,
    CONF_MANUAL_MODE,
    CONF_MANUAL_MODE_OVERRIDE,
    CONF_MANUAL_OVERRIDE,
    CONF_MANUAL_STRATEGY,
    CONF_MANUAL_STRATEGY_OVERRIDE,
    CONF_RECOMMENDED_TO_TURN_OFF,
    CONF_LONGITUDE,
    CONF_MAX_BATTERY_CURRENT_AMPS,
    CONF_MINIMUM_BATTERY_RESERVE,
    CONF_SAFETY_FORECAST_FACTOR,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_STRINGS,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BASELINE_CONSUMPTION,
    DEFAULT_CONSUMER_DELAY,
    DEFAULT_DISCHARGE_LIMIT_DEADBAND_PERCENT,
    DEFAULT_DISCHARGE_LIMIT_PERCENT,
    DEFAULT_EOD_BATTERY_TARGET,
    DEFAULT_FORECAST_PR,
    DEFAULT_INVERTER_SIZE_KW,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_MAX_BATTERY_CURRENT_AMPS,
    DEFAULT_MINIMUM_BATTERY_RESERVE,
    DEFAULT_SAFETY_FORECAST_FACTOR,
    DOMAIN,
    FORECAST_STRATEGY_CACHE_MINUTES,
    UPDATE_INTERVAL,
)
from .engine import DecisionEngine, EnergyModel, ForecastEngine, LoadManager
from .engine.decision_engine import recommend_battery_strategy

_LOGGER = logging.getLogger(__name__)


def _float_state(hass: HomeAssistant, entity_id: str) -> float:
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        return 0.0
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return 0.0


def _normalize_consumer_entity_ids(raw: Any) -> list[str]:
    """Normalize consumer list from config (support list of strings or list of dicts with entity_id)."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            eid = item.get("entity_id") or item.get("id")
            if isinstance(eid, str):
                out.append(eid)
    return out


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
    except Exception as e:
        _LOGGER.debug("sun sunset: %s", e)
        return 0.0


def _hours_until_sunrise(hass: HomeAssistant) -> float:
    sun = hass.states.get("sun.sun")
    if sun is None:
        return 0.0
    next_rise = sun.attributes.get("next_rising")
    if next_rise is None:
        return 0.0
    try:
        from homeassistant.util import dt as dt_util
        rise_ts = dt_util.as_timestamp(next_rise)
        now_ts = datetime.now(timezone.utc).timestamp()
        return max(0.0, round((rise_ts - now_ts) / 3600, 2))
    except Exception as e:
        _LOGGER.debug("sun sunrise: %s", e)
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
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.model = EnergyModel(
            battery_capacity_kwh=float(data.get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY)),
            baseline_consumption_kw=float(data.get(CONF_BASELINE_CONSUMPTION, DEFAULT_BASELINE_CONSUMPTION)),
            eod_battery_target_percent=float(data.get(CONF_EOD_BATTERY_TARGET, DEFAULT_EOD_BATTERY_TARGET)),
            emergency_reserve_percent=float(data.get(CONF_MINIMUM_BATTERY_RESERVE, DEFAULT_MINIMUM_BATTERY_RESERVE)),
            safety_forecast_factor_percent=float(data.get(CONF_SAFETY_FORECAST_FACTOR, DEFAULT_SAFETY_FORECAST_FACTOR)),
            max_battery_current_amps=float(data.get(CONF_MAX_BATTERY_CURRENT_AMPS, DEFAULT_MAX_BATTERY_CURRENT_AMPS)),
            discharge_limit_percent=float(data.get(CONF_DISCHARGE_LIMIT_PERCENT, DEFAULT_DISCHARGE_LIMIT_PERCENT)),
            discharge_limit_deadband_percent=float(
                data.get(CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT, DEFAULT_DISCHARGE_LIMIT_DEADBAND_PERCENT)
            ),
        )
        self.forecast_engine = ForecastEngine(
            latitude=float(data.get(CONF_LATITUDE, DEFAULT_LATITUDE)),
            longitude=float(data.get(CONF_LONGITUDE, DEFAULT_LONGITUDE)),
            strings=data.get(CONF_STRINGS, []),
            pr_factor=float(data.get(CONF_FORECAST_PR, DEFAULT_FORECAST_PR)),
        )
        self.decision_engine = DecisionEngine()
        consumer_switches = data.get(CONF_CONSUMER_SWITCHES) or []
        if isinstance(consumer_switches, str):
            consumer_switches = [consumer_switches]
        lights = data.get(CONF_LIGHTS_TO_TURN_OFF) or []
        if isinstance(lights, str):
            lights = [lights]
        self._recommended_to_turn_off_entity_ids = (
            data.get(CONF_RECOMMENDED_TO_TURN_OFF) or []
        )
        if isinstance(self._recommended_to_turn_off_entity_ids, str):
            self._recommended_to_turn_off_entity_ids = [
                self._recommended_to_turn_off_entity_ids
            ]
        self.load_manager = LoadManager(
            hass,
            consumer_switches,
            lights,
            int(data.get(CONF_CONSUMER_DELAY, DEFAULT_CONSUMER_DELAY)),
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
        self._last_forecast: Any = None
        self._last_forecast_time: datetime | None = None
        self._last_strategy: str | None = None
        self._last_strategy_reason: str = ""
        self._last_strategy_time: datetime | None = None

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
            current_config = {**self.entry.data, **(self.entry.options or {})}

            # 2. Forecast (cached every FORECAST_STRATEGY_CACHE_MINUTES)
            now_utc = datetime.now(timezone.utc)
            cache_min = timedelta(minutes=FORECAST_STRATEGY_CACHE_MINUTES)
            inverter_size_kw = float(
                current_config.get(CONF_INVERTER_SIZE_KW, DEFAULT_INVERTER_SIZE_KW) or 0
            )
            if (
                self._last_forecast is None
                or self._last_forecast_time is None
                or (now_utc - self._last_forecast_time) >= cache_min
            ):
                forecast = await self.forecast_engine.fetch_and_compute(
                    self.hass, now_utc, inverter_size_kw=inverter_size_kw
                )
                self._last_forecast = forecast
                self._last_forecast_time = now_utc
            else:
                forecast = self._last_forecast
            forecast_available = getattr(forecast, "available", True)
            self.model.forecast_available = forecast_available
            if forecast_available:
                self.model.forecast_next_hour_kwh = forecast.forecast_next_hour_kwh
                self.model.forecast_today_remaining_kwh = forecast.forecast_today_remaining_kwh
            else:
                self.model.forecast_next_hour_kwh = 0.0
                self.model.forecast_today_remaining_kwh = 0.0
            self.model.hours_until_eod = _hours_until_sunset(self.hass)

            # 3. Derived
            self.model.update_derived()

            # 4. Decision engine (charge state duration: assume ~0.5 min per update)
            self.decision_engine.update_charge_state_duration(
                self.model.charge_state, UPDATE_INTERVAL / 60.0
            )
            manual_mode_override = bool(current_config.get(CONF_MANUAL_MODE_OVERRIDE, current_config.get(CONF_MANUAL_OVERRIDE, False)))
            manual_strategy_override = bool(current_config.get(CONF_MANUAL_STRATEGY_OVERRIDE, current_config.get(CONF_MANUAL_OVERRIDE, False)))
            manual_mode = current_config.get(CONF_MANUAL_MODE) or SYSTEM_MODE_NORMAL
            manual_strategy = current_config.get(CONF_MANUAL_STRATEGY) or STRATEGY_MEDIUM
            if (
                self._last_strategy_time is None
                or (now_utc - self._last_strategy_time) >= cache_min
            ):
                self._last_strategy, self._last_strategy_reason = recommend_battery_strategy(
                    self.model
                )
                self._last_strategy_time = now_utc
            cached_strategy = (
                (self._last_strategy, self._last_strategy_reason)
                if self._last_strategy is not None
                else None
            )
            decision = self.decision_engine.decide(
                self.model,
                manual_mode_override=manual_mode_override,
                manual_strategy_override=manual_strategy_override,
                manual_mode=manual_mode,
                manual_strategy=manual_strategy,
                cached_strategy=cached_strategy,
            )
            self._last_decision = decision

            # 5. Load manager actions (act only on mode; no extra input gates)
            super_saving = self.model.battery_status == "very low"
            await self.load_manager.apply_mode(
                decision.system_mode,
                super_saving=super_saving,
            )

            # 6. Discharge over limit: turn off one consumer when discharge_state -> max
            if (
                self.model.discharge_state == "max"
                and self._prev_discharge_state != "max"
            ):
                consumer_list = _normalize_consumer_entity_ids(
                    current_config.get(CONF_CONSUMER_SWITCHES)
                )
                await self.load_manager.discharge_over_limit_turn_off_one(
                    consumer_list
                )
            self._prev_discharge_state = self.model.discharge_state

            # Recommendation: turn off intermediate devices when battery low and forecast short
            recommended_entity_ids: list[str] = []
            if (
                self._recommended_to_turn_off_entity_ids
                and self.model.battery_status in ("low", "very low")
                and (not self.model.forecast_available or self.model.daily_margin_kwh < 0)
            ):
                recommended_entity_ids = list(self._recommended_to_turn_off_entity_ids)

            # Count consumers (use current config; normalize list for EntitySelector dict format)
            consumer_entity_ids = _normalize_consumer_entity_ids(
                current_config.get(CONF_CONSUMER_SWITCHES)
            )
            consumers_on_count = 0
            for eid in consumer_entity_ids:
                state = self.hass.states.get(eid)
                if state and state.state == "on":
                    consumers_on_count += 1
            consumers_total = len(consumer_entity_ids)

            # 7. Expose for sensors (forecast already capped by inverter in fetch_and_compute)
            if forecast_available:
                f_next = forecast.forecast_next_hour_kwh
                f_today = forecast.forecast_today_remaining_kwh
                f_tomorrow = forecast.forecast_tomorrow_kwh
                f_tomorrow_hourly = getattr(
                    forecast, "forecast_tomorrow_hourly_kw", []
                )
                f_current = getattr(forecast, "forecast_current_power_kw", None) or 0.0
                daily_margin = self.model.daily_margin_kwh
                pv_safe = self.model.pv_remaining_today_safe_kwh
            else:
                f_next = f_today = f_tomorrow = f_current = daily_margin = pv_safe = None
                f_tomorrow_hourly = []

            hours_until_sunrise = _hours_until_sunrise(self.hass)
            usable_kwh = max(
                0.0,
                (soc - BATTERY_RUNTIME_MIN_SOC_PERCENT) / 100.0
                * self.model.battery_capacity_kwh,
            )
            house_kw = self.model.house_consumption_kw
            if house_kw is None or house_kw <= 0:
                battery_runtime_hhmm = "99:59"
            else:
                runtime_hours = usable_kwh / house_kw
                h = min(99, int(runtime_hours))
                m = int((runtime_hours % 1) * 60)
                battery_runtime_hhmm = f"{h:02d}:{m:02d}"

            _LOGGER.debug(
                "update ok: mode=%s strategy=%s",
                decision.system_mode,
                decision.strategy_recommendation,
            )
            return {
                "model": self.model,
                "forecast": forecast,
                "decision": decision,
                "forecast_available": forecast_available,
                "battery_soc": soc,
                "battery_power_kw": self.model.battery_power_kw,
                "solar_production_kw": self.model.solar_production_kw,
                "house_consumption_kw": self.model.house_consumption_kw,
                "forecast_next_hour_kwh": f_next,
                "forecast_today_remaining_kwh": f_today,
                "forecast_tomorrow_kwh": f_tomorrow,
                "forecast_tomorrow_hourly_kw": f_tomorrow_hourly,
                "forecast_current_power_kw": f_current,
                "energy_manager_mode": decision.system_mode,
                "strategy_recommendation": decision.strategy_recommendation,
                "strategy_reason": decision.strategy_reason,
                "mode_reason": decision.mode_reason,
                "forecast_remaining_kwh": f_today,
                "battery_reserve_state": self.model.battery_status,
                "daily_margin_kwh": daily_margin,
                "recommended_to_turn_off_entity_ids": recommended_entity_ids,
                "charge_state": self.model.charge_state,
                "discharge_state": self.model.discharge_state,
                "needed_energy_today_kwh": self.model.needed_energy_today_kwh,
                "pv_remaining_today_safe_kwh": pv_safe,
                "hours_until_eod": self.model.hours_until_eod,
                "hours_until_sunrise": hours_until_sunrise,
                "battery_runtime_hhmm": battery_runtime_hhmm,
                "consumers_on_count": consumers_on_count,
                "consumers_total": consumers_total,
            }
        except Exception as e:
            _LOGGER.exception("Error updating energy manager: %s", e)
            raise UpdateFailed(str(e)) from e

