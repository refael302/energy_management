"""Persist learned power (kW) and in-progress learn samples (W) to disk; invalidate when consumer list or house sensor changes."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import (
    CONF_CONSUMERS,
    CONF_CONSUMER_POWER_SENSOR_ENTITY_ID,
    CONF_CONSUMER_SWITCH_ENTITY_ID,
    CONF_HOUSE_CONSUMPTION_SENSOR,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONSUMER_LEARN_DISK_VERSION = 1


def _normalize_consumers(raw: Any) -> list[dict[str, str]]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            out.append(
                {
                    CONF_CONSUMER_SWITCH_ENTITY_ID: item,
                    CONF_CONSUMER_POWER_SENSOR_ENTITY_ID: "",
                }
            )
        elif isinstance(item, dict):
            switch_eid = item.get(CONF_CONSUMER_SWITCH_ENTITY_ID)
            sensor_eid = item.get(CONF_CONSUMER_POWER_SENSOR_ENTITY_ID) or ""
            if isinstance(switch_eid, str):
                out.append(
                    {
                        CONF_CONSUMER_SWITCH_ENTITY_ID: switch_eid,
                        CONF_CONSUMER_POWER_SENSOR_ENTITY_ID: str(sensor_eid),
                    }
                )
    return out


def consumer_learn_fingerprint(config: dict[str, Any]) -> str:
    """Invalidate learned power when consumer mapping or house consumption sensor changes."""
    consumers = sorted(
        _normalize_consumers(config.get(CONF_CONSUMERS)),
        key=lambda x: x.get(CONF_CONSUMER_SWITCH_ENTITY_ID, ""),
    )
    house = config.get(CONF_HOUSE_CONSUMPTION_SENSOR) or ""
    raw = json.dumps(
        {"consumers": consumers, "house_consumption_sensor": str(house)},
        sort_keys=True,
    ).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def create_consumer_learn_store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, CONSUMER_LEARN_DISK_VERSION, f"{DOMAIN}.{entry_id}.consumer_learn")
