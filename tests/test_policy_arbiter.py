"""Table-style tests for layered policy (arbiter + advisors)."""

from __future__ import annotations

import pytest

# conftest registers energy_manager.* without integration __init__
from energy_manager.const import (
    STRATEGY_FULL,
    STRATEGY_LOW,
    STRATEGY_MEDIUM,
    SYSTEM_MODE_EMERGENCY_SAVING,
    SYSTEM_MODE_NORMAL,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)
from energy_manager.engine.energy_model import EnergyModel
from energy_manager.engine.policy.arbiter import merge_policy
from energy_manager.engine.policy.emergency_advisor import evaluate_emergency
from energy_manager.engine.policy.forecast_strategy_advisor import (
    recommend_battery_strategy,
)


def _base_forecast_model() -> EnergyModel:
    m = EnergyModel(
        battery_soc=50.0,
        forecast_available=True,
        evening_margin_kwh=100.0,
        morning_floor_margin_kwh=5.0,
        sun_below_horizon=False,
        house_consumption_kw=1.0,
        forecast_next_hour_kwh=2.0,
        can_refill_tomorrow_to_full=True,
        can_drain_to_morning_floor=True,
    )
    m.battery_status = "medium"
    m.charge_state = "off"
    m.discharge_state = "on"
    return m


@pytest.mark.parametrize(
    ("soc_band", "charge", "strat", "expected_mode", "forecast_ok"),
    [
        ("very low", "off", STRATEGY_LOW, SYSTEM_MODE_EMERGENCY_SAVING, True),
        ("low", "off", STRATEGY_FULL, SYSTEM_MODE_SAVING, False),
        ("high", "off", STRATEGY_LOW, SYSTEM_MODE_WASTING, True),
        ("medium", "off", STRATEGY_MEDIUM, SYSTEM_MODE_NORMAL, True),
    ],
)
def test_merge_policy_soc_vs_strategy(
    soc_band: str,
    charge: str,
    strat: str,
    expected_mode: str,
    forecast_ok: bool,
) -> None:
    m = _base_forecast_model()
    m.forecast_available = forecast_ok
    m.battery_status = soc_band
    m.charge_state = charge
    if soc_band == "very low":
        m.battery_soc = 10.0
    elif soc_band == "low":
        m.battery_soc = 25.0
    elif soc_band == "high":
        m.battery_soc = 80.0
    out = merge_policy(
        m,
        strategy=strat,
        strategy_reason="test",
        charge_state_max_duration_minutes=0.0,
        discharge_just_entered_max=False,
    )
    assert out.system_mode == expected_mode


def test_max_charge_duration_forces_wasting() -> None:
    m = _base_forecast_model()
    m.battery_status = "low"
    m.charge_state = "max"
    out = merge_policy(
        m,
        strategy=STRATEGY_FULL,
        strategy_reason="test",
        charge_state_max_duration_minutes=5.0,
        discharge_just_entered_max=False,
    )
    assert out.system_mode == SYSTEM_MODE_WASTING
    assert "Max charging" in out.mode_reason


def test_discharge_max_suppresses_and_sheds_on_edge() -> None:
    m = _base_forecast_model()
    m.battery_status = "medium"
    m.charge_state = "off"
    m.discharge_state = "max"
    out = merge_policy(
        m,
        strategy=STRATEGY_LOW,
        strategy_reason="test",
        charge_state_max_duration_minutes=0.0,
        discharge_just_entered_max=True,
    )
    assert out.suppress_wasting_turn_ons is True
    assert out.force_shed_one_consumer is True
    assert out.system_mode == SYSTEM_MODE_WASTING


def test_discharge_max_sustained_suppress_only() -> None:
    m = _base_forecast_model()
    m.discharge_state = "max"
    out = merge_policy(
        m,
        strategy=STRATEGY_LOW,
        strategy_reason="test",
        charge_state_max_duration_minutes=0.0,
        discharge_just_entered_max=False,
    )
    assert out.suppress_wasting_turn_ons is True
    assert out.force_shed_one_consumer is False


def test_manual_mode_override() -> None:
    m = _base_forecast_model()
    out = merge_policy(
        m,
        strategy=STRATEGY_LOW,
        strategy_reason="test",
        charge_state_max_duration_minutes=0.0,
        manual_mode_override=True,
        manual_mode=SYSTEM_MODE_SAVING,
        manual_strategy_override=False,
        manual_strategy=None,
        discharge_just_entered_max=False,
    )
    assert out.system_mode == SYSTEM_MODE_SAVING
    assert out.mode_reason == "Manual mode"


def test_recommend_battery_strategy_evening_margin_negative() -> None:
    m = _base_forecast_model()
    m.forecast_available = True
    m.evening_margin_kwh = -1.0
    s, r = recommend_battery_strategy(m)
    assert s == STRATEGY_FULL
    assert "not reachable" in r


def test_evaluate_emergency_discharge_only() -> None:
    m = _base_forecast_model()
    m.discharge_state = "max"
    ev = evaluate_emergency(m, 0.0, discharge_just_entered_max=True)
    assert ev.mode_override is None
    assert ev.suppress_wasting_turn_ons is True
    assert ev.force_shed_one_consumer is True


def test_morning_pre_pv_drain_prefers_wasting_over_normal() -> None:
    """Below strategy with forecast OK, but still above morning floor and pre-PV → wasting."""
    m = _base_forecast_model()
    m.battery_soc = 28.0
    m.battery_status = "low"
    m.morning_target_percent = 20.0
    m.hours_until_first_pv = 2.0
    m.solar_production_kw = 0.0
    m.charge_state = "off"
    out = merge_policy(
        m,
        strategy=STRATEGY_FULL,
        strategy_reason="test",
        charge_state_max_duration_minutes=0.0,
        discharge_just_entered_max=False,
    )
    assert out.system_mode == SYSTEM_MODE_WASTING
    assert "Morning drain" in out.mode_reason


def test_morning_pre_pv_drain_skips_when_solar_already_significant() -> None:
    m = _base_forecast_model()
    m.battery_soc = 28.0
    m.battery_status = "low"
    m.morning_target_percent = 20.0
    m.hours_until_first_pv = 2.0
    m.solar_production_kw = 2.0
    m.charge_state = "off"
    out = merge_policy(
        m,
        strategy=STRATEGY_FULL,
        strategy_reason="test",
        charge_state_max_duration_minutes=0.0,
        discharge_just_entered_max=False,
    )
    assert out.system_mode == SYSTEM_MODE_NORMAL


def test_morning_pre_pv_drain_skips_when_near_morning_floor() -> None:
    m = _base_forecast_model()
    m.battery_soc = 22.0
    m.battery_status = "low"
    m.morning_target_percent = 20.0
    m.hours_until_first_pv = 2.0
    m.solar_production_kw = 0.0
    m.charge_state = "off"
    out = merge_policy(
        m,
        strategy=STRATEGY_FULL,
        strategy_reason="test",
        charge_state_max_duration_minutes=0.0,
        discharge_just_entered_max=False,
    )
    assert out.system_mode == SYSTEM_MODE_NORMAL
