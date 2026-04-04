"""Energy Manager – Home Assistant integration for solar energy management."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er

from .const import DOMAIN, NAME, SERVICE_RESET_CONSUMER_LEARN
from .coordinator import EnergyManagerCoordinator
from .engine.consumer_learn_cache import consumer_learn_fingerprint

_LOGGER = logging.getLogger(__name__)

# Keys removed from config; strip from existing entries on migrate
_LEGACY_BASELINE_CONSUMPTION = "baseline_consumption"
_LEGACY_MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
_LEGACY_SAFETY_FORECAST_FACTOR = "safety_forecast_factor"
_LEGACY_CONSUMER_DELAY = "consumer_delay"
_LEGACY_EOD_BATTERY_TARGET = "eod_battery_target"
_LEGACY_MAX_BATTERY_CURRENT_AMPS = "max_battery_current_amps"
_LEGACY_BATTERY_CURRENT_SENSOR = "battery_current_sensor"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.SELECT]

RESET_CONSUMER_LEARN_SCHEMA = vol.Schema(
    {vol.Optional("config_entry_id"): cv.string}
)


async def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_RESET_CONSUMER_LEARN):
        return

    async def handle_reset_consumer_learn(call: ServiceCall) -> None:
        entry_id = call.data.get("config_entry_id")
        domain_data = hass.data.get(DOMAIN)
        if not isinstance(domain_data, dict):
            return
        if entry_id:
            targets = [entry_id] if entry_id in domain_data else []
        else:
            targets = [
                k
                for k, v in domain_data.items()
                if isinstance(k, str) and hasattr(v, "consumer_learner")
            ]
        for eid in targets:
            coord = domain_data.get(eid)
            if coord is None or not hasattr(coord, "consumer_learner"):
                continue
            cfg = {**coord.entry.data, **(coord.entry.options or {})}
            fp = consumer_learn_fingerprint(cfg)
            await coord.consumer_learner.async_reset(fp)
            if coord.data is not None:
                coord.async_set_updated_data(
                    {
                        **coord.data,
                        "consumer_learned_kw": coord.consumer_learner.get_learned_kw(),
                        "consumer_learned_power_kw": 0.0,
                        "consumer_learn_pending_samples": coord.consumer_learner.get_pending_counts(),
                    }
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_CONSUMER_LEARN,
        handle_reset_consumer_learn,
        schema=RESET_CONSUMER_LEARN_SCHEMA,
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config upgrades through v7 (battery power peaks; strip legacy current/amps)."""
    current = entry.version
    if current >= 7:
        return True

    data = {**entry.data}
    options = dict(entry.options) if entry.options else {}

    if current < 2:
        data.pop(_LEGACY_BASELINE_CONSUMPTION, None)
        options.pop(_LEGACY_BASELINE_CONSUMPTION, None)
        current = 2

    if current < 3:
        data.pop(_LEGACY_MINIMUM_BATTERY_RESERVE, None)
        options.pop(_LEGACY_MINIMUM_BATTERY_RESERVE, None)
        current = 3

    if current < 4:
        data.pop(_LEGACY_SAFETY_FORECAST_FACTOR, None)
        options.pop(_LEGACY_SAFETY_FORECAST_FACTOR, None)
        current = 4

    if current < 5:
        data.pop(_LEGACY_CONSUMER_DELAY, None)
        options.pop(_LEGACY_CONSUMER_DELAY, None)
        current = 5

    if current < 6:
        data.pop(_LEGACY_EOD_BATTERY_TARGET, None)
        options.pop(_LEGACY_EOD_BATTERY_TARGET, None)
        current = 6

    if current < 7:
        from .const import (
            CONF_BATTERY_POWER_SENSOR,
            DEFAULT_BATTERY_NOMINAL_VOLTAGE,
            DEFAULT_MAX_BATTERY_CURRENT_AMPS,
            MIN_EFFECTIVE_MAX_BATTERY_POWER_KW,
        )
        from .engine.battery_power_peak_cache import (
            battery_power_peak_fingerprint,
            create_battery_peak_store,
        )

        merged = {**data, **options}
        amps_raw = merged.get(_LEGACY_MAX_BATTERY_CURRENT_AMPS)
        try:
            amps = (
                float(amps_raw)
                if amps_raw is not None
                else float(DEFAULT_MAX_BATTERY_CURRENT_AMPS)
            )
        except (TypeError, ValueError):
            amps = float(DEFAULT_MAX_BATTERY_CURRENT_AMPS)
        seed_kw = max(
            MIN_EFFECTIVE_MAX_BATTERY_POWER_KW,
            amps * float(DEFAULT_BATTERY_NOMINAL_VOLTAGE) / 1000.0,
        )
        data.pop(_LEGACY_MAX_BATTERY_CURRENT_AMPS, None)
        options.pop(_LEGACY_MAX_BATTERY_CURRENT_AMPS, None)
        data.pop(_LEGACY_BATTERY_CURRENT_SENSOR, None)
        options.pop(_LEGACY_BATTERY_CURRENT_SENSOR, None)
        cfg_for_fp = {**data, **options}
        fp = battery_power_peak_fingerprint(cfg_for_fp)
        store = create_battery_peak_store(hass, entry.entry_id)
        await store.async_save(
            {
                "fingerprint": fp,
                "peak_discharge_kw": round(seed_kw, 4),
                "peak_charge_kw": round(seed_kw, 4),
                "sample_ticks": 0,
            }
        )
        if not cfg_for_fp.get(CONF_BATTERY_POWER_SENSOR):
            _LOGGER.warning(
                "Energy Manager migration v7: no battery power sensor; peak store may mismatch until configured"
            )
        current = 7

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options if options else None,
        version=current,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Manager from a config entry."""
    if not isinstance(hass.data.get(DOMAIN), dict):
        hass.data[DOMAIN] = {}
    # Single device for this config entry (avoid duplicate "refael302" vs "Energy Manager")
    dev_reg = dr.async_get(hass)
    our_identifiers = {(DOMAIN, entry.entry_id)}
    devices_with_entry = [
        d for d in dev_reg.devices.values()
        if entry.entry_id in d.config_entries
    ]
    if devices_with_entry:
        # Use first device that already has our identifiers, or take the first and adopt it
        device = next(
            (d for d in devices_with_entry if d.identifiers == our_identifiers),
            devices_with_entry[0],
        )
        dev_reg.async_update_device(
            device.id,
            new_identifiers=our_identifiers,
            name=entry.title or NAME,
            manufacturer=NAME,
        )
        # Unlink other devices from this config entry so only one device remains
        for other in devices_with_entry:
            if other.id != device.id:
                dev_reg.async_update_device(other.id, remove_config_entry_id=entry.entry_id)
    else:
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers=our_identifiers,
            name=entry.title or NAME,
            manufacturer=NAME,
        )
    coordinator = EnergyManagerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Link all entities for this config entry to this device
    ent_reg = er.async_get(hass)
    for ent_entry in ent_reg.entities.values():
        if ent_entry.config_entry_id == entry.entry_id and ent_entry.device_id != device.id:
            ent_reg.async_update_entity(ent_entry.entity_id, device_id=device.id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        if isinstance(hass.data.get(DOMAIN), dict):
            hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
