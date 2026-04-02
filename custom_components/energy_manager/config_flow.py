"""Config flow for Energy Manager integration."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .config_schema import (
    main_params_schema_options,
    main_params_schema_user,
    strings_schema_from_config,
    strings_schema_install_defaults,
)
from .const import (
    CONF_AZIMUTH,
    CONF_BATTERY_CURRENT_SENSOR,
    CONF_LIGHTS_TO_TURN_OFF,
    CONF_RECOMMENDED_TO_TURN_OFF,
    CONF_STRINGS,
    CONF_SYSTEM_SIZE_KW,
    CONF_TILT,
    DEFAULT_AZIMUTH,
    DEFAULT_SYSTEM_SIZE_KW,
    DEFAULT_TILT,
    DOMAIN,
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
            data_schema=main_params_schema_user(self.hass),
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
            data_schema=main_params_schema_options(self.hass, merged),
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
