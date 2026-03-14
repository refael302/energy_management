"""Config flow for Energy Manager integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
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
    CONF_HOUSE_CONSUMPTION_SENSOR,
    CONF_LIGHTS_TO_TURN_OFF,
    CONF_RECOMMENDED_TO_TURN_OFF,
    CONF_MAX_BATTERY_CURRENT_AMPS,
    CONF_MINIMUM_BATTERY_RESERVE,
    CONF_SAFETY_FORECAST_FACTOR,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_STRINGS,
    CONF_SYSTEM_SIZE_KW,
    CONF_TILT,
    DEFAULT_BASELINE_CONSUMPTION,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_CONSUMER_DELAY,
    DEFAULT_DISCHARGE_LIMIT_DEADBAND_PERCENT,
    DEFAULT_DISCHARGE_LIMIT_PERCENT,
    DEFAULT_EOD_BATTERY_TARGET,
    DEFAULT_MAX_BATTERY_CURRENT_AMPS,
    DEFAULT_MINIMUM_BATTERY_RESERVE,
    DEFAULT_SAFETY_FORECAST_FACTOR,
    DOMAIN,
    MAX_STRINGS,
)

_LOGGER = logging.getLogger(__name__)


def _sensor_selector() -> selector.Selector:
    return selector.EntitySelector(
        selector.EntityFilterSelectorConfig(domain=["sensor"])
    )


def _power_sensor_selector() -> selector.Selector:
    return selector.EntitySelector(
        selector.EntityFilterSelectorConfig(domain=["sensor"])
    )


def _battery_sensor_selector() -> selector.Selector:
    return selector.EntitySelector(
        selector.EntityFilterSelectorConfig(domain=["sensor"])
    )


def _data_schema_user(hass: HomeAssistant) -> vol.Schema:
    """Build user step schema with defaults from HA config (e.g. home location)."""
    try:
        lat = float(hass.config.latitude)
        lon = float(hass.config.longitude)
    except (TypeError, ValueError):
        lat, lon = 32.08, 34.78
    return vol.Schema(
        {
            vol.Required(CONF_BATTERY_SOC_SENSOR): _battery_sensor_selector(),
            vol.Required(CONF_BATTERY_POWER_SENSOR): _power_sensor_selector(),
            vol.Required(CONF_SOLAR_PRODUCTION_SENSOR): _power_sensor_selector(),
            vol.Required(CONF_HOUSE_CONSUMPTION_SENSOR): _power_sensor_selector(),
            vol.Required(CONF_CONSUMER_SWITCHES): selector.EntitySelector(
                selector.EntityFilterSelectorConfig(
                    domain=["switch", "input_boolean"], multiple=True
                ),
            ),
            vol.Required(CONF_LATITUDE, default=lat): vol.Coerce(float),
            vol.Required(CONF_LONGITUDE, default=lon): vol.Coerce(float),
            vol.Required(CONF_BATTERY_CAPACITY, default=20.0): vol.Coerce(float),
            vol.Required(CONF_BASELINE_CONSUMPTION, default=0.8): vol.Coerce(float),
            vol.Required(CONF_MINIMUM_BATTERY_RESERVE, default=20): vol.Coerce(int),
            vol.Required(CONF_SAFETY_FORECAST_FACTOR, default=90): vol.Coerce(int),
            vol.Required(CONF_CONSUMER_DELAY, default=5): vol.Coerce(int),
            vol.Required(CONF_EOD_BATTERY_TARGET, default=90): vol.Coerce(int),
            vol.Required(CONF_MAX_BATTERY_CURRENT_AMPS, default=36): vol.Coerce(int),
            vol.Required(CONF_DISCHARGE_LIMIT_PERCENT, default=80): vol.Coerce(int),
            vol.Required(
                CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT, default=5
            ): vol.Coerce(int),
            vol.Optional(CONF_BATTERY_CURRENT_SENSOR): _sensor_selector(),
            vol.Optional(CONF_LIGHTS_TO_TURN_OFF): selector.EntitySelector(
                selector.EntityFilterSelectorConfig(
                    domain=["light", "switch", "input_boolean", "fan"],
                    multiple=True,
                ),
            ),
            vol.Optional(CONF_RECOMMENDED_TO_TURN_OFF): selector.EntitySelector(
                selector.EntityFilterSelectorConfig(
                    domain=["light", "switch", "input_boolean", "fan"],
                    multiple=True,
                ),
            ),
        }
    )


def _strings_data_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("string_0_system_size_kw", default=5.0): vol.Coerce(float),
            vol.Required("string_0_tilt", default=30): vol.Coerce(float),
            vol.Required("string_0_azimuth", default=0): vol.Coerce(float),
            vol.Required("string_1_system_size_kw", default=5.0): vol.Coerce(float),
            vol.Required("string_1_tilt", default=30): vol.Coerce(float),
            vol.Required("string_1_azimuth", default=0): vol.Coerce(float),
        }
    )


class EnergyManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Manager."""

    VERSION = 1

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(*args, **kwargs)
        self._user_input: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step (sensors and parameters)."""
        if user_input is not None:
            battery_current = user_input.pop(CONF_BATTERY_CURRENT_SENSOR, None)
            lights = user_input.pop(CONF_LIGHTS_TO_TURN_OFF, None) or []
            recommended = user_input.pop(CONF_RECOMMENDED_TO_TURN_OFF, None) or []
            if battery_current:
                user_input[CONF_BATTERY_CURRENT_SENSOR] = battery_current
            user_input[CONF_LIGHTS_TO_TURN_OFF] = lights
            user_input[CONF_RECOMMENDED_TO_TURN_OFF] = recommended
            self._user_input = user_input
            return await self.async_step_strings()
        return self.async_show_form(
            step_id="user",
            data_schema=_data_schema_user(self.hass),
        )

    async def async_step_strings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure PV strings (2 strings: system_size_kw, tilt, azimuth)."""
        if user_input is not None and self._user_input is not None:
            strings = [
                {
                    CONF_SYSTEM_SIZE_KW: user_input["string_0_system_size_kw"],
                    CONF_TILT: user_input["string_0_tilt"],
                    CONF_AZIMUTH: user_input["string_0_azimuth"],
                },
                {
                    CONF_SYSTEM_SIZE_KW: user_input["string_1_system_size_kw"],
                    CONF_TILT: user_input["string_1_tilt"],
                    CONF_AZIMUTH: user_input["string_1_azimuth"],
                },
            ]
            data = {**self._user_input, CONF_STRINGS: strings}
            return self.async_create_entry(title="Energy Manager", data=data)
        return self.async_show_form(
            step_id="strings", data_schema=_strings_data_schema()
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return EnergyManagerOptionsFlow(config_entry)


def _options_schema_main(hass: HomeAssistant, merged: dict[str, Any]) -> vol.Schema:
    """Build options form schema for main params (sensors, devices, numbers)."""
    def _list_or_empty(val: Any) -> list[str]:
        if val is None:
            return []
        if isinstance(val, list):
            return val
        return [val] if val else []

    return vol.Schema(
        {
            vol.Required(
                CONF_BATTERY_SOC_SENSOR,
                default=merged.get(CONF_BATTERY_SOC_SENSOR) or "",
            ): _battery_sensor_selector(),
            vol.Required(
                CONF_BATTERY_POWER_SENSOR,
                default=merged.get(CONF_BATTERY_POWER_SENSOR) or "",
            ): _power_sensor_selector(),
            vol.Required(
                CONF_SOLAR_PRODUCTION_SENSOR,
                default=merged.get(CONF_SOLAR_PRODUCTION_SENSOR) or "",
            ): _power_sensor_selector(),
            vol.Required(
                CONF_HOUSE_CONSUMPTION_SENSOR,
                default=merged.get(CONF_HOUSE_CONSUMPTION_SENSOR) or "",
            ): _power_sensor_selector(),
            vol.Required(
                CONF_CONSUMER_SWITCHES,
                default=_list_or_empty(merged.get(CONF_CONSUMER_SWITCHES)),
            ): selector.EntitySelector(
                selector.EntityFilterSelectorConfig(
                    domain=["switch", "input_boolean"], multiple=True
                ),
            ),
            vol.Required(
                CONF_LATITUDE,
                default=merged.get(CONF_LATITUDE, hass.config.latitude),
            ): vol.Coerce(float),
            vol.Required(
                CONF_LONGITUDE,
                default=merged.get(CONF_LONGITUDE, hass.config.longitude),
            ): vol.Coerce(float),
            vol.Required(
                CONF_BATTERY_CAPACITY,
                default=merged.get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY),
            ): vol.Coerce(float),
            vol.Required(
                CONF_BASELINE_CONSUMPTION,
                default=merged.get(CONF_BASELINE_CONSUMPTION, DEFAULT_BASELINE_CONSUMPTION),
            ): vol.Coerce(float),
            vol.Required(
                CONF_MINIMUM_BATTERY_RESERVE,
                default=merged.get(CONF_MINIMUM_BATTERY_RESERVE, DEFAULT_MINIMUM_BATTERY_RESERVE),
            ): vol.Coerce(int),
            vol.Required(
                CONF_SAFETY_FORECAST_FACTOR,
                default=merged.get(CONF_SAFETY_FORECAST_FACTOR, DEFAULT_SAFETY_FORECAST_FACTOR),
            ): vol.Coerce(int),
            vol.Required(
                CONF_CONSUMER_DELAY,
                default=merged.get(CONF_CONSUMER_DELAY, DEFAULT_CONSUMER_DELAY),
            ): vol.Coerce(int),
            vol.Required(
                CONF_EOD_BATTERY_TARGET,
                default=merged.get(CONF_EOD_BATTERY_TARGET, DEFAULT_EOD_BATTERY_TARGET),
            ): vol.Coerce(int),
            vol.Required(
                CONF_MAX_BATTERY_CURRENT_AMPS,
                default=merged.get(CONF_MAX_BATTERY_CURRENT_AMPS, DEFAULT_MAX_BATTERY_CURRENT_AMPS),
            ): vol.Coerce(int),
            vol.Required(
                CONF_DISCHARGE_LIMIT_PERCENT,
                default=merged.get(CONF_DISCHARGE_LIMIT_PERCENT, DEFAULT_DISCHARGE_LIMIT_PERCENT),
            ): vol.Coerce(int),
            vol.Required(
                CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT,
                default=merged.get(
                    CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT,
                    DEFAULT_DISCHARGE_LIMIT_DEADBAND_PERCENT,
                ),
            ): vol.Coerce(int),
            vol.Optional(
                CONF_BATTERY_CURRENT_SENSOR,
                default=merged.get(CONF_BATTERY_CURRENT_SENSOR) or "",
            ): _sensor_selector(),
            vol.Optional(
                CONF_LIGHTS_TO_TURN_OFF,
                default=_list_or_empty(merged.get(CONF_LIGHTS_TO_TURN_OFF)),
            ): selector.EntitySelector(
                selector.EntityFilterSelectorConfig(
                    domain=["light", "switch", "input_boolean", "fan"],
                    multiple=True,
                ),
            ),
            vol.Optional(
                CONF_RECOMMENDED_TO_TURN_OFF,
                default=_list_or_empty(merged.get(CONF_RECOMMENDED_TO_TURN_OFF)),
            ): selector.EntitySelector(
                selector.EntityFilterSelectorConfig(
                    domain=["light", "switch", "input_boolean", "fan"],
                    multiple=True,
                ),
            ),
        }
    )


class EnergyManagerOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Handle Energy Manager options (all configurable params)."""

    def _merged_config(self) -> dict[str, Any]:
        """Current config = data + options."""
        return {
            **self.config_entry.data,
            **(self.config_entry.options or {}),
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: main params (sensors, devices, numbers)."""
        if user_input is not None:
            battery_current = user_input.pop(CONF_BATTERY_CURRENT_SENSOR, None) or None
            lights = user_input.get(CONF_LIGHTS_TO_TURN_OFF) or []
            recommended = user_input.get(CONF_RECOMMENDED_TO_TURN_OFF) or []
            user_input[CONF_BATTERY_CURRENT_SENSOR] = battery_current
            user_input[CONF_LIGHTS_TO_TURN_OFF] = lights
            user_input[CONF_RECOMMENDED_TO_TURN_OFF] = recommended
            self._options = user_input
            return await self.async_step_strings()
        merged = self._merged_config()
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema_main(self.hass, merged),
        )

    async def async_step_strings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: PV strings."""
        if user_input is not None and hasattr(self, "_options"):
            strings = [
                {
                    CONF_SYSTEM_SIZE_KW: user_input["string_0_system_size_kw"],
                    CONF_TILT: user_input["string_0_tilt"],
                    CONF_AZIMUTH: user_input["string_0_azimuth"],
                },
                {
                    CONF_SYSTEM_SIZE_KW: user_input["string_1_system_size_kw"],
                    CONF_TILT: user_input["string_1_tilt"],
                    CONF_AZIMUTH: user_input["string_1_azimuth"],
                },
            ]
            data = {**self._options, CONF_STRINGS: strings}
            return self.async_create_entry(data=data)
        merged = self._merged_config()
        strings = merged.get(CONF_STRINGS, [
            {"system_size_kw": 5.0, "tilt": 30, "azimuth": 0},
            {"system_size_kw": 5.0, "tilt": 30, "azimuth": 0},
        ])
        schema = vol.Schema(
            {
                vol.Required(
                    "string_0_system_size_kw",
                    default=strings[0].get(CONF_SYSTEM_SIZE_KW, 5.0),
                ): vol.Coerce(float),
                vol.Required(
                    "string_0_tilt",
                    default=strings[0].get(CONF_TILT, 30),
                ): vol.Coerce(float),
                vol.Required(
                    "string_0_azimuth",
                    default=strings[0].get(CONF_AZIMUTH, 0),
                ): vol.Coerce(float),
                vol.Required(
                    "string_1_system_size_kw",
                    default=strings[1].get(CONF_SYSTEM_SIZE_KW, 5.0),
                ): vol.Coerce(float),
                vol.Required(
                    "string_1_tilt",
                    default=strings[1].get(CONF_TILT, 30),
                ): vol.Coerce(float),
                vol.Required(
                    "string_1_azimuth",
                    default=strings[1].get(CONF_AZIMUTH, 0),
                ): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="strings", data_schema=schema)
