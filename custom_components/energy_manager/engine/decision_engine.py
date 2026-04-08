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
    SYSTEM_MODE_EMERGENCY_SAVING,
    SYSTEM_MODE_NORMAL,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)

if TYPE_CHECKING:
    from .energy_model import EnergyModel


def recommend_battery_strategy_no_forecast(model: EnergyModel) -> tuple[str, str]:
    """
    When Open-Meteo / PV forecast is unavailable, drive strategy from battery band only.
    Maps each band to the next-lower target so decide() yields wasting until SOC drops
    one level (full→high→medium→low); low / very low stay conservative (FULL).
    """
    status = getattr(model, "battery_status", "medium")
    if status == "full":
        return (
            STRATEGY_HIGH,
            "HIGH – no forecast (target high)",
        )
    if status == "high":
        return (
            STRATEGY_MEDIUM,
            "MEDIUM – no forecast (target medium)",
        )
    if status == "medium":
        return (
            STRATEGY_LOW,
            "LOW – no forecast (target low)",
        )
    return (
        STRATEGY_FULL,
        "FULL – no forecast (conservative)",
    )


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
    When forecast is unavailable, use recommend_battery_strategy_no_forecast (SOC bands).
    """
    if not getattr(model, "forecast_available", True):
        return recommend_battery_strategy_no_forecast(model)

    evening_margin = model.evening_margin_kwh
    morning_margin = model.morning_floor_margin_kwh
    in_night_window = bool(getattr(model, "sun_below_horizon", False)) and (
        float(getattr(model, "hours_until_first_pv", 0.0)) > 0.0
    )
    consumption_next_hour = model.house_consumption_kw
    pv_next_hour = model.forecast_next_hour_kwh

    if evening_margin < 0:
        return (
            STRATEGY_FULL,
            f"FULL – evening full target not reachable (margin={evening_margin} kWh)",
        )
    if in_night_window and (not model.can_refill_tomorrow_to_full or morning_margin < 0):
        why = (
            "tomorrow refill not safe"
            if not model.can_refill_tomorrow_to_full
            else f"morning floor margin={morning_margin} kWh"
        )
        return (STRATEGY_FULL, f"FULL – hold night reserve ({why})")
    if pv_next_hour < consumption_next_hour and not getattr(
        model, "night_bridge_relaxed", False
    ):
        return (
            STRATEGY_FULL,
            f"FULL – no PV for next hour (need {consumption_next_hour} kWh)",
        )
    if evening_margin <= MARGIN_HIGH_THRESHOLD:
        return (
            STRATEGY_HIGH,
            f"HIGH – small evening buffer ({evening_margin} kWh)",
        )
    if MARGIN_HIGH_THRESHOLD < evening_margin <= MARGIN_MEDIUM_MAX:
        return (
            STRATEGY_MEDIUM,
            f"MEDIUM – medium evening buffer ({evening_margin} kWh)",
        )
    return (
        STRATEGY_LOW,
        f"LOW – large evening buffer ({evening_margin} kWh)",
    )


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
    ) -> DecisionResult:
        """
        Compute strategy recommendation and system mode from current model.
        manual_strategy_override: use manual_strategy select; else use recommend_battery_strategy or cached_strategy.
        cached_strategy: when provided (strategy, reason), use instead of calling recommend_battery_strategy.
        """
        if cached_strategy is not None:
            strategy, reason = cached_strategy[0], cached_strategy[1]
        else:
            strategy, reason = recommend_battery_strategy(model)
        if manual_strategy_override and manual_strategy in (STRATEGY_LOW, STRATEGY_MEDIUM, STRATEGY_HIGH, STRATEGY_FULL):
            strat = manual_strategy
            strategy_reason = "Manual strategy"
        else:
            strat = strategy
            strategy_reason = reason
        model.set_strategy_recommendation(strat)

        if manual_mode_override and manual_mode in (SYSTEM_MODE_SAVING, SYSTEM_MODE_NORMAL, SYSTEM_MODE_WASTING, SYSTEM_MODE_EMERGENCY_SAVING):
            return DecisionResult(
                strategy_recommendation=strat,
                strategy_reason=strategy_reason,
                system_mode=manual_mode,
                mode_reason="Manual mode",
            )

        battery_status = model.battery_status
        charging_state = model.charge_state
        rec = strat
        levels = {"very low": 0, "low": 1, "medium": 2, "high": 3, "full": 4}
        min_level = {"low": 1, "medium": 2, "high": 3, "full": 4}
        cur = levels.get(battery_status, 0)
        req = min_level.get(rec, 4)
        # When forecast says we have headroom for the day, do not force saving for
        # "low" SOC or "below strategy level" — only very_low still triggers shutdown.
        forecast_headroom_ok = bool(
            getattr(model, "forecast_available", True)
        ) and model.evening_margin_kwh >= 0.0
        night_drain_ok = bool(
            getattr(model, "can_drain_to_morning_floor", False)
            and getattr(model, "can_refill_tomorrow_to_full", False)
        )
        forecast_or_night_ok = forecast_headroom_ok and (
            not bool(getattr(model, "sun_below_horizon", False)) or night_drain_ok
        )

        # 1. Max charging for 5 min → wasting
        if charging_state == "max" and self._charge_state_max_duration_minutes >= 5:
            return DecisionResult(
                strategy_recommendation=strat,
                strategy_reason=strategy_reason,
                system_mode=SYSTEM_MODE_WASTING,
                mode_reason="Max charging for 5 minutes",
            )

        # 2. Very low battery + not max charging → emergency_saving
        if battery_status == "very low" and charging_state != "max":
            return DecisionResult(
                strategy_recommendation=strat,
                strategy_reason=strategy_reason,
                system_mode=SYSTEM_MODE_EMERGENCY_SAVING,
                mode_reason="Very low battery",
            )

        # 3. Battery above strategy level → wasting
        if cur > req:
            return DecisionResult(
                strategy_recommendation=strat,
                strategy_reason=strategy_reason,
                system_mode=SYSTEM_MODE_WASTING,
                mode_reason="Can waste energy",
            )

        # 4. Low battery + not max charging → saving (conservative when no forecast headroom)
        if (
            battery_status == "low"
            and charging_state != "max"
            and not forecast_or_night_ok
        ):
            return DecisionResult(
                strategy_recommendation=strat,
                strategy_reason=strategy_reason,
                system_mode=SYSTEM_MODE_SAVING,
                mode_reason="Low battery",
            )

        # 5. Battery at recommendation level → normal (Off)
        if cur == req:
            return DecisionResult(
                strategy_recommendation=strat,
                strategy_reason=strategy_reason,
                system_mode=SYSTEM_MODE_NORMAL,
                mode_reason="Battery at recommendation level",
            )

        # 6. Default: below recommendation → saving, or normal if forecast headroom OK
        if forecast_or_night_ok:
            return DecisionResult(
                strategy_recommendation=strat,
                strategy_reason=strategy_reason,
                system_mode=SYSTEM_MODE_NORMAL,
                mode_reason="Below recommendation (forecast/night headroom OK)",
            )
        return DecisionResult(
            strategy_recommendation=strat,
            strategy_reason=strategy_reason,
            system_mode=SYSTEM_MODE_SAVING,
            mode_reason="Below recommendation",
        )
