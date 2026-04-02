"""Persist hourly PV forecast to disk for use when Open-Meteo is unreachable."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

FORECAST_DISK_CACHE_VERSION = 1


def forecast_config_fingerprint(config: dict[str, Any]) -> str:
    """Invalidate stored hourly series when location, strings, or PR change."""
    from ..const import CONF_FORECAST_PR, CONF_LATITUDE, CONF_LONGITUDE, CONF_STRINGS

    payload = {
        "lat": config.get(CONF_LATITUDE),
        "lon": config.get(CONF_LONGITUDE),
        "strings": config.get(CONF_STRINGS),
        "pr": config.get(CONF_FORECAST_PR),
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def create_forecast_store(hass: HomeAssistant, entry_id: str) -> Store:
    """One Store file per config entry under .storage/."""
    return Store(hass, FORECAST_DISK_CACHE_VERSION, f"{DOMAIN}.{entry_id}.forecast_hourly")


def stored_series_covers_now(times_iso: list[str], hass: HomeAssistant, now: datetime) -> bool:
    """True if current time falls within the cached hourly window (with 1h slack)."""
    if len(times_iso) < 2:
        return bool(times_iso)
    try:
        from zoneinfo import ZoneInfo

        tz_name = getattr(hass.config, "time_zone", None) or "UTC"
        try:
            local_zone = ZoneInfo(tz_name)
        except Exception:
            local_zone = ZoneInfo("UTC")

        def _parse(ts: str) -> datetime:
            s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=local_zone)
            return dt

        t0 = _parse(times_iso[0])
        t1 = _parse(times_iso[-1])
        now_ts = now.timestamp()
        return t0.timestamp() - 3600 <= now_ts <= t1.timestamp() + 7200
    except Exception as e:
        _LOGGER.debug("stored_series_covers_now: %s", e)
        return False
