"""
Project battery SOC forward using hourly PV forecast and learned baseline house load (kW per clock hour).
Estimates time-to-full and time-to-very-low with optional fractional-hour crossing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class EdgeHorizonResult:
    """Result for one edge (full or very low)."""

    hours_until: float | None
    edge_time_iso: str | None
    hourly_steps: list[dict[str, Any]]
    reached_within_horizon: bool
    soc_start_kwh: float
    soc_end_last_kwh: float


def _ensure_24(baseline_hourly_kw: list[float]) -> list[float]:
    if not baseline_hourly_kw:
        return [0.0] * 24
    if len(baseline_hourly_kw) >= 24:
        return [float(x) for x in baseline_hourly_kw[:24]]
    out = [float(x) for x in baseline_hourly_kw]
    pad = out[-1] if out else 0.0
    while len(out) < 24:
        out.append(pad)
    return out


def _parse_time_iso(t_iso: str) -> datetime | None:
    try:
        s = t_iso.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _house_kw_for_datetime(dt: datetime, baseline24: list[float]) -> float:
    h = dt.hour % 24
    return baseline24[h]


def compute_battery_edge_horizons(
    *,
    now_local: datetime,
    soc_percent: float,
    capacity_kwh: float,
    max_charge_kw: float,
    max_discharge_kw: float,
    pv_kw_slots: list[float],
    time_iso_slots: list[str],
    baseline_hourly_kw: list[float],
    target_full_percent: float,
    target_very_low_percent: float,
) -> tuple[EdgeHorizonResult, EdgeHorizonResult]:
    """
    Walk hourly PV vs baseline house load; battery absorbs surplus up to max_charge,
    covers deficit up to max_discharge. Returns (to_full, to_very_low).
    """
    baseline24 = _ensure_24(baseline_hourly_kw)
    n = min(len(pv_kw_slots), len(time_iso_slots))
    if n <= 0 or capacity_kwh <= 0:
        empty = EdgeHorizonResult(
            hours_until=None,
            edge_time_iso=None,
            hourly_steps=[],
            reached_within_horizon=False,
            soc_start_kwh=0.0,
            soc_end_last_kwh=0.0,
        )
        return empty, empty

    cap = float(capacity_kwh)
    soc_pct = max(0.0, min(100.0, float(soc_percent)))
    soc_kwh = soc_pct / 100.0 * cap
    full_kwh = float(target_full_percent) / 100.0 * cap
    vl_kwh = float(target_very_low_percent) / 100.0 * cap
    max_c = max(0.0, float(max_charge_kw))
    max_d = max(0.0, float(max_discharge_kw))

    steps: list[dict[str, Any]] = []
    hours_elapsed = 0.0
    hours_to_full: float | None = None
    hours_to_vl: float | None = None

    if soc_kwh >= full_kwh - 1e-9:
        hours_to_full = 0.0
    if soc_kwh <= vl_kwh + 1e-9:
        hours_to_vl = 0.0

    soc_running = soc_kwh

    for i in range(n):
        pv = float(pv_kw_slots[i])
        t_iso = time_iso_slots[i]
        dt = _parse_time_iso(t_iso)
        if dt is None:
            continue
        house = _house_kw_for_datetime(dt, baseline24)
        spare = pv - house
        if spare >= 0.0:
            ch_kw = min(spare, max_c)
            dis_kw = 0.0
            delta_kwh = ch_kw * 1.0
        else:
            dis_kw = min(-spare, max_d)
            ch_kw = 0.0
            delta_kwh = -dis_kw * 1.0

        soc_start = soc_running
        soc_end = soc_start + delta_kwh
        soc_end = max(0.0, min(cap, soc_end))

        if hours_to_full is None and soc_start < full_kwh - 1e-9:
            if soc_end >= full_kwh - 1e-9:
                if delta_kwh > 1e-12:
                    frac = (full_kwh - soc_start) / delta_kwh
                    frac = max(0.0, min(1.0, frac))
                    hours_to_full = hours_elapsed + frac
                else:
                    hours_to_full = hours_elapsed

        if hours_to_vl is None and soc_start > vl_kwh + 1e-9:
            if soc_end <= vl_kwh + 1e-9:
                if delta_kwh < -1e-12:
                    frac = (soc_start - vl_kwh) / (-delta_kwh)
                    frac = max(0.0, min(1.0, frac))
                    hours_to_vl = hours_elapsed + frac
                else:
                    hours_to_vl = hours_elapsed

        hours_elapsed += 1.0
        soc_running = soc_end

        steps.append(
            {
                "time": t_iso,
                "soc_percent": round(100.0 * soc_end / cap, 2) if cap > 0 else 0.0,
                "pv_kw": round(pv, 3),
                "house_kw": round(house, 3),
                "battery_charge_kw": round(ch_kw, 3),
                "battery_discharge_kw": round(dis_kw, 3),
                "delta_soc_kwh": round(delta_kwh, 4),
            }
        )

    def _edge_iso(hours: float | None) -> str | None:
        if hours is None:
            return None
        try:
            return (now_local + timedelta(hours=float(hours))).isoformat()
        except (TypeError, ValueError, OverflowError):
            return None

    to_full = EdgeHorizonResult(
        hours_until=hours_to_full,
        edge_time_iso=_edge_iso(hours_to_full) if hours_to_full is not None else None,
        hourly_steps=list(steps),
        reached_within_horizon=hours_to_full is not None,
        soc_start_kwh=soc_kwh,
        soc_end_last_kwh=soc_running,
    )
    to_vl = EdgeHorizonResult(
        hours_until=hours_to_vl,
        edge_time_iso=_edge_iso(hours_to_vl) if hours_to_vl is not None else None,
        hourly_steps=list(steps),
        reached_within_horizon=hours_to_vl is not None,
        soc_start_kwh=soc_kwh,
        soc_end_last_kwh=soc_running,
    )
    return to_full, to_vl
