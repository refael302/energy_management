"""
Energy model – derived values from CONFIG and sensor readings.
Replicates YAML template sensors: battery status, headroom, margin, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..const import (
    BASELINE_PROFILE_BOOTSTRAP_KW,
    BATTERY_SOC_VERY_LOW_PERCENT,
    EMERGENCY_RESERVE_PLANNING_PERCENT,
    NIGHT_BRIDGE_HOURS_BEFORE_SUNRISE,
    NIGHT_BRIDGE_SOLAR_SENSOR_THRESHOLD_KW,
)
from .baseline_integrals import kwh_forward_hours, kwh_over_clock_interval


@dataclass
class EnergyModel:
    """Holds current energy state and derived values (from YAML CONFIG + templates)."""

    # Raw from sensors (or coordinator)
    battery_soc: float = 0.0
    battery_power_kw: float = 0.0
    battery_current: float | None = None
    solar_production_kw: float = 0.0
    house_consumption_kw: float = 0.0

    # Config (from entry)
    battery_capacity_kwh: float = 20.0
    eod_battery_target_percent: float = 90.0
    emergency_reserve_percent: float = EMERGENCY_RESERVE_PLANNING_PERCENT
    safety_forecast_factor_percent: float = 90.0
    max_battery_current_amps: float = 36.0
    discharge_limit_percent: float = 80.0
    discharge_limit_deadband_percent: float = 5.0

    # Forecast inputs (from forecast engine)
    forecast_next_hour_kwh: float = 0.0
    forecast_today_remaining_kwh: float = 0.0
    forecast_available: bool = True

    # Time until end of day (hours)
    hours_until_eod: float = 0.0
    # Night bridge inputs (set by coordinator before update_derived)
    hours_until_sunrise: float = 999.0
    sun_below_horizon: bool = True
    forecast_tomorrow_kwh: float = 0.0
    hours_until_first_pv: float = 0.0

    # --- Derived (computed) ---
    battery_status: str = "medium"
    charge_state: str = "off"
    discharge_state: str = "off"
    discharge_under_limit: bool = False
    consumption_till_eod_kwh: float = 0.0
    battery_charge_headroom_kwh: float = 0.0
    emergency_reserve_kwh: float = 0.0
    needed_energy_today_kwh: float = 0.0
    pv_remaining_today_safe_kwh: float = 0.0
    daily_margin_kwh: float = 0.0
    night_bridge_relaxed: bool = False
    night_bridge_tomorrow_ok: bool = False
    night_bridge_energy_need_kwh: float = 0.0
    night_bridge_usable_kwh: float = 0.0

    # Learned hourly baseline (kW per clock hour 0–23); set by coordinator each tick
    baseline_hourly_kw: list[float] = field(default_factory=lambda: [BASELINE_PROFILE_BOOTSTRAP_KW] * 24)

    def update_derived(self, now_local: datetime | None = None) -> None:
        """Update all derived fields from current raw and config values."""
        self._battery_status()
        self._charge_discharge_states()
        self._consumption_and_headroom(now_local)
        self._night_bridge(now_local)

    def _battery_status(self) -> None:
        if self.battery_soc < BATTERY_SOC_VERY_LOW_PERCENT:
            self.battery_status = "very low"
        elif self.battery_soc < 30:
            self.battery_status = "low"
        elif self.battery_soc < 70:
            self.battery_status = "medium"
        elif self.battery_soc < 95:
            self.battery_status = "high"
        else:
            self.battery_status = "full"

    def _charge_discharge_states(self) -> None:
        c = self.battery_current
        m = self.max_battery_current_amps
        pct = self.discharge_limit_percent
        db = self.discharge_limit_deadband_percent
        thr_discharge = m * pct / 100
        thr_under = m * (pct - db) / 100

        if c is None:
            self.charge_state = "off"
            self.discharge_state = "off"
            self.discharge_under_limit = False
            return
        if c <= -m:
            self.charge_state = "max"
        elif c < 0:
            self.charge_state = "on"
        else:
            self.charge_state = "off"

        if c <= 0:
            self.discharge_state = "off"
        elif c >= thr_discharge:
            self.discharge_state = "max"
        else:
            self.discharge_state = "on"

        self.discharge_under_limit = 0 < c < thr_under

    def _consumption_and_headroom(self, now_local: datetime | None) -> None:
        # Baseline integral until local calendar midnight (distinct from hours_until_eod / sunset).
        if now_local is not None and len(self.baseline_hourly_kw) == 24:
            next_midnight = now_local.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            self.consumption_till_eod_kwh = round(
                kwh_over_clock_interval(
                    self.baseline_hourly_kw, now_local, next_midnight
                ),
                2,
            )
        else:
            self.consumption_till_eod_kwh = 0.0
        diff = self.eod_battery_target_percent - self.battery_soc
        self.battery_charge_headroom_kwh = round(
            max(0, diff / 100 * self.battery_capacity_kwh), 2
        )
        self.emergency_reserve_kwh = round(
            self.battery_capacity_kwh * self.emergency_reserve_percent / 100, 2
        )
        self.needed_energy_today_kwh = round(
            self.consumption_till_eod_kwh
            + self.battery_charge_headroom_kwh
            + self.emergency_reserve_kwh,
            2,
        )
        if self.forecast_available:
            self.pv_remaining_today_safe_kwh = round(
                self.forecast_today_remaining_kwh * self.safety_forecast_factor_percent / 100, 2
            )
            self.daily_margin_kwh = round(
                self.pv_remaining_today_safe_kwh - self.needed_energy_today_kwh, 2
            )
        else:
            self.pv_remaining_today_safe_kwh = 0.0
            self.daily_margin_kwh = -1.0  # conservative: assume no PV headroom

    def _night_bridge(self, now_local: datetime | None) -> None:
        """Relax next-hour PV check near sunrise when battery can last until forecast PV and tomorrow looks safe."""
        self.night_bridge_relaxed = False
        self.night_bridge_tomorrow_ok = False
        self.night_bridge_energy_need_kwh = 0.0
        self.night_bridge_usable_kwh = 0.0
        if not self.forecast_available:
            return
        pv_tomorrow_safe = round(
            self.forecast_tomorrow_kwh * self.safety_forecast_factor_percent / 100.0,
            2,
        )
        charge_from_floor_kwh = round(
            max(
                0.0,
                (self.eod_battery_target_percent - self.emergency_reserve_percent)
                / 100.0
                * self.battery_capacity_kwh,
            ),
            2,
        )
        if now_local is not None and len(self.baseline_hourly_kw) == 24:
            day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            next_day_start = day_start + timedelta(days=1)
            tomorrow_load_kwh = round(
                kwh_over_clock_interval(
                    self.baseline_hourly_kw, day_start, next_day_start
                ),
                2,
            )
            self.night_bridge_energy_need_kwh = round(
                kwh_forward_hours(
                    self.baseline_hourly_kw,
                    now_local,
                    self.hours_until_first_pv,
                ),
                2,
            )
        else:
            tomorrow_load_kwh = 0.0
            self.night_bridge_energy_need_kwh = 0.0
        self.night_bridge_tomorrow_ok = pv_tomorrow_safe >= (
            charge_from_floor_kwh + tomorrow_load_kwh
        )
        self.night_bridge_usable_kwh = round(
            max(
                0.0,
                (self.battery_soc - self.emergency_reserve_percent)
                / 100.0
                * self.battery_capacity_kwh,
            ),
            2,
        )
        window = (
            0.0 < self.hours_until_sunrise <= NIGHT_BRIDGE_HOURS_BEFORE_SUNRISE
        )
        dark = self.sun_below_horizon and (
            self.solar_production_kw < NIGHT_BRIDGE_SOLAR_SENSOR_THRESHOLD_KW
        )
        self.night_bridge_relaxed = (
            window
            and dark
            and self.night_bridge_tomorrow_ok
            and self.daily_margin_kwh >= 0.0
            and self.night_bridge_usable_kwh >= self.night_bridge_energy_need_kwh
        )

    battery_strategy_recommendation: str = "full"

    def set_strategy_recommendation(self, rec: str) -> None:
        """Set strategy (from decision engine)."""
        self.battery_strategy_recommendation = rec
