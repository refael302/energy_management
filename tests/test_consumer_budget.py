"""Consumer budget selection (discharge headroom + projected post-load gating)."""

from __future__ import annotations

from energy_manager.const import (
    CONSUMER_DISCHARGE_HEADROOM_SAFETY_KW,
    CONSUMER_UNLEARNED_ASSUMED_KW,
    DISCHARGE_HEADROOM_FRACTION,
)
from energy_manager.engine.consumer_budget import (
    battery_load_delta_kw,
    fits_discharge_ceiling_after_extra,
    next_unlearned_for_sampling,
    operational_discharge_ceiling_kw,
    select_learned_consumers,
)


def test_select_learned_consumers_respects_discharge_safety_slack() -> None:
    """Legacy path: without safety slack both fit; with slack only the first fits."""
    ordered = ["switch.a", "switch.b"]
    learned = {"switch.a": 2.0, "switch.b": 2.0}
    budget = 10.0
    d_head = 4.0
    m = 1.0
    sel = select_learned_consumers(ordered, learned, budget, d_head, m)
    assert sel == {"switch.a"}


def test_battery_load_delta_partial_pv_overflow() -> None:
    """PV covers house but only part of the new load → overflow hits battery."""
    # solar 2, house 1, extra 2 → after house+extra=3, overflow 1
    assert battery_load_delta_kw(2.0, 1.0, 2.0) == 1.0
    # PV still covers house+extra
    assert battery_load_delta_kw(5.0, 1.0, 2.0) == 0.0
    # Already short → full extra on battery
    assert battery_load_delta_kw(0.5, 1.0, 2.0) == 2.0


def test_select_blocks_when_pv_covers_house_but_not_consumer() -> None:
    """Current marginal would be 0 (PV≥house), but projected overflow breaches ceiling."""
    ordered = ["switch.dvd"]
    learned = {"switch.dvd": 3.0}
    # max discharge 3 → ceiling 3*(1-0.3)=2.1; projected 0+3=3 > 2.1
    max_dis = 3.0
    ceiling = operational_discharge_ceiling_kw(max_dis)
    assert ceiling == 3.0 * (1.0 - DISCHARGE_HEADROOM_FRACTION)
    sel = select_learned_consumers(
        ordered,
        learned,
        budget_kw=10.0,
        discharge_headroom_kw=80.0,  # legacy would allow
        marginal_battery_per_kw=0.0,  # PV covers house *now*
        solar_production_kw=1.0,
        house_consumption_kw=0.8,
        battery_discharge_kw=0.0,
        max_battery_discharge_kw=max_dis,
        currently_on=set(),
    )
    assert sel == set()


def test_select_allows_when_projected_fits_ceiling() -> None:
    ordered = ["switch.dvd"]
    learned = {"switch.dvd": 2.0}
    # max 10 → ceiling 7; projected discharge 2 + safety 0.25 < 7
    sel = select_learned_consumers(
        ordered,
        learned,
        budget_kw=10.0,
        discharge_headroom_kw=80.0,
        marginal_battery_per_kw=0.0,
        solar_production_kw=0.5,
        house_consumption_kw=0.5,
        battery_discharge_kw=0.0,
        max_battery_discharge_kw=10.0,
        currently_on=set(),
    )
    assert sel == {"switch.dvd"}


