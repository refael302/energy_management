"""Consumer budget selection (discharge headroom safety slack)."""

from __future__ import annotations

from energy_manager.engine.consumer_budget import select_learned_consumers


def test_select_learned_consumers_respects_discharge_safety_slack() -> None:
    """Without safety slack both fit; with slack only the first fits."""
    ordered = ["switch.a", "switch.b"]
    learned = {"switch.a": 2.0, "switch.b": 2.0}
    budget = 10.0
    d_head = 4.0
    m = 1.0
    sel = select_learned_consumers(ordered, learned, budget, d_head, m)
    assert sel == {"switch.a"}
