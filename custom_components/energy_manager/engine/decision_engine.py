"""
Decision engine – replicates YAML DECISIONS: battery strategy + energy mode.
Delegates to policy package: forecast strategy advisor, emergency, state mode, arbiter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..const import (
    STRATEGY_FULL,
    STRATEGY_HIGH,
    STRATEGY_LOW,
    STRATEGY_MEDIUM,
    SYSTEM_MODE_EMERGENCY_SAVING,
    SYSTEM_MODE_NORMAL,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)
from .policy.arbiter import merge_policy
from .policy.forecast_strategy_advisor import (
    recommend_battery_strategy,
    recommend_battery_strategy_no_forecast,
)

if TYPE_CHECKING:
    from .energy_model import EnergyModel


@dataclass
class DecisionResult:
    """Output of the decision engine."""

    strategy_recommendation: str
    strategy_reason: str
    system_mode: str  # saving | normal | wasting | emergency_saving
    mode_reason: str  # short reason why this mode was chosen
    suppress_wasting_turn_ons: bool = False
    force_shed_one_consumer: bool = False


class DecisionEngine:
    """
    Replicates automation "[חבילת אנרגיה] החלטות – בחירת מצב".
    Priority: 1) Max charging → wasting, 2) Very low battery → emergency_saving,
    3) Can waste → wasting, 4) Low battery → saving (only if no forecast headroom),
    5) At recommendation → normal, 6) Below recommendation → saving or normal
    when forecast_available and daily_margin >= 0.
    """

    def __init__(self) -> None:
        self._charge_state_max_duration_minutes: float = 0.0
        self._last_charge_state: str = ""

    def update_charge_state_duration(self, charge_state: str, dt_minutes: float) -> None:
        """Track how long charge_state has been 'max' (for 5-minute condition)."""
        if charge_state == "max":
            if self._last_charge_state == "max":
                self._charge_state_max_duration_minutes += dt_minutes
            else:
                self._charge_state_max_duration_minutes = dt_minutes
        else:
            self._charge_state_max_duration_minutes = 0.0
        self._last_charge_state = charge_state

    def decide(
        self,
        model: EnergyModel,
        manual_mode_override: bool = False,
        manual_strategy_override: bool = False,
        manual_mode: str | None = None,
        manual_strategy: str | None = None,
        cached_strategy: tuple[str, str] | None = None,
        *,
        discharge_just_entered_max: bool = False,
    ) -> DecisionResult:
        """
        Compute strategy recommendation and system mode from current model.
        manual_strategy_override: use manual_strategy select; else use recommend_battery_strategy or cached_strategy.
        cached_strategy: when provided (strategy, reason), use instead of calling recommend_battery_strategy.
        discharge_just_entered_max: set by coordinator when discharge_state crosses to max (policy phase 2).
        """
        if cached_strategy is not None:
            strategy, reason = cached_strategy[0], cached_strategy[1]
        else:
            strategy, reason = recommend_battery_strategy(model)

        pd = merge_policy(
            model,
            strategy=strategy,
            strategy_reason=reason,
            charge_state_max_duration_minutes=self._charge_state_max_duration_minutes,
            manual_mode_override=manual_mode_override,
            manual_strategy_override=manual_strategy_override,
            manual_mode=manual_mode,
            manual_strategy=manual_strategy,
            discharge_just_entered_max=discharge_just_entered_max,
        )
        return DecisionResult(
            strategy_recommendation=pd.strategy_recommendation,
            strategy_reason=pd.strategy_reason,
            system_mode=pd.system_mode,
            mode_reason=pd.mode_reason,
            suppress_wasting_turn_ons=pd.suppress_wasting_turn_ons,
            force_shed_one_consumer=pd.force_shed_one_consumer,
        )


__all__ = [
    "DecisionEngine",
    "DecisionResult",
    "recommend_battery_strategy",
    "recommend_battery_strategy_no_forecast",
]
