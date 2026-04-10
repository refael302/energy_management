"""Merge manual override, emergency, forecast strategy, and state-based mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...const import (
    STRATEGY_FULL,
    STRATEGY_HIGH,
    STRATEGY_LOW,
    STRATEGY_MEDIUM,
    SYSTEM_MODE_EMERGENCY_SAVING,
    SYSTEM_MODE_NORMAL,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)

from .emergency_advisor import evaluate_emergency
from .state_mode_advisor import advise_state_mode
from .types import PolicyDecision

if TYPE_CHECKING:
    from ..energy_model import EnergyModel

_VALID_MANUAL_MODES = frozenset(
    {
        SYSTEM_MODE_SAVING,
        SYSTEM_MODE_NORMAL,
        SYSTEM_MODE_WASTING,
        SYSTEM_MODE_EMERGENCY_SAVING,
    }
)
_VALID_STRATEGIES = frozenset(
    {STRATEGY_LOW, STRATEGY_MEDIUM, STRATEGY_HIGH, STRATEGY_FULL}
)


def merge_policy(
    model: EnergyModel,
    *,
    strategy: str,
    strategy_reason: str,
    charge_state_max_duration_minutes: float,
    manual_mode_override: bool = False,
    manual_strategy_override: bool = False,
    manual_mode: str | None = None,
    manual_strategy: str | None = None,
    discharge_just_entered_max: bool = False,
) -> PolicyDecision:
    """
    Arbiter order:
    1) Manual strategy override (applied before this call via strategy/strategy_reason)
    2) Manual mode override
    3) Emergency (max charge, very low; discharge ceiling hints)
    4) State-based mode given resolved strategy
    """
    strat = strategy
    strat_reason = strategy_reason

    if manual_strategy_override and manual_strategy in _VALID_STRATEGIES:
        strat = manual_strategy
        strat_reason = "Manual strategy"

    model.set_strategy_recommendation(strat)

    if manual_mode_override and manual_mode in _VALID_MANUAL_MODES:
        return PolicyDecision(
            strategy_recommendation=strat,
            strategy_reason=strat_reason,
            system_mode=manual_mode,
            mode_reason="Manual mode",
        )

    ev = evaluate_emergency(
        model,
        charge_state_max_duration_minutes,
        discharge_just_entered_max=discharge_just_entered_max,
    )

    if ev.mode_override is not None:
        return PolicyDecision(
            strategy_recommendation=strat,
            strategy_reason=strat_reason,
            system_mode=ev.mode_override.system_mode,
            mode_reason=ev.mode_override.mode_reason,
            suppress_wasting_turn_ons=ev.suppress_wasting_turn_ons,
            force_shed_one_consumer=ev.force_shed_one_consumer,
        )

    mode_advice = advise_state_mode(model, strat)
    return PolicyDecision(
        strategy_recommendation=strat,
        strategy_reason=strat_reason,
        system_mode=mode_advice.system_mode,
        mode_reason=mode_advice.mode_reason,
        suppress_wasting_turn_ons=ev.suppress_wasting_turn_ons,
        force_shed_one_consumer=ev.force_shed_one_consumer,
    )
