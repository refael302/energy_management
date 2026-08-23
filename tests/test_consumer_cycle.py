"""Per-consumer auto control filtering (on and off in wasting/normal)."""

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


def test_disabled_consumer_excluded_from_wasting_pool() -> None:
    """AC with auto control off must not appear in wasting ordered/target pool.

    Regression: v1.18.1 put all consumers in consumers_ordered while excluding
    disabled ones from learned_target, so an ON AC was turned off as
    wasting_not_in_target midday despite auto control being off.
    """
    all_consumers = [
        "switch.dvd",
        "switch.mzgn_ykhydh_on_off",
        "switch.mpzr_khvm",
    ]
    enabled_map = {
        "switch.dvd": True,
        "switch.mzgn_ykhydh_on_off": False,
        "switch.mpzr_khvm": True,
    }
    active = filter_cycle_active_consumers(all_consumers, enabled_map)
    assert "switch.mzgn_ykhydh_on_off" not in active
    assert active == ["switch.dvd", "switch.mpzr_khvm"]
