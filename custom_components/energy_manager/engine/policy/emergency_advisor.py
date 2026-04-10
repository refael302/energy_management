"""Emergency rules: max charge → wasting, very low → emergency; discharge ceiling hints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...const import (
    SYSTEM_MODE_EMERGENCY_SAVING,
    SYSTEM_MODE_WASTING,
)

from .types import EmergencyAdvice, EmergencyEvaluation

if TYPE_CHECKING:
    from ..energy_model import EnergyModel


def evaluate_emergency(
    model: EnergyModel,
    charge_state_max_duration_minutes: float,
    *,
    discharge_just_entered_max: bool = False,
) -> EmergencyEvaluation:
    """
    Priority 1–2 of legacy decide(): max charging duration, very low SOC.
    When discharge_just_entered_max (operational ceiling), request shed + no new turn-ons
    for this tick (phase 2 — coordinated with LoadManager).
    """
    charging_state = model.charge_state
    battery_status = model.battery_status

    if charging_state == "max" and charge_state_max_duration_minutes >= 5:
        return EmergencyEvaluation(
            mode_override=EmergencyAdvice(
                SYSTEM_MODE_WASTING,
                "Max charging for 5 minutes",
            ),
        )

    if battery_status == "very low" and charging_state != "max":
        return EmergencyEvaluation(
            mode_override=EmergencyAdvice(
                SYSTEM_MODE_EMERGENCY_SAVING,
                "Very low battery",
            ),
        )

    if model.discharge_state == "max":
        return EmergencyEvaluation(
            suppress_wasting_turn_ons=True,
            force_shed_one_consumer=discharge_just_entered_max,
        )

    return EmergencyEvaluation()
