"""
Central place for Home Assistant config flow schemas (integration UI settings).

Keys and numeric defaults remain in const.py; this module only builds voluptuous Schema
objects for the initial setup step and the options flow — single definition path for field sets.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import (
    CONF_AZIMUTH,
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
    CONF_FORECAST_PR,
    CONF_HOUSE_CONSUMPTION_SENSOR,
    CONF_INVERTER_SIZE_KW,
    CONF_LIGHTS_TO_TURN_OFF,
    CONF_RECOMMENDED_TO_TURN_OFF,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MAX_BATTERY_CURRENT_AMPS,
    CONF_MINIMUM_BATTERY_RESERVE,
    CONF_SAFETY_FORECAST_FACTOR,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_SYSTEM_SIZE_KW,
    CONF_TILT,
    DEFAULT_BASELINE_CONSUMPTION,
    DEFAULT_BATTERY_CAPACITY,
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
    DEFAULT_SYSTEM_SIZE_KW,
    DEFAULT_TILT,
    DEFAULT_AZIMUTH,
)


def sensor_selector() -> selector.Selector:
    return selector.EntitySelector(
        selector.EntityFilterSelectorConfig(domain=["sensor"])
    )


def battery_sensor_selector() -> selector.Selector:
    return selector.EntitySelector(
        selector.EntityFilterSelectorConfig(domain=["sensor"])
    )


def consumer_entity_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntityFilterSelectorConfig(
            domain=["switch", "input_boolean"], multiple=True
        ),
    )


def super_saving_entity_selector() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntityFilterSelectorConfig(
            domain=["light", "switch", "input_boolean", "fan"],
            multiple=True,
        ),
    )


def list_or_empty(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val] if val else []


def _home_lat_lon(hass: HomeAssistant) -> tuple[float, float]:
    try:
        return float(hass.config.latitude), float(hass.config.longitude)
    except (TypeError, ValueError):
        return DEFAULT_LATITUDE, DEFAULT_LONGITUDE


def main_params_schema_minimal(
    merged: dict[str, Any] | None = None,
) -> vol.Schema:
    """Step 1: battery/house/solar sensors and consumer switches only."""
    if merged is None:
        return vol.Schema(
            {
                vol.Required(CONF_BATTERY_SOC_SENSOR): battery_sensor_selector(),
                vol.Required(CONF_BATTERY_POWER_SENSOR): sensor_selector(),
                vol.Required(CONF_SOLAR_PRODUCTION_SENSOR): sensor_selector(),
                vol.Required(CONF_HOUSE_CONSUMPTION_SENSOR): sensor_selector(),
                vol.Required(CONF_CONSUMER_SWITCHES): consumer_entity_selector(),
            }
        )
    return vol.Schema(
        {
            vol.Required(
                CONF_BATTERY_SOC_SENSOR,
                default=merged.get(CONF_BATTERY_SOC_SENSOR) or "",
            ): battery_sensor_selector(),
            vol.Required(
                CONF_BATTERY_POWER_SENSOR,
                default=merged.get(CONF_BATTERY_POWER_SENSOR) or "",
            ): sensor_selector(),
            vol.Required(
                CONF_SOLAR_PRODUCTION_SENSOR,
                default=merged.get(CONF_SOLAR_PRODUCTION_SENSOR) or "",
            ): sensor_selector(),
            vol.Required(
                CONF_HOUSE_CONSUMPTION_SENSOR,
                default=merged.get(CONF_HOUSE_CONSUMPTION_SENSOR) or "",
            ): sensor_selector(),
            vol.Required(
                CONF_CONSUMER_SWITCHES,
                default=list_or_empty(merged.get(CONF_CONSUMER_SWITCHES)),
            ): consumer_entity_selector(),
        }
    )


def main_params_schema_advanced(base: dict[str, Any]) -> vol.Schema:
    """Step 2: numeric params and optional entities. Lat/lon are set in the flow."""
    return vol.Schema(
        {
            vol.Required(
                CONF_BATTERY_CAPACITY,
                default=base.get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY),
            ): vol.Coerce(float),
            vol.Required(
                CONF_BASELINE_CONSUMPTION,
                default=base.get(CONF_BASELINE_CONSUMPTION, DEFAULT_BASELINE_CONSUMPTION),
            ): vol.Coerce(float),
            vol.Required(
                CONF_MINIMUM_BATTERY_RESERVE,
                default=base.get(
                    CONF_MINIMUM_BATTERY_RESERVE, DEFAULT_MINIMUM_BATTERY_RESERVE
                ),
            ): vol.Coerce(int),
            vol.Required(
                CONF_SAFETY_FORECAST_FACTOR,
                default=base.get(
                    CONF_SAFETY_FORECAST_FACTOR, DEFAULT_SAFETY_FORECAST_FACTOR
                ),
            ): vol.Coerce(int),
            vol.Required(
                CONF_CONSUMER_DELAY,
                default=base.get(CONF_CONSUMER_DELAY, DEFAULT_CONSUMER_DELAY),
            ): vol.Coerce(int),
            vol.Required(
                CONF_FORECAST_PR,
                default=base.get(CONF_FORECAST_PR, DEFAULT_FORECAST_PR),
            ): vol.Coerce(float),
            vol.Required(
                CONF_EOD_BATTERY_TARGET,
                default=base.get(CONF_EOD_BATTERY_TARGET, DEFAULT_EOD_BATTERY_TARGET),
            ): vol.Coerce(int),
            vol.Required(
                CONF_MAX_BATTERY_CURRENT_AMPS,
                default=base.get(
                    CONF_MAX_BATTERY_CURRENT_AMPS, DEFAULT_MAX_BATTERY_CURRENT_AMPS
                ),
            ): vol.Coerce(int),
            vol.Required(
                CONF_DISCHARGE_LIMIT_PERCENT,
                default=base.get(
                    CONF_DISCHARGE_LIMIT_PERCENT, DEFAULT_DISCHARGE_LIMIT_PERCENT
                ),
            ): vol.Coerce(int),
            vol.Required(
                CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT,
                default=base.get(
                    CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT,
                    DEFAULT_DISCHARGE_LIMIT_DEADBAND_PERCENT,
                ),
            ): vol.Coerce(int),
            vol.Optional(
                CONF_INVERTER_SIZE_KW,
                default=base.get(CONF_INVERTER_SIZE_KW, DEFAULT_INVERTER_SIZE_KW),
            ): vol.Coerce(float),
            vol.Optional(
                CONF_BATTERY_CURRENT_SENSOR,
                default=base.get(CONF_BATTERY_CURRENT_SENSOR) or "",
            ): sensor_selector(),
            vol.Optional(
                CONF_LIGHTS_TO_TURN_OFF,
                default=list_or_empty(base.get(CONF_LIGHTS_TO_TURN_OFF)),
            ): super_saving_entity_selector(),
            vol.Optional(
                CONF_RECOMMENDED_TO_TURN_OFF,
                default=list_or_empty(base.get(CONF_RECOMMENDED_TO_TURN_OFF)),
            ): super_saving_entity_selector(),
        }
    )


def strings_schema_install_defaults() -> vol.Schema:
    """PV strings step after advanced params (defaults only)."""
    return vol.Schema(
        {
            vol.Required(
                "string_0_system_size_kw", default=DEFAULT_SYSTEM_SIZE_KW
            ): vol.Coerce(float),
            vol.Required("string_0_tilt", default=DEFAULT_TILT): vol.Coerce(float),
            vol.Required("string_0_azimuth", default=DEFAULT_AZIMUTH): vol.Coerce(float),
            vol.Required(
                "string_1_system_size_kw", default=DEFAULT_SYSTEM_SIZE_KW
            ): vol.Coerce(float),
            vol.Required("string_1_tilt", default=DEFAULT_TILT): vol.Coerce(float),
            vol.Required("string_1_azimuth", default=DEFAULT_AZIMUTH): vol.Coerce(float),
        }
    )


def strings_schema_from_config(strings: list[dict[str, Any]]) -> vol.Schema:
    """PV strings options step: defaults from existing CONF_STRINGS."""
    s0 = strings[0] if len(strings) > 0 else {}
    s1 = strings[1] if len(strings) > 1 else {}
    return vol.Schema(
        {
            vol.Required(
                "string_0_system_size_kw",
                default=float(s0.get(CONF_SYSTEM_SIZE_KW, DEFAULT_SYSTEM_SIZE_KW)),
            ): vol.Coerce(float),
            vol.Required(
                "string_0_tilt",
                default=float(s0.get(CONF_TILT, DEFAULT_TILT)),
            ): vol.Coerce(float),
            vol.Required(
                "string_0_azimuth",
                default=float(s0.get(CONF_AZIMUTH, DEFAULT_AZIMUTH)),
            ): vol.Coerce(float),
            vol.Required(
                "string_1_system_size_kw",
                default=float(s1.get(CONF_SYSTEM_SIZE_KW, DEFAULT_SYSTEM_SIZE_KW)),
            ): vol.Coerce(float),
            vol.Required(
                "string_1_tilt",
                default=float(s1.get(CONF_TILT, DEFAULT_TILT)),
            ): vol.Coerce(float),
            vol.Required(
                "string_1_azimuth",
                default=float(s1.get(CONF_AZIMUTH, DEFAULT_AZIMUTH)),
            ): vol.Coerce(float),
        }
    )