def test_select_does_not_double_count_already_on() -> None:
    """Consumer already on is in house reading — do not add its kw again as extra."""
    ordered = ["switch.dvd"]
    learned = {"switch.dvd": 3.0}
    # With currently_on: extra=0 → projected=1.0 stays under ceiling 2.1.
    # If double-counted (extra=3): projected≈4 → would be excluded.
    sel = select_learned_consumers(
        ordered,
        learned,
        budget_kw=10.0,
        discharge_headroom_kw=80.0,
        marginal_battery_per_kw=1.0,
        solar_production_kw=0.0,
        house_consumption_kw=3.0,
        battery_discharge_kw=1.0,
        max_battery_discharge_kw=3.0,
        currently_on={"switch.dvd"},
    )
    assert sel == {"switch.dvd"}
    sel_double = select_learned_consumers(
        ordered,
        learned,
        budget_kw=10.0,
        discharge_headroom_kw=80.0,
        marginal_battery_per_kw=1.0,
        solar_production_kw=0.0,
        house_consumption_kw=3.0,
        battery_discharge_kw=1.0,
        max_battery_discharge_kw=3.0,
        currently_on=set(),  # wrongly treat as off → double count vs house
    )
    assert sel_double == set()


def test_fits_discharge_ceiling_helper() -> None:
    assert fits_discharge_ceiling_after_extra(
        solar_production_kw=0.0,
        house_consumption_kw=0.5,
        battery_discharge_kw=0.5,
        max_battery_discharge_kw=10.0,
        extra_load_kw=2.0,
        safety_kw=CONSUMER_DISCHARGE_HEADROOM_SAFETY_KW,
    )
    assert not fits_discharge_ceiling_after_extra(
        solar_production_kw=0.0,
        house_consumption_kw=0.5,
        battery_discharge_kw=0.5,
        max_battery_discharge_kw=3.0,
        extra_load_kw=3.0,
        safety_kw=CONSUMER_DISCHARGE_HEADROOM_SAFETY_KW,
    )


def test_next_unlearned_requires_headroom_when_on_battery() -> None:
    ordered = ["switch.a", "switch.b"]
    learned: dict[str, float] = {}
    on_targets: set[str] = set()
    m = 1.0
    assert (
        next_unlearned_for_sampling(
            ordered,
            learned,
            on_targets,
            discharge_headroom_kw=1.5,
            marginal_battery_per_kw=m,
        )
        is None
    )
    assert (
        next_unlearned_for_sampling(
            ordered,
            learned,
            on_targets,
            discharge_headroom_kw=2.0,
            marginal_battery_per_kw=m,
        )
        == "switch.a"
    )


def test_next_unlearned_projected_blocks_tight_ceiling() -> None:
    ordered = ["switch.x"]
    # Assumed 2 kW with solar 1 / house 0.5 → battery delta 1.5; max 2 → ceiling 1.4.
    assert (
        next_unlearned_for_sampling(
            ordered,
            {},
            set(),
            discharge_headroom_kw=80.0,
            marginal_battery_per_kw=0.0,
            solar_production_kw=1.0,
            house_consumption_kw=0.5,
            battery_discharge_kw=0.0,
            max_battery_discharge_kw=2.0,
            currently_on=set(),
        )
        is None
    )


def test_next_unlearned_default_min_headroom_matches_assumed_kw() -> None:
    """Default gate uses CONSUMER_UNLEARNED_ASSUMED_KW (2 kW)."""
    ordered = ["switch.x"]
    learned: dict[str, float] = {}
    on_targets: set[str] = set()
    assert (
        next_unlearned_for_sampling(
            ordered,
            learned,
            on_targets,
            discharge_headroom_kw=CONSUMER_UNLEARNED_ASSUMED_KW - 0.01,
            marginal_battery_per_kw=1.0,
        )
        is None
    )
    assert (
        next_unlearned_for_sampling(
            ordered,
            learned,
            on_targets,
            discharge_headroom_kw=CONSUMER_UNLEARNED_ASSUMED_KW,
            marginal_battery_per_kw=1.0,
        )
        == "switch.x"
    )


def test_next_unlearned_skips_learned_and_on_targets_only() -> None:
    ordered = ["switch.first", "switch.second"]
    learned = {"switch.first": 1.0}
    on_targets = {"switch.second"}
    out = next_unlearned_for_sampling(
        ordered,
        learned,
        on_targets,
        discharge_headroom_kw=5.0,
        marginal_battery_per_kw=0.0,
    )
    assert out is None
