"""
Consumer load budget (kW): combine instantaneous sensors, daily margin, night bridge,
and battery discharge headroom (fixed fraction of max discharge kW). Pure functions + hysteresis + greedy selection.

Instant surplus (v1):
  charge_kw = max(0, -battery_power_kw)  # negative battery power = charging (HA convention)
  a = max(0, solar_production_kw - house_consumption_kw - charge_kw)
       → PV not absorbed by house or battery charge (export / unused production proxy)
  When inverter_size_kw > 0 also add:
  b = max(0, inverter_size_kw - solar_production_kw)
       → unused DC→AC / stack headroom so extra AC load can absorb production (user story: 15 kW cap, 10 kW producing → +5 kW room)
  instant_kw = a + b when inverter set, else a only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ..const import (
    CONSUMER_BUDGET_MARGIN_HIGH_CAP_KW,
    CONSUMER_BUDGET_MARGIN_LARGE_CAP_KW,
    CONSUMER_BUDGET_MARGIN_MEDIUM_CAP_KW,
    CONSUMER_BUDGET_MARGIN_NEG_CAP_KW,
    CONSUMER_DISCHARGE_HEADROOM_SAFETY_KW,
    CONSUMER_UNLEARNED_ASSUMED_KW,
    DISCHARGE_HEADROOM_FRACTION,
    MIN_EFFECTIVE_MAX_BATTERY_POWER_KW,
    MARGIN_HIGH_THRESHOLD,
    MARGIN_MEDIUM_MAX,
)

from .battery_horizon import compute_battery_edge_horizons

if TYPE_CHECKING:
    from .energy_model import EnergyModel

_BATTERY_LOAD_MARGIN = 0.05


@dataclass
class ConsumerBudgetCeilings:
    """Per-ceiling breakdown for diagnostics (kW, all >= 0)."""

    instant_kw: float
    strategic_kw: float
    night_spread_kw: float
    discharge_kw: float


def compute_instant_surplus_kw(
    solar_production_kw: float,
    house_consumption_kw: float,
    battery_power_kw: float,
    inverter_size_kw: float,
) -> float:
    """
    Estimate kW that can be diverted to additional household consumers without relying
    on new PV physics — export-like surplus plus optional inverter headroom.

    battery_power_kw: positive = discharge, negative = charge (see Energy Manager sensors).
    """
    charge_kw = max(0.0, -battery_power_kw)
    balance = solar_production_kw - house_consumption_kw - charge_kw
    a = max(0.0, balance)
    if inverter_size_kw and inverter_size_kw > 0:
        b = max(0.0, inverter_size_kw - solar_production_kw)
        return a + b
    return a


def strategic_waste_cap_kw(model: EnergyModel) -> float:
    """Tighter cap when daily margin is small; 0 when EOD target unreachable."""
    if not getattr(model, "forecast_available", True):
        return CONSUMER_BUDGET_MARGIN_HIGH_CAP_KW
    margin = float(getattr(model, "daily_margin_kwh", -1.0))
    if margin < 0:
        return CONSUMER_BUDGET_MARGIN_NEG_CAP_KW
    if margin <= MARGIN_HIGH_THRESHOLD:
        return CONSUMER_BUDGET_MARGIN_HIGH_CAP_KW
    if margin <= MARGIN_MEDIUM_MAX:
        return CONSUMER_BUDGET_MARGIN_MEDIUM_CAP_KW
    return CONSUMER_BUDGET_MARGIN_LARGE_CAP_KW


def night_spread_cap_kw(model: EnergyModel) -> float:
    """
    Average kW to spread night_bridge usable energy until first PV, when night bridge is relaxed.
    """
    if not getattr(model, "night_bridge_relaxed", False):
        return CONSUMER_BUDGET_MARGIN_LARGE_CAP_KW
    usable = float(getattr(model, "night_bridge_usable_kwh", 0.0))
    hours = float(getattr(model, "hours_until_first_pv", 0.0))
    hours = max(hours, 0.25)
    return max(0.0, usable / hours)


def _battery_discharge_headroom_kw(model: EnergyModel) -> float:
    """
    kW margin before hitting operational discharge ceiling (max kW × (1 - headroom)).
    When not discharging, returns a large cap (not binding).
    """
    discharge_kw = max(0.0, model.battery_power_kw)
    if discharge_kw <= 0.01:
        return CONSUMER_BUDGET_MARGIN_LARGE_CAP_KW

    m_kw = max(MIN_EFFECTIVE_MAX_BATTERY_POWER_KW, float(model.max_battery_discharge_kw))
    operational_ceiling_kw = m_kw * (1.0 - DISCHARGE_HEADROOM_FRACTION)
    if operational_ceiling_kw <= 0:
        return CONSUMER_BUDGET_MARGIN_LARGE_CAP_KW

    return max(0.0, operational_ceiling_kw - discharge_kw)


def marginal_battery_load_fraction(
    solar_production_kw: float,
    house_consumption_kw: float,
) -> float:
    """
    Fraction of each additional kW of consumer load expected to come from battery discharge
    when PV is not already covering house (conservative 0..1).

    Note: this is the *current* snapshot. For turn-on gating prefer
    ``battery_load_delta_kw`` / ``projected_discharge_kw`` which evaluate house+extra.
    """
    if solar_production_kw + 0.05 >= house_consumption_kw:
        return 0.0
    return 1.0


def battery_load_delta_kw(
    solar_production_kw: float,
    house_consumption_kw: float,
    extra_load_kw: float,
) -> float:
    """
    Increase in battery-served house load (kW) after adding extra_load_kw to the house.

    If PV still covers house+extra → 0. If PV already short → full extra.
    If PV covers only part of the extra → only the overflow hits the battery.
    """
    extra = max(0.0, float(extra_load_kw))
    if extra <= 1e-9:
        return 0.0
    solar = max(0.0, float(solar_production_kw))
    house = max(0.0, float(house_consumption_kw))
    before = max(0.0, house - solar)
    after = max(0.0, house + extra - solar)
    return max(0.0, after - before)


def operational_discharge_ceiling_kw(max_battery_discharge_kw: float) -> float:
    """Operational discharge ceiling (kW): max × (1 - headroom fraction)."""
    m_kw = max(MIN_EFFECTIVE_MAX_BATTERY_POWER_KW, float(max_battery_discharge_kw))
    return max(0.0, m_kw * (1.0 - DISCHARGE_HEADROOM_FRACTION))


def projected_discharge_kw(
    *,
    solar_production_kw: float,
    house_consumption_kw: float,
    battery_discharge_kw: float,
    extra_load_kw: float,
) -> float:
    """Estimated battery discharge kW after adding extra_load not yet in the house reading."""
    delta = battery_load_delta_kw(
        solar_production_kw, house_consumption_kw, extra_load_kw
    )
    return max(0.0, float(battery_discharge_kw)) + delta


def fits_discharge_ceiling_after_extra(
    *,
    solar_production_kw: float,
    house_consumption_kw: float,
    battery_discharge_kw: float,
    max_battery_discharge_kw: float,
    extra_load_kw: float,
    safety_kw: float | None = None,
) -> bool:
    """True if projected discharge after extra_load stays within operational ceiling + safety."""
    safety = (
        max(0.0, float(CONSUMER_DISCHARGE_HEADROOM_SAFETY_KW))
        if safety_kw is None
        else max(0.0, float(safety_kw))
    )
    ceiling = operational_discharge_ceiling_kw(max_battery_discharge_kw)
    projected = projected_discharge_kw(
        solar_production_kw=solar_production_kw,
        house_consumption_kw=house_consumption_kw,
        battery_discharge_kw=battery_discharge_kw,
        extra_load_kw=extra_load_kw,
    )
    return projected + safety - ceiling <= 1e-6


def compute_raw_budget_kw(
    model: EnergyModel,
    inverter_size_kw: float,
) -> ConsumerBudgetCeilings:
    """Compose ceiling components; caller takes min(...) for raw budget."""
    instant = compute_instant_surplus_kw(
        model.solar_production_kw,
        model.house_consumption_kw,
        model.battery_power_kw,
        inverter_size_kw,
    )
    strategic = strategic_waste_cap_kw(model)
    night_sp = night_spread_cap_kw(model)
    discharge = _battery_discharge_headroom_kw(model)
    return ConsumerBudgetCeilings(
        instant_kw=round(instant, 3),
        strategic_kw=round(strategic, 3),
        night_spread_kw=round(night_sp, 3),
        discharge_kw=round(discharge, 3),
    )


def compose_raw_budget_kw(
    ceilings: ConsumerBudgetCeilings,
    *,
    marginal_battery_per_kw: float,
    battery_discharging_kw: float,
) -> float:
    """
    Take min of instant, strategic, night spread, and (if relevant) discharge ceiling.
    Discharge ceiling is ignored (non-binding) when extra load is expected to be served
    from PV (marginal_battery ~ 0) and battery is not discharging.
    """
    use_discharge = (
        marginal_battery_per_kw > _BATTERY_LOAD_MARGIN
        or battery_discharging_kw > 0.05
    )
    d = ceilings.discharge_kw if use_discharge else CONSUMER_BUDGET_MARGIN_LARGE_CAP_KW
    return max(
        0.0,
        min(
            ceilings.instant_kw,
            ceilings.strategic_kw,
            ceilings.night_spread_kw,
            d,
        ),
    )


def apply_hysteresis(
    raw_budget_kw: float,
    locked_budget_kw: float | None,
    hysteresis_ratio: float,
    *,
    epsilon_kw: float = 0.05,
) -> tuple[float, bool]:
    """
    Return (budget_to_use, did_update_lock).
    If locked is None, always adopt raw. Else keep locked unless relative change >= ratio.
    """
    hyst = max(0.01, min(0.95, hysteresis_ratio))
    if locked_budget_kw is None:
        return max(0.0, raw_budget_kw), True
    locked = max(0.0, locked_budget_kw)
    raw = max(0.0, raw_budget_kw)
    denom = max(locked, epsilon_kw)
    if abs(raw - locked) / denom >= hyst:
        return raw, True
    return locked, False


def select_learned_consumers(
    consumers_ordered: list[str],
    learned_kw: dict[str, float],
    budget_kw: float,
    discharge_headroom_kw: float,
    marginal_battery_per_kw: float,
    *,
    solar_production_kw: float | None = None,
    house_consumption_kw: float | None = None,
    battery_discharge_kw: float | None = None,
    max_battery_discharge_kw: float | None = None,
    currently_on: set[str] | frozenset[str] | None = None,
) -> set[str]:
    """
    Greedy by priority order: add consumer if sum learned_kw <= budget and discharge path allows.

    When solar/house/max_discharge are provided, gate on *projected* discharge after the
    new load (house+extra), not only the current marginal snapshot (which is 0 whenever
    PV covers the house *before* the consumer turns on).

    Legacy path (no solar/house): ``(total * marginal) + safety <= discharge_headroom``.
    """
    selected: set[str] = set()
    total_learned = 0.0
    budget = max(0.0, budget_kw)
    d_head = max(0.0, discharge_headroom_kw)
    m = max(0.0, min(1.0, marginal_battery_per_kw))
    on = set(currently_on or ())
    use_projected = (
        solar_production_kw is not None
        and house_consumption_kw is not None
        and battery_discharge_kw is not None
        and max_battery_discharge_kw is not None
    )

    safety = max(0.0, float(CONSUMER_DISCHARGE_HEADROOM_SAFETY_KW))
    for eid in consumers_ordered:
        kw = learned_kw.get(eid)
        if kw is None or eid not in learned_kw:
            continue
        if total_learned + kw - budget > 1e-6:
            continue
        if use_projected:
            tentative = selected | {eid}
            extra_new = sum(
                float(learned_kw[e]) for e in tentative if e not in on and e in learned_kw
            )
            if not fits_discharge_ceiling_after_extra(
                solar_production_kw=float(solar_production_kw),
                house_consumption_kw=float(house_consumption_kw),
                battery_discharge_kw=float(battery_discharge_kw),
                max_battery_discharge_kw=float(max_battery_discharge_kw),
                extra_load_kw=extra_new,
                safety_kw=safety,
            ):
                continue
        else:
            load_on_battery = (total_learned + kw) * m
            if load_on_battery + safety - d_head > 1e-6:
                continue
        selected.add(eid)
        total_learned += kw

    return selected


def next_unlearned_for_sampling(
    consumers_ordered: list[str],
    learned_kw: dict[str, float],
    on_targets: set[str],
    *,
    discharge_headroom_kw: float,
    marginal_battery_per_kw: float,
    min_headroom_for_unknown_kw: float = CONSUMER_UNLEARNED_ASSUMED_KW,
    solar_production_kw: float | None = None,
    house_consumption_kw: float | None = None,
    battery_discharge_kw: float | None = None,
    max_battery_discharge_kw: float | None = None,
    currently_on: set[str] | frozenset[str] | None = None,
    pending_extra_kw: float = 0.0,
) -> str | None:
    """
    First (priority) consumer that is off, not learned, not already targeted for turn-on.
    Skip if projected discharge after assumed unknown load would breach the ceiling
    (or, legacy: headroom below min when already on battery).
    """
    use_projected = (
        solar_production_kw is not None
        and house_consumption_kw is not None
        and battery_discharge_kw is not None
        and max_battery_discharge_kw is not None
    )
    if use_projected:
        # pending_extra: learned targets not yet on; assumed kw for the unlearned probe.
        extra = max(0.0, float(pending_extra_kw)) + max(
            0.0, float(min_headroom_for_unknown_kw)
        )
        if not fits_discharge_ceiling_after_extra(
            solar_production_kw=float(solar_production_kw),
            house_consumption_kw=float(house_consumption_kw),
            battery_discharge_kw=float(battery_discharge_kw),
            max_battery_discharge_kw=float(max_battery_discharge_kw),
            extra_load_kw=extra,
        ):
            return None
    else:
        m = max(0.0, min(1.0, marginal_battery_per_kw))
        if m >= 0.99 and discharge_headroom_kw < min_headroom_for_unknown_kw:
            return None
    for eid in consumers_ordered:
        if eid in learned_kw:
            continue
        if eid in on_targets:
            continue
        if use_projected and eid in set(currently_on or ()):
            continue
        return eid
    return None


def trim_learned_consumers_for_very_low_horizon(
    selected: set[str],
    consumers_ordered: list[str],
    learned_kw: dict[str, float],
    marginal_battery_per_kw: float,
    *,
    now_local: datetime,
    soc_percent: float,
    capacity_kwh: float,
    very_low_percent: float,
    target_full_percent: float,
    max_charge_kw: float,
    max_discharge_kw: float,
    baseline_hourly_kw: list[float],
    pv_kw_slots: list[float],
    time_iso_slots: list[str],
    hours_until_first_pv: float,
    solar_production_kw: float | None = None,
    house_consumption_kw: float | None = None,
    currently_on: set[str] | frozenset[str] | None = None,
) -> set[str]:
    """
    Drop lowest-priority selected consumers until PV+baseline+extra projection does not
    cross very_low within the hourly forecast horizon (or until a simple kWh fallback passes).

    When solar/house are provided, battery-served extra load uses projected overflow
    (house+new consumers − PV), not only the current marginal snapshot.
    """
    m = max(0.0, min(1.0, marginal_battery_per_kw))
    use_projected = solar_production_kw is not None and house_consumption_kw is not None
    on = set(currently_on or ())

    ordered_sel = [eid for eid in consumers_ordered if eid in selected]
    if not ordered_sel:
        return set()

    def _battery_extra_kw(eids: list[str]) -> float:
        if use_projected:
            extra_new = sum(
                float(learned_kw.get(eid, 0.0)) for eid in eids if eid not in on
            )
            return battery_load_delta_kw(
                float(solar_production_kw),
                float(house_consumption_kw),
                extra_new,
            )
        return sum(learned_kw.get(eid, 0.0) for eid in eids) * m

    # No battery impact projected and current marginal says PV covers house → keep set.
    if _battery_extra_kw(ordered_sel) < _BATTERY_LOAD_MARGIN and m < _BATTERY_LOAD_MARGIN:
        return set(selected)

    forecast_ok = (
        len(pv_kw_slots) >= 1
        and len(pv_kw_slots) == len(time_iso_slots)
        and capacity_kwh > 0
    )

    while ordered_sel:
        total_kw = _battery_extra_kw(ordered_sel)
        if total_kw < _BATTERY_LOAD_MARGIN:
            break
        safe = False
        if forecast_ok:
            _, to_vl = compute_battery_edge_horizons(
                now_local=now_local,
                soc_percent=soc_percent,
                capacity_kwh=capacity_kwh,
                max_charge_kw=max_charge_kw,
                max_discharge_kw=max_discharge_kw,
                pv_kw_slots=pv_kw_slots,
                time_iso_slots=time_iso_slots,
                baseline_hourly_kw=baseline_hourly_kw,
                target_full_percent=target_full_percent,
                target_very_low_percent=very_low_percent,
                extra_house_load_kw=total_kw,
            )
            safe = to_vl.hours_until is None
        else:
            h = max(0.5, float(hours_until_first_pv or 12.0))
            usable = max(
                0.0,
                (soc_percent - very_low_percent) / 100.0 * capacity_kwh,
            )
            safe = total_kw * h <= usable * 0.95
        if safe:
            break
        ordered_sel.pop()

    return set(ordered_sel)
