"""Integrate piecewise-constant hourly baseline (kW) over local clock time intervals."""

from __future__ import annotations

from datetime import datetime, timedelta


def kwh_over_clock_interval(
    profile_hourly_kw: list[float],
    start_local: datetime,
    end_local: datetime,
) -> float:
    """
    Assume profile[h] is average kW during local clock hour h.
    Integrate from start_local inclusive to end_local exclusive along the timeline.
    """
    if end_local <= start_local or len(profile_hourly_kw) != 24:
        return 0.0
    total = 0.0
    t = start_local
    while t < end_local:
        h = t.hour
        next_boundary = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        seg_end = min(next_boundary, end_local)
        frac_h = (seg_end - t).total_seconds() / 3600.0
        total += profile_hourly_kw[h] * frac_h
        t = seg_end
    return total


def kwh_forward_hours(
    profile_hourly_kw: list[float],
    start_local: datetime,
    duration_hours: float,
) -> float:
    """Energy (kWh) over duration_hours forward from start_local using repeating clock-hour profile."""
    if duration_hours <= 0:
        return 0.0
    end_local = start_local + timedelta(hours=duration_hours)
    return kwh_over_clock_interval(profile_hourly_kw, start_local, end_local)
