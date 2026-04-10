"""Battery strategy (FULL/LOW/…) from forecast margins or SOC bands when no forecast."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...const import (
    MARGIN_HIGH_THRESHOLD,
    MARGIN_MEDIUM_MAX,
    STRATEGY_FULL,
    STRATEGY_HIGH,
    STRATEGY_LOW,
    STRATEGY_MEDIUM,
)

if TYPE_CHECKING:
    from ..energy_model import EnergyModel


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
