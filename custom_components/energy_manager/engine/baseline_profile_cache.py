"""Persist learned hourly baseline profile; invalidate when house sensor or consumer list changes."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import DOMAIN

BASELINE_PROFILE_DISK_VERSION = 1


def create_baseline_profile_store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, BASELINE_PROFILE_DISK_VERSION, f"{DOMAIN}.{entry_id}.baseline_profile")
