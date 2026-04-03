"""Config flow for Energy Manager integration."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .config_schema import (
    _home_lat_lon,
    main_params_schema_advanced,
    main_params_schema_minimal,
    strings_schema_from_config,
    strings_schema_install_defaults,
)
from .const import (
    CONF_AZIMUTH,
    CONF_BATTERY_CURRENT_SENSOR,
    CONF_LATITUDE,
    CONF_LIGHTS_TO_TURN_OFF,
    CONF_LONGITUDE,
    CONF_RECOMMENDED_TO_TURN_OFF,
    CONF_STRINGS,
    CONF_SYSTEM_SIZE_KW,
    CONF_TILT,
    DEFAULT_AZIMUTH,
    DEFAULT_SYSTEM_SIZE_KW,
    DEFAULT_TILT,
    DOMAIN,
)


def _apply_advanced_optional_entities(user_input: dict[str, Any]) -> None:
    """Normalize optional entity fields from an advanced-step form submission."""
    battery_current = user_input.pop(CONF_BATTERY_CURRENT_SENSOR, None)
    lights = user_input.pop(CONF_LIGHTS_TO_TURN_OFF, None) or []
    recommended = user_input.pop(CONF_RECOMMENDED_TO_TURN_OFF, None) or []
    if battery_current:
        user_input[CONF_BATTERY_CURRENT_SENSOR] = battery_current
    user_input[CONF_LIGHTS_TO_TURN_OFF] = lights
    user_input[CONF_RECOMMENDED_TO_TURN_OFF] = recommended


def _latitude_longitude_for_new_entry(hass: HomeAssistant) -> tuple[float, float]:
    """Use HA home location for solar forecast (same as former user-step defaults)."""
    return _home_lat_lon(hass)


def _latitude_longitude_preserve_or_home(
    hass: HomeAssistant, merged: dict[str, Any]
) -> tuple[float, float]:
    home_lat, home_lon = _home_lat_lon(hass)
    try:
        lat = float(merged.get(CONF_LATITUDE, home_lat))
    except (TypeError, ValueError):
        lat = home_lat
    try:
        lon = float(merged.get(CONF_LONGITUDE, home_lon))
    except (TypeError, ValueError):
        lon = home_lon
    return lat, lon


class EnergyManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Manager."""

    VERSION = 4

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(*args, **kwargs)
        self._user_input: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: required sensors and consumer switches."""
        if user_input is not None:
            self._user_input = dict(user_input)
            return await self.async_step_advanced()
        return self.async_show_form(
            step_id="user",
            data_schema=main_params_schema_minimal(),
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: numeric parameters and optional entities; inject lat/lon from HA."""
        if self._user_input is None:
            return await self.async_step_user()
        if user_input is not None:
            user_input = dict(user_input)
            _apply_advanced_optional_entities(user_input)
            lat, lon = _latitude_longitude_for_new_entry(self.hass)
            self._user_input = {**self._user_input, **user_input, CONF_LATITUDE: lat, CONF_LONGITUDE: lon}
            return await self.async_step_strings()
        base = dict(self._user_input)
        return self.async_show_form(
            step_id="advanced",
            data_schema=main_params_schema_advanced(base),
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
            step_id="strings", data_schema=strings_schema_install_defaults()
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return EnergyManagerOptionsFlow(config_entry)


class EnergyManagerOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Handle Energy Manager options (minimal → advanced → PV strings)."""

    def _merged_config(self) -> dict[str, Any]:
        """Current config = data + options."""
        return {
            **self.config_entry.data,
            **(self.config_entry.options or {}),
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: sensors and consumer switches."""
        if user_input is not None:
            self._options_partial = dict(user_input)
            return await self.async_step_advanced()
        merged = self._merged_config()
        return self.async_show_form(
            step_id="init",
            data_schema=main_params_schema_minimal(merged),
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: numbers and optional entities; keep or repair lat/lon."""
        merged = self._merged_config()
        if not hasattr(self, "_options_partial"):
            return await self.async_step_init()
        if user_input is not None:
            user_input = dict(user_input)
            _apply_advanced_optional_entities(user_input)
            base = {**merged, **self._options_partial}
            lat, lon = _latitude_longitude_preserve_or_home(self.hass, base)
            self._options = {
                **base,
                **user_input,
                CONF_LATITUDE: lat,
                CONF_LONGITUDE: lon,
            }
            return await self.async_step_strings()
        base = {**merged, **self._options_partial}
        return self.async_show_form(
            step_id="advanced",
            data_schema=main_params_schema_advanced(base),
        )

    async def async_step_strings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: PV strings."""
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
        strings = merged.get(
            CONF_STRINGS,
            [
                {
                    CONF_SYSTEM_SIZE_KW: DEFAULT_SYSTEM_SIZE_KW,
                    CONF_TILT: DEFAULT_TILT,
                    CONF_AZIMUTH: DEFAULT_AZIMUTH,
                },
                {
                    CONF_SYSTEM_SIZE_KW: DEFAULT_SYSTEM_SIZE_KW,
                    CONF_TILT: DEFAULT_TILT,
                    CONF_AZIMUTH: DEFAULT_AZIMUTH,
                },
            ],
        )
        schema = strings_schema_from_config(strings)
        return self.async_show_form(step_id="strings", data_schema=schema)
