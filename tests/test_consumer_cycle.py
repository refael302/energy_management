"""Per-consumer cycle enable / quick-neutral filtering."""

from __future__ import annotations

from energy_manager.consumer_cycle import (
    filter_cycle_active_consumers,
    get_consumer_cycle_enabled_map,
    is_consumer_cycle_enabled,
)
from energy_manager.const import CONF_CONSUMER_CYCLE_ENABLED


def test_cycle_enabled_defaults_true() -> None:
    assert is_consumer_cycle_enabled("switch.a", {}) is True
    assert filter_cycle_active_consumers(
        ["switch.a", "switch.b"], {}
    ) == ["switch.a", "switch.b"]


def test_cycle_enabled_map_from_config() -> None:
    cfg = {
        CONF_CONSUMER_CYCLE_ENABLED: {
            "switch.a": False,
            "switch.b": True,
        }
    }
    assert get_consumer_cycle_enabled_map(cfg) == {
        "switch.a": False,
        "switch.b": True,
    }
    assert is_consumer_cycle_enabled("switch.a", get_consumer_cycle_enabled_map(cfg)) is False
    assert filter_cycle_active_consumers(
        ["switch.a", "switch.b", "switch.c"],
        get_consumer_cycle_enabled_map(cfg),
    ) == ["switch.b", "switch.c"]
