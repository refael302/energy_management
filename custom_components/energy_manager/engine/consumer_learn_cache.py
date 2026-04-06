"""Persist learned power (kW) and in-progress learn samples (W) to disk; invalidate when consumer list or house sensor changes."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import CONF_CONSUMER_SWITCHES, CONF_HOUSE_CONSUMPTION_SENSOR, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONSUMER_LEARN_DISK_VERSION = 1


def _normalize_consumer_entity_ids(raw: Any) -> list[str]:
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


def consumer_learn_fingerprint(config: dict[str, Any]) -> str:
    """Invalidate learned power when consumer entities or house consumption sensor change."""
    consumers = sorted(_normalize_consumer_entity_ids(config.get(CONF_CONSUMER_SWITCHES)))
    house = str(config.get(CONF_HOUSE_CONSUMPTION_SENSOR) or "")
    raw = json.dumps({"consumers": consumers, "house": house}, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def create_consumer_learn_store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, CONSUMER_LEARN_DISK_VERSION, f"{DOMAIN}.{entry_id}.consumer_learn")
