"""System mode from current SOC vs strategy and forecast / night headroom."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...const import (
    MORNING_DRAIN_MAX_HOURS_BEFORE_FIRST_PV,
    MORNING_DRAIN_MAX_SOLAR_KW,
    MORNING_DRAIN_SOC_BUFFER_PERCENT,
    SYSTEM_MODE_NORMAL,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)

from .types import ModeAdvice

if TYPE_CHECKING:
    from ..energy_model import EnergyModel


def _morning_pre_pv_drain_should_waste(model: EnergyModel) -> bool:
    """
    Before meaningful PV, keep (or enter) wasting while SOC is still above the morning
    floor so the pack can drain toward the planning target instead of idling high.
    """
    if model.battery_status == "very low":
        return False
    if not getattr(model, "forecast_available", True):
        return False
    if float(getattr(model, "evening_margin_kwh", -1.0)) < 0.0:
        return False
    if not getattr(model, "can_drain_to_morning_floor", False):
        return False
    if not getattr(model, "can_refill_tomorrow_to_full", False):
        return False
    soc = float(model.battery_soc)
    floor = float(model.morning_target_percent)
    if soc <= floor + float(MORNING_DRAIN_SOC_BUFFER_PERCENT):
        return False
    h_pv = float(getattr(model, "hours_until_first_pv", 999.0))
    if h_pv <= 0.0 or h_pv > float(MORNING_DRAIN_MAX_HOURS_BEFORE_FIRST_PV):
        return False
    solar_kw = float(getattr(model, "solar_production_kw", 0.0))
    if solar_kw >= float(MORNING_DRAIN_MAX_SOLAR_KW):
        return False
    return True


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
        if _morning_pre_pv_drain_should_waste(model):
            return ModeAdvice(
                SYSTEM_MODE_WASTING,
                "Morning drain to floor before PV",
            )
        return ModeAdvice(
            SYSTEM_MODE_NORMAL,
            "Below recommendation (forecast/night headroom OK)",
        )
    return ModeAdvice(SYSTEM_MODE_SAVING, "Below recommendation")
