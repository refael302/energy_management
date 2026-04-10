"""System mode from current SOC vs strategy and forecast / night headroom."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...const import (
    SYSTEM_MODE_NORMAL,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)

from .types import ModeAdvice

if TYPE_CHECKING:
    from ..energy_model import EnergyModel


def advise_state_mode(model: EnergyModel, strategy: str) -> ModeAdvice:
    """
    Steps 3–6 of legacy decide(): SOC vs strategy min level + forecast headroom.
    Does not handle emergency (max charge / very low) — those are in emergency_advisor.
    """
    battery_status = model.battery_status
    charging_state = model.charge_state
    levels = {"very low": 0, "low": 1, "medium": 2, "high": 3, "full": 4}
    min_level = {"low": 1, "medium": 2, "high": 3, "full": 4}
    cur = levels.get(battery_status, 0)
    req = min_level.get(strategy, 4)

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

    if cur > req:
        return ModeAdvice(SYSTEM_MODE_WASTING, "Can waste energy")

    if (
        battery_status == "low"
        and charging_state != "max"
        and not forecast_or_night_ok
    ):
        return ModeAdvice(SYSTEM_MODE_SAVING, "Low battery")

    if cur == req:
        return ModeAdvice(SYSTEM_MODE_NORMAL, "Battery at recommendation level")

    if forecast_or_night_ok:
        return ModeAdvice(
            SYSTEM_MODE_NORMAL,
            "Below recommendation (forecast/night headroom OK)",
        )
    return ModeAdvice(SYSTEM_MODE_SAVING, "Below recommendation")
