"""
Solar forecast engine using Open-Meteo (GHI, DNI, DHI) and pvlib for POA and power.
Supports multiple panel strings (tilt, azimuth, system_size_kw).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from pvlib import irradiance, solarposition
import pandas as pd

from ..const import (
    OPEN_METEO_BASE_URL,
    OPEN_METEO_FORECAST_DAYS,
    OPEN_METEO_HOURLY,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class StringConfig:
    """One PV string: size (kW), tilt (°), azimuth (°)."""

    system_size_kw: float
    tilt: float
    azimuth: float


@dataclass
class SolarForecast:
    """Forecast result: next hour, today remaining, tomorrow, current power."""

    forecast_next_hour_kwh: float = 0.0
    forecast_today_remaining_kwh: float = 0.0
    forecast_tomorrow_kwh: float = 0.0
    forecast_current_power_kw: float = 0.0
    hourly_poa_per_string: list[list[float]] = field(default_factory=list)
    hourly_power_per_string: list[list[float]] = field(default_factory=list)
    available: bool = True  # False when fetch failed or data empty


def _compute_poa_and_power_sync(
    lat: float,
    lon: float,
    times: list[datetime],
    ghi: list[float],
    dni: list[float],
    dhi: list[float],
    strings: list[StringConfig],
) -> tuple[list[list[float]], list[list[float]]]:
    """
    Synchronous computation: for each time step, sun position -> POA per string -> power.
    Returns (hourly_poa_per_string, hourly_power_per_string) where each is [string_idx][hour_idx].
    """
    poa_per_string: list[list[float]] = [[] for _ in strings]
    power_per_string: list[list[float]] = [[] for _ in strings]
    for t, g, n, d in zip(times, ghi, dni, dhi):
        if g is None or n is None or d is None:
            g, n, d = 0.0, 0.0, 0.0
        try:
            solpos = solarposition.get_solarposition(
                pd.Timestamp(t), lat, lon
            )
            solar_zenith = float(solpos["zenith"].iloc[0])
            solar_azimuth = float(solpos["azimuth"].iloc[0])
            dni_extra = float(irradiance.get_extra_radiation(pd.Timestamp(t)))
        except Exception:
            for s in range(len(strings)):
                poa_per_string[s].append(0.0)
                power_per_string[s].append(0.0)
            continue
        if solar_zenith > 90:
            for s in range(len(strings)):
                poa_per_string[s].append(0.0)
                power_per_string[s].append(0.0)
            continue
        for s, cfg in enumerate(strings):
            try:
                poa = irradiance.get_total_irradiance(
                    cfg.tilt,
                    cfg.azimuth,
                    solar_zenith,
                    solar_azimuth,
                    g,
                    n,
                    d,
                    dni_extra=dni_extra,
                    model="haydavies",
                )
                poa_global = float(poa["poa_global"].iloc[0])
                if poa_global < 0:
                    poa_global = 0.0
            except Exception:
                poa_global = 0.0
            poa_per_string[s].append(poa_global)
            power_per_string[s].append(
                round(cfg.system_size_kw * (poa_global / 1000.0), 4)
            )
    return poa_per_string, power_per_string


class ForecastEngine:
    """Fetches irradiance from Open-Meteo and computes POA + expected power per string."""

    def __init__(
        self,
        latitude: float,
        longitude: float,
        strings: list[dict[str, Any]],
    ) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.strings = [
            StringConfig(
                system_size_kw=float(s.get("system_size_kw", 5.0)),
                tilt=float(s.get("tilt", 30)),
                azimuth=float(s.get("azimuth", 0)),
            )
            for s in (strings or [])
        ]
        if not self.strings:
            self.strings = [StringConfig(5.0, 30.0, 0.0)]
        self._last: SolarForecast | None = None

    async def fetch_and_compute(
        self, hass: Any, now: datetime | None = None
    ) -> SolarForecast:
        """
        Fetch hourly GHI, DNI, DHI from Open-Meteo; compute POA and power in executor.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        url = (
            f"{OPEN_METEO_BASE_URL}?"
            f"latitude={self.latitude}&longitude={self.longitude}"
            f"&hourly={OPEN_METEO_HOURLY}&forecast_days={OPEN_METEO_FORECAST_DAYS}"
            "&timezone=UTC"
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        _LOGGER.warning(
                            "Open-Meteo returned %s for %s", resp.status, url
                        )
                        return SolarForecast(available=False)
                    data = await resp.json()
        except asyncio.TimeoutError:
            _LOGGER.warning("Open-Meteo request timeout")
            return SolarForecast(available=False)
        except Exception as e:
            _LOGGER.warning("Open-Meteo request failed: %s", e)
            return SolarForecast(available=False)

        hourly = data.get("hourly", {})
        times_str = hourly.get("time", [])
        ghi = hourly.get("shortwave_radiation", [])
        dni = hourly.get("direct_normal_irradiance", [])
        dhi = hourly.get("diffuse_radiation", [])

        if not times_str or not ghi:
            return SolarForecast(available=False)

        def _parse_time(ts: str) -> datetime:
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt

        times = [_parse_time(ts) for ts in times_str]
        # Ensure same length
        n = len(times)
        ghi = (ghi + [None] * n)[:n]
        dni = (dni + [None] * n)[:n] if dni else [None] * n
        dhi = (dhi + [None] * n)[:n] if dhi else [None] * n

        poa_per_string, power_per_string = await hass.async_add_executor_job(
            _compute_poa_and_power_sync,
            self.latitude,
            self.longitude,
            times,
            ghi,
            dni,
            dhi,
            self.strings,
        )

        # Aggregate total power per hour (sum over strings)
        total_power_per_hour = []
        for hour_idx in range(len(times)):
            total_power_per_hour.append(
                sum(p[hour_idx] for p in power_per_string)
            )

        # forecast_next_hour: energy in the next hour (kWh) = power (kW) * 1h
        now_ts = now.timestamp()
        next_hour_kwh = 0.0
        current_power_kw = 0.0
        for hour_idx, t in enumerate(times):
            start = t.timestamp()
            end = start + 3600
            if start <= now_ts < end:
                current_power_kw = total_power_per_hour[hour_idx]
                next_hour_kwh = current_power_kw
                if hour_idx + 1 < len(times):
                    next_hour_kwh = total_power_per_hour[hour_idx + 1]
                break
            if hour_idx + 1 < len(times) and times[hour_idx + 1].timestamp() > now_ts:
                next_hour_kwh = total_power_per_hour[hour_idx + 1]
                current_power_kw = total_power_per_hour[hour_idx]
                break

        # Today remaining: sum of hourly energy from now until end of today (UTC)
        today_remaining_kwh = 0.0
        for hour_idx, t in enumerate(times):
            if t.date() > now.date():
                break
            if t >= now and t.date() == now.date():
                today_remaining_kwh += total_power_per_hour[hour_idx]

        # Tomorrow total
        next_day = now.date() + timedelta(days=1)
        tomorrow_kwh = 0.0
        for hour_idx, t in enumerate(times):
            if t.date() == next_day:
                tomorrow_kwh += total_power_per_hour[hour_idx]

        result = SolarForecast(
            forecast_next_hour_kwh=round(next_hour_kwh, 2),
            forecast_today_remaining_kwh=round(today_remaining_kwh, 2),
            forecast_tomorrow_kwh=round(tomorrow_kwh, 2),
            forecast_current_power_kw=round(current_power_kw, 2),
            hourly_poa_per_string=poa_per_string,
            hourly_power_per_string=power_per_string,
            available=True,
        )
        self._last = result
        return result
