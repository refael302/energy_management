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
    DEFAULT_AZIMUTH,
    DEFAULT_SYSTEM_SIZE_KW,
    DEFAULT_TILT,
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
    _logged_solpos_fail = False
    _logged_poa_fail = False
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
        except Exception as e:
            if not _logged_solpos_fail:
                _LOGGER.warning(
                    "pvlib solar position failed for hour %s: %s",
                    t,
                    e,
                )
                _logged_solpos_fail = True
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
                val = poa["poa_global"]
                poa_global = float(val.iloc[0]) if hasattr(val, "iloc") else float(val)
                if poa_global < 0:
                    poa_global = 0.0
            except Exception as e:
                if not _logged_poa_fail:
                    _LOGGER.warning(
                        "pvlib get_total_irradiance failed (hour %s, string %s): %s",
                        t,
                        s,
                        e,
                    )
                    _logged_poa_fail = True
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
        pr_factor: float = 1.0,
    ) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.pr_factor = pr_factor
        self.strings = [
            StringConfig(
                system_size_kw=float(s.get("system_size_kw", DEFAULT_SYSTEM_SIZE_KW)),
                tilt=float(s.get("tilt", DEFAULT_TILT)),
                azimuth=float(s.get("azimuth", DEFAULT_AZIMUTH)),
            )
            for s in (strings or [])
        ]
        if not self.strings:
            self.strings = [
                StringConfig(DEFAULT_SYSTEM_SIZE_KW, DEFAULT_TILT, DEFAULT_AZIMUTH)
            ]
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

        _LOGGER.debug(
            "Open-Meteo: %d hours, first=%s last=%s, GHI sample=%s",
            len(times_str),
            times_str[0] if times_str else None,
            times_str[-1] if times_str else None,
            ghi[:5] if len(ghi) >= 5 else ghi,
        )

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
        _LOGGER.debug(
            "Forecast now=%s, times range %s .. %s",
            now.isoformat(),
            times[0].isoformat() if times else None,
            times[-1].isoformat() if times else None,
        )

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
                sum(p[hour_idx] for p in power_per_string) * self.pr_factor
            )

        # Index-based: which hour slot does "now" fall into (robust to timezone/year)
        now_ts = now.timestamp()
        t0_ts = times[0].timestamp()
        hour_index = int((now_ts - t0_ts) / 3600)
        hour_index = max(0, min(hour_index, len(times) - 1))

        current_power_kw = total_power_per_hour[hour_index]
        next_hour_kwh = (
            total_power_per_hour[hour_index + 1]
            if hour_index + 1 < len(times)
            else 0.0
        )
        # Today remaining: from current hour to end of first 24h (API first day)
        today_end_idx = min(24, len(times))
        today_remaining_kwh = sum(
            total_power_per_hour[i]
            for i in range(hour_index, today_end_idx)
        )
        # Tomorrow: next 24h (API second day)
        tomorrow_kwh = sum(
            total_power_per_hour[i]
            for i in range(24, min(48, len(times)))
        )

        if sum(total_power_per_hour) == 0:
            _LOGGER.warning(
                "Forecast computed all zeros (hour_index=%s, now=%s)",
                hour_index,
                now.isoformat(),
            )
        _LOGGER.debug(
            "Forecast hour_index=%s, next_hour_kwh=%s, today_remaining=%s, tomorrow=%s",
            hour_index,
            next_hour_kwh,
            today_remaining_kwh,
            tomorrow_kwh,
        )

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
