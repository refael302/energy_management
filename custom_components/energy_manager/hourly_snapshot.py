"""
Readable multi-line strings for the hourly ops log (each line fits INTEGRATION_LOG_SUMMARY_MAX_LEN).
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import INTEGRATION_LOG_SUMMARY_MAX_LEN


def _short_entity_label(entity_id: str) -> str:
    if not entity_id:
        return ""
    if "." in entity_id:
        return entity_id.split(".", 1)[1]
    return entity_id


def _entity_state(hass: HomeAssistant, entity_id: str | None) -> str:
    if not entity_id:
        return "n/a"
    st = hass.states.get(entity_id)
    if st is None:
        return "missing"
    raw = st.state
    if raw in ("unknown", "unavailable", ""):
        return raw or "empty"
    return str(raw)[:40]


def _fmt_num(v: Any, decimals: int = 3) -> str:
    if v is None:
        return "n/a"
    try:
        f = float(v)
        s = f"{f:.{decimals}f}"
        return s.rstrip("0").rstrip(".") or "0"
    except (TypeError, ValueError):
        return str(v)[:30]


def _fmt_learned_kw(m: dict[str, Any] | None, max_pairs: int = 8) -> str:
    if not m:
        return "none"
    items: list[str] = []
    for k, v in sorted(m.items(), key=lambda x: x[0]):
        lab = _short_entity_label(str(k))
        items.append(f"{lab}={_fmt_num(v, 2)}")
        if len(items) >= max_pairs:
            items.append("…")
            break
    return " ".join(items)


def _trunc(s: Any, n: int = 90) -> str:
    t = str(s).replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def build_hourly_snapshot_lines(
    hass: HomeAssistant,
    data: dict[str, Any],
    entity_ids: dict[str, str | None],
) -> list[str]:
    """Return human-readable log lines; each line <= INTEGRATION_LOG_SUMMARY_MAX_LEN."""
    mlen = INTEGRATION_LOG_SUMMARY_MAX_LEN
    d = data
    lines: list[str] = []

    soc_e = entity_ids.get("battery_soc")
    pwr_e = entity_ids.get("battery_power")
    sol_e = entity_ids.get("solar")
    house_e = entity_ids.get("house")

    lines.append(
        "[Hourly snapshot] "
        f"soc%={_fmt_num(d.get('battery_soc'), 2)} "
        f"bat_kW={_fmt_num(d.get('battery_power_kw'))} "
        f"solar_kW={_fmt_num(d.get('solar_production_kw'))} "
        f"house_kW={_fmt_num(d.get('house_consumption_kw'))}"
    )
    lines.append(
        "[Sensors] "
        f"soc_entity={_short_entity_label(soc_e or '')} state={_entity_state(hass, soc_e)} | "
        f"bat_pwr={_short_entity_label(pwr_e or '')} state={_entity_state(hass, pwr_e)}"
    )
    lines.append(
        "[Sensors] "
        f"solar={_short_entity_label(sol_e or '')} state={_entity_state(hass, sol_e)} | "
        f"house={_short_entity_label(house_e or '')} state={_entity_state(hass, house_e)}"
    )
    lines.append(
        "[Mode] "
        f"system_mode={d.get('energy_manager_mode')} | "
        f"strategy={d.get('strategy_recommendation')} | "
        f"battery_reserve={d.get('battery_reserve_state')}"
    )
    lines.append(
        "[Reasons] "
        f"mode_reason={_trunc(d.get('mode_reason'), 85)} | "
        f"strategy_reason={_trunc(d.get('strategy_reason'), 85)}"
    )
    lines.append(
        "[Forecast] "
        f"available={d.get('forecast_available')} from_cache={d.get('forecast_from_cache')} | "
        f"next_h_kWh={_fmt_num(d.get('forecast_next_hour_kwh'))} "
        f"today_rem_kWh={_fmt_num(d.get('forecast_today_remaining_kwh'))} "
        f"tomorrow_kWh={_fmt_num(d.get('forecast_tomorrow_kwh'))} "
        f"cur_pv_kW={_fmt_num(d.get('forecast_current_power_kw'))}"
    )
    lines.append(
        "[Battery UI] "
        f"power_state={d.get('battery_power_state')} | "
        f"charge={d.get('charge_state')} discharge={d.get('discharge_state')}"
    )
    lines.append(
        "[Time] "
        f"h_eod={_fmt_num(d.get('hours_until_eod'))} "
        f"h_sunrise={_fmt_num(d.get('hours_until_sunrise'))} "
        f"h_first_pv={_fmt_num(d.get('hours_until_first_pv'))}"
    )
    lines.append(
        "[Margins] "
        f"daily_margin_kWh={_fmt_num(d.get('daily_margin_kwh'))} "
        f"evening_margin_kWh={_fmt_num(d.get('evening_margin_kwh'))} "
        f"morning_margin_kWh={_fmt_num(d.get('morning_floor_margin_kwh'))}"
    )
    lines.append(
        "[Targets] "
        f"evening%={_fmt_num(d.get('evening_target_percent'), 1)} "
        f"morning%={_fmt_num(d.get('morning_target_percent'), 1)} | "
        f"need_evening_kWh={_fmt_num(d.get('needed_to_evening_full_kwh'))} "
        f"need_morning_kWh={_fmt_num(d.get('needed_to_morning_floor_kwh'))}"
    )
    lines.append(
        "[Headroom checks] "
        f"pv_evening_safe_kWh={_fmt_num(d.get('pv_to_evening_safe_kwh'))} "
        f"drain_ok={d.get('can_drain_to_morning_floor')} "
        f"refill_ok={d.get('can_refill_tomorrow_to_full')}"
    )
    lines.append(
        "[Baseline windows] "
        f"to_sunset_kWh={_fmt_num(d.get('baseline_to_sunset_kwh'))} "
        f"to_first_pv_kWh={_fmt_num(d.get('baseline_to_first_pv_kwh'))}"
    )
    lines.append(
        "[Night bridge] "
        f"relaxed={d.get('night_bridge_relaxed')} tomorrow_ok={d.get('night_bridge_tomorrow_ok')} | "
        f"need_kWh={_fmt_num(d.get('night_bridge_energy_need_kwh'))} "
        f"usable_kWh={_fmt_num(d.get('night_bridge_usable_kwh'))}"
    )
    bh_n = len(d.get("battery_horizon_hourly") or [])
    lines.append(
        "[Runtime] "
        f"to_empty_hhmm={d.get('battery_runtime_hhmm')} "
        f"to_full_hhmm={d.get('battery_time_to_full_hhmm')} | "
        f"horizon={d.get('battery_horizon_method')} hourly_steps={bh_n}"
    )
    lines.append(
        "[Horizon edges] "
        f"full_iso={_trunc(d.get('battery_horizon_to_full_edge_iso'), 42)} | "
        f"very_low_iso={_trunc(d.get('battery_horizon_to_very_low_edge_iso'), 42)}"
    )
    tgt = d.get("consumer_learned_target_ids") or []
    if not isinstance(tgt, list):
        tgt = []
    tgt_s = ",".join(_short_entity_label(str(x)) for x in tgt[:12])
    if len(tgt) > 12:
        tgt_s += ",…"
    lines.append(
        "[Consumers] "
        f"on={d.get('consumers_on_count')}/{d.get('consumers_total')} | "
        f"learned_target=[{tgt_s}]"
    )
    ceil = d.get("consumer_budget_ceilings")
    if isinstance(ceil, dict):
        lines.append(
            "[Wasting budget] "
            f"raw_kW={_fmt_num(d.get('consumer_budget_raw_kw'))} "
            f"locked_kW={_fmt_num(d.get('consumer_budget_locked_kw'))} "
            f"eff_kW={_fmt_num(d.get('consumer_budget_effective_kw'))} | "
            f"ceil_inst={_fmt_num(ceil.get('instant_kw'))} "
            f"strat={_fmt_num(ceil.get('strategic_kw'))} "
            f"disch={_fmt_num(ceil.get('discharge_kw'))}"
        )
    else:
        lines.append(
            "[Wasting budget] "
            f"raw_kW={_fmt_num(d.get('consumer_budget_raw_kw'))} "
            f"locked_kW={_fmt_num(d.get('consumer_budget_locked_kw'))} "
            f"eff_kW={_fmt_num(d.get('consumer_budget_effective_kw'))} (not wasting / n/a)"
        )
    lines.append(
        "[Learned kW by consumer] " + _fmt_learned_kw(d.get("consumer_learned_kw"))
    )
    lines.append(
        "[Learn pending] "
        f"samples={_trunc(d.get('consumer_learn_pending_samples'), 100)} | "
        f"pending_kw={_trunc(d.get('consumer_learn_pending_kw'), 100)}"
    )
    lines.append(
        "[Baseline] "
        f"est_daily_kWh={_fmt_num(d.get('baseline_estimated_daily_kwh'))} "
        f"days={d.get('baseline_completed_days')} "
        f"hour_fc_kW={_fmt_num(d.get('baseline_forecast_kw'))} "
        f"sampled={d.get('baseline_sample_recorded')}"
    )
    lines.append(
        "[Battery peaks] "
        f"learn_d_kW={_fmt_num(d.get('battery_learned_max_discharge_kw'))} "
        f"learn_c_kW={_fmt_num(d.get('battery_learned_max_charge_kw'))} | "
        f"eff_d_kW={_fmt_num(d.get('battery_effective_max_discharge_kw'))} "
        f"eff_c_kW={_fmt_num(d.get('battery_effective_max_charge_kw'))} "
        f"state={d.get('battery_peak_learn_state')} ticks={d.get('battery_peak_sample_ticks')}"
    )

    out: list[str] = []
    for raw in lines:
        text = raw.replace("\n", " ").strip()
        start = 0
        while start < len(text):
            out.append(text[start : start + mlen])
            start += mlen
    return out
