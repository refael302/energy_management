"""Consumer budget selection (discharge headroom safety slack)."""

from __future__ import annotations

from energy_manager.const import CONSUMER_UNLEARNED_ASSUMED_KW
from energy_manager.engine.consumer_budget import (
    next_unlearned_for_sampling,
    select_learned_consumers,
)


def test_select_learned_consumers_respects_discharge_safety_slack() -> None:
    """Without safety slack both fit; with slack only the first fits."""
    ordered = ["switch.a", "switch.b"]
    learned = {"switch.a": 2.0, "switch.b": 2.0}
    budget = 10.0
    d_head = 4.0
    m = 1.0
    sel = select_learned_consumers(ordered, learned, budget, d_head, m)
    assert sel == {"switch.a"}


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
