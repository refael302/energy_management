"""Persist learned battery charge/discharge power peaks (kW); invalidate when battery power entity changes."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import CONF_BATTERY_POWER_SENSOR, DOMAIN

BATTERY_PEAK_DISK_VERSION = 1
# Bump when learn logic changes so old peaks are not mixed incorrectly
BATTERY_PEAK_LOGIC_VERSION = 1


def battery_power_peak_fingerprint(config: dict[str, Any]) -> str:
    """Invalidate learned peaks when battery power sensor entity changes."""
    bp = str(config.get(CONF_BATTERY_POWER_SENSOR) or "")
    raw = json.dumps(
        {"battery_power": bp, "v": BATTERY_PEAK_LOGIC_VERSION}, sort_keys=True
    ).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def create_battery_peak_store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, BATTERY_PEAK_DISK_VERSION, f"{DOMAIN}.{entry_id}.battery_power_peaks")
