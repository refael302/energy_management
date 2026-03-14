"""
Decision engine – replicates YAML DECISIONS: battery strategy + energy mode.
Inputs: battery_soc, solar_production, house_consumption, forecast_remaining, model state.
Outputs: strategy_recommendation (low/medium/high/full), strategy_reason, system_mode (saving/normal/wasting).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..const import (
    MARGIN_HIGH_THRESHOLD,
    MARGIN_MEDIUM_MAX,
    STRATEGY_FULL,
    STRATEGY_HIGH,
    STRATEGY_LOW,
    STRATEGY_MEDIUM,
    SYSTEM_MODE_NORMAL,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)

if TYPE_CHECKING:
    from .energy_model import EnergyModel


@dataclass
class DecisionResult:
    """Output of the decision engine."""

    strategy_recommendation: str
    strategy_reason: str
    system_mode: str  # saving | normal | wasting
    mode_reason: str  # short reason why this mode was chosen


def recommend_battery_strategy(model: EnergyModel) -> tuple[str, str]:
    """
    Replicate script recommend_battery_strategy_v5.
    Returns (strategy_recommendation, strategy_reason).
    When forecast is unavailable, recommend FULL (conservative) and reason explains we use current state only.
    """
    if not getattr(model, "forecast_available", True):
        return (
            STRATEGY_FULL,
            "FULL – forecast unavailable, using current state only",
        )

    daily_margin = model.daily_margin_kwh
    consumption_next_hour = model.house_consumption_kw
    pv_next_hour = model.forecast_next_hour_kwh

    if daily_margin < 0:
        return (
            STRATEGY_FULL,
            f"FULL – EOD target not reachable (daily_margin={daily_margin} kWh)",
        )
    if pv_next_hour < consumption_next_hour:
        return (
            STRATEGY_FULL,
            f"FULL – no PV for next hour (need {consumption_next_hour} kWh)",
        )
    if daily_margin <= MARGIN_HIGH_THRESHOLD:
        return (
            STRATEGY_HIGH,
            f"HIGH – small daily buffer ({daily_margin} kWh)",
        )
    if MARGIN_HIGH_THRESHOLD < daily_margin <= MARGIN_MEDIUM_MAX:
        return (
            STRATEGY_MEDIUM,
            f"MEDIUM – medium daily buffer ({daily_margin} kWh)",
        )
    return (
        STRATEGY_LOW,
        f"LOW – large daily buffer ({daily_margin} kWh)",
    )


class DecisionEngine:
    """
    Replicates automation "[חבילת אנרגיה] החלטות – בחירת מצב".
    Priority: 1) Max charging → wasting, 2) Very low battery → saving,
    3) Can waste → wasting, 4) Low battery → saving, 5) At recommendation → normal,
    6) Default → saving.
    """

    def __init__(self, manual_override: bool = False) -> None:
        self.manual_override = manual_override
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

    def decide(self, model: EnergyModel) -> DecisionResult:
        """
        Compute strategy recommendation and system mode from current model.
        If manual_override, returns current mode as normal (no auto changes).
        """
        strategy, reason = recommend_battery_strategy(model)
        model.set_strategy_recommendation(strategy)

        if self.manual_override:
            return DecisionResult(
                strategy_recommendation=strategy,
                strategy_reason=reason,
                system_mode=SYSTEM_MODE_NORMAL,
                mode_reason="Manual override",
            )

        battery_status = model.battery_status
        charging_state = model.charge_state
        can_waste = model.can_waste_energy
        rec = strategy

        # 1. Max charging for 5 min → wasting
        if charging_state == "max" and self._charge_state_max_duration_minutes >= 5:
            return DecisionResult(
                strategy_recommendation=strategy,
                strategy_reason=reason,
                system_mode=SYSTEM_MODE_WASTING,
                mode_reason="Max charging for 5 minutes",
            )

        # 2. Very low battery + not max charging → saving (super)
        if battery_status == "very low" and charging_state != "max":
            return DecisionResult(
                strategy_recommendation=strategy,
                strategy_reason=reason,
                system_mode=SYSTEM_MODE_SAVING,
                mode_reason="Very low battery",
            )

        # 3. Can waste energy → wasting
        if can_waste:
            return DecisionResult(
                strategy_recommendation=strategy,
                strategy_reason=reason,
                system_mode=SYSTEM_MODE_WASTING,
                mode_reason="Can waste energy",
            )

        # 4. Low battery + not max charging → saving
        if battery_status == "low" and charging_state != "max":
            return DecisionResult(
                strategy_recommendation=strategy,
                strategy_reason=reason,
                system_mode=SYSTEM_MODE_SAVING,
                mode_reason="Low battery",
            )

        # 5. Battery at recommendation level → normal (Off)
        levels = {"very low": 0, "low": 1, "medium": 2, "high": 3, "full": 4}
        min_level = {"low": 1, "medium": 2, "high": 3, "full": 4}
        cur = levels.get(battery_status, 0)
        req = min_level.get(rec, 4)
        if cur == req:
            return DecisionResult(
                strategy_recommendation=strategy,
                strategy_reason=reason,
                system_mode=SYSTEM_MODE_NORMAL,
                mode_reason="Battery at recommendation level",
            )

        # 6. Default: below recommendation → saving
        return DecisionResult(
            strategy_recommendation=strategy,
            strategy_reason=reason,
            system_mode=SYSTEM_MODE_SAVING,
            mode_reason="Below recommendation",
        )
