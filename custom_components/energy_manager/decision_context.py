"""
Per-tick decision snapshot for ops logging (fixed schema, schema=2 compatible).
"""

from __future__ import annotations

from dataclasses import dataclass

LOG_VALUE_NA = "n/a"


@dataclass(frozen=True)
class DecisionContext:
    """Immutable snapshot: same keys in every ACTION/MODE/SYSTEM log line that carries it."""

    tick_id: str
    system_mode: str
    mode_reason: str
    strategy_recommendation: str
    strategy_reason: str
    battery_soc_percent: str
    forecast_available: str
    daily_margin_kwh: str
    evening_margin_kwh: str
    effective_budget_kw: str
    battery_discharge_kw: str
    discharge_ceiling_kw: str

    def to_flat_log_dict(self) -> dict[str, str]:
        return {
            "tick_id": self.tick_id,
            "system_mode": self.system_mode,
            "mode_reason": self.mode_reason,
            "strategy_recommendation": self.strategy_recommendation,
            "strategy_reason": self.strategy_reason,
            "battery_soc_percent": self.battery_soc_percent,
            "forecast_available": self.forecast_available,
            "daily_margin_kwh": self.daily_margin_kwh,
            "evening_margin_kwh": self.evening_margin_kwh,
            "effective_budget_kw": self.effective_budget_kw,
            "battery_discharge_kw": self.battery_discharge_kw,
            "discharge_ceiling_kw": self.discharge_ceiling_kw,
        }

    def merge_action_context(
        self,
        *,
        reason_code: str,
        entity_id: str | None = None,
        count: str | None = None,
    ) -> dict[str, str]:
        out = self.to_flat_log_dict()
        out["reason_code"] = reason_code
        if entity_id is not None:
            out["entity_id"] = entity_id
        if count is not None:
            out["count"] = count
        return out


def build_decision_context(
    tick_id: str,
    *,
    system_mode: str,
    mode_reason: str,
    strategy_recommendation: str,
    strategy_reason: str,
    battery_soc: float,
    forecast_available: bool,
    daily_margin_kwh: float,
    evening_margin_kwh: float,
    effective_budget_kw_wasting: float | None,
    battery_discharge_kw: float,
    discharge_ceiling_kw: float,
) -> DecisionContext:
    eff = (
        f"{round(effective_budget_kw_wasting, 3):g}"
        if effective_budget_kw_wasting is not None
        else LOG_VALUE_NA
    )
    return DecisionContext(
        tick_id=tick_id,
        system_mode=system_mode,
        mode_reason=mode_reason,
        strategy_recommendation=strategy_recommendation,
        strategy_reason=strategy_reason,
        battery_soc_percent=f"{round(float(battery_soc), 2):g}",
        forecast_available="true" if forecast_available else "false",
        daily_margin_kwh=f"{round(float(daily_margin_kwh), 3):g}",
        evening_margin_kwh=f"{round(float(evening_margin_kwh), 3):g}",
        effective_budget_kw=eff,
        battery_discharge_kw=f"{round(float(battery_discharge_kw), 3):g}",
        discharge_ceiling_kw=f"{round(float(discharge_ceiling_kw), 3):g}",
    )
