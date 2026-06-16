"""Per-consumer cycle participation (quick neutral) helpers."""

from __future__ import annotations

from typing import Any

from .const import CONF_CONSUMER_CYCLE_ENABLED


def get_consumer_cycle_enabled_map(config: dict[str, Any]) -> dict[str, bool]:
    """Per-consumer cycle participation from options (default True when unset)."""
    raw = config.get(CONF_CONSUMER_CYCLE_ENABLED) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): bool(v) for k, v in raw.items()}


def is_consumer_cycle_enabled(
    entity_id: str, enabled_map: dict[str, bool]
) -> bool:
    """True when the integration may auto-control this consumer."""
    if entity_id in enabled_map:
        return enabled_map[entity_id]
    return True


def filter_cycle_active_consumers(
    entity_ids: list[str], enabled_map: dict[str, bool]
) -> list[str]:
    """Consumers that participate in wasting rotation and auto control."""
    return [eid for eid in entity_ids if is_consumer_cycle_enabled(eid, enabled_map)]
