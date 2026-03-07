"""
Energy model – derived values from CONFIG and sensor readings.
Replicates YAML template sensors: battery status, headroom, margin, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    baseline_consumption_kw: float = 0.8
    eod_battery_target_percent: float = 90.0
    emergency_reserve_percent: float = 20.0
    safety_forecast_factor_percent: float = 90.0
    max_battery_current_amps: float = 36.0
    discharge_limit_percent: float = 80.0
    discharge_limit_deadband_percent: float = 5.0

    # Forecast inputs (from forecast engine)
    forecast_next_hour_kwh: float = 0.0
    forecast_today_remaining_kwh: float = 0.0

    # Time until end of day (hours)
    hours_until_eod: float = 0.0

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
    can_turn_on_heavy_consumer: bool = False
    can_waste_energy: bool = False

    def update_derived(self) -> None:
        """Update all derived fields from current raw and config values."""
        self._battery_status()
        self._charge_discharge_states()
        self._consumption_and_headroom()
        self._can_turn_on_heavy_consumer()
        self._can_waste_energy()

    def _battery_status(self) -> None:
        if self.battery_soc < 15:
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

    def _consumption_and_headroom(self) -> None:
        self.consumption_till_eod_kwh = round(
            self.baseline_consumption_kw * self.hours_until_eod, 2
        )
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
        self.pv_remaining_today_safe_kwh = round(
            self.forecast_today_remaining_kwh * self.safety_forecast_factor_percent / 100, 2
        )
        self.daily_margin_kwh = round(
            self.pv_remaining_today_safe_kwh - self.needed_energy_today_kwh, 2
        )

    def _can_turn_on_heavy_consumer(self) -> None:
        soc_energy = self.battery_soc / 100 * self.battery_capacity_kwh
        available = soc_energy + self.forecast_next_hour_kwh - self.house_consumption_kw
        self.can_turn_on_heavy_consumer = (
            self.daily_margin_kwh > 0 and available > 0
        )

    def _can_waste_energy(self) -> None:
        levels = {"very low": 0, "low": 1, "medium": 2, "high": 3, "full": 4}
        min_level = {"low": 1, "medium": 2, "high": 3, "full": 4}
        cur = levels.get(self.battery_status, 0)
        req = min_level.get(self.battery_strategy_recommendation, 4)
        self.can_waste_energy = cur > req

    battery_strategy_recommendation: str = "full"

    def set_strategy_recommendation(self, rec: str) -> None:
        """Set strategy (from decision engine) and recompute can_waste_energy."""
        self.battery_strategy_recommendation = rec
        self._can_waste_energy()
