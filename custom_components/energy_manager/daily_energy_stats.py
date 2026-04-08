"""
Persisted daily energy totals (kWh): integrate solar, battery discharge, house load,
and consumer power while in wasting mode. Helpers for forecast full-day and elapsed
forecast energy vs actual PV.
"""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DAILY_ENERGY_STORE_VERSION = 1
# Skip trapezoid if gap larger than this (restart / long pause) to avoid spikes
_MAX_INTEGRATION_GAP_HOURS = 2.0


def create_daily_energy_store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, DAILY_ENERGY_STORE_VERSION, f"{DOMAIN}.{entry_id}.daily_energy_stats")


def forecast_full_day_kwh(hourly_kw: list[float] | None) -> float | None:
    """Sum of today's hourly forecast slots (kWh-equivalent per slot)."""
    if not hourly_kw:
        return None
    return round(sum(float(x) for x in hourly_kw), 3)


def forecast_elapsed_today_kwh(
    hourly_kw: list[float] | None,
    hour_idx: int,
    now_local: datetime,
) -> float | None:
    """
    Cumulative forecast from local midnight through now: completed hours + prorated current hour.
    hour_idx: index of the current hour in the first-day hourly block (from forecast engine).
    """
    if hourly_kw is None or hour_idx < 0 or hour_idx >= len(hourly_kw):
        return None
    past_sum = sum(float(hourly_kw[i]) for i in range(hour_idx))
    hour_start = now_local.replace(minute=0, second=0, microsecond=0)
    frac = (now_local - hour_start).total_seconds() / 3600.0
    frac = max(0.0, min(1.0, frac))
    return round(past_sum + float(hourly_kw[hour_idx]) * frac, 3)


class DailyEnergyAccumulator:
    """Trapz-integrate power (kW) into daily kWh; reset at local calendar day rollover."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = create_daily_energy_store(hass, entry_id)
        self._loaded = False
        self._dirty = False
        self.day_key: str = ""
        self.pv_kwh: float = 0.0
        self.battery_discharge_kwh: float = 0.0
        self.house_kwh: float = 0.0
        self.wasting_consumer_kwh: float = 0.0
        self._last_ts: datetime | None = None
        self._last_solar_kw: float = 0.0
        self._last_bat_dis_kw: float = 0.0
        self._last_house_kw: float = 0.0
        self._last_consumer_kw: float = 0.0

    async def async_ensure_loaded(self) -> None:
        if self._loaded:
            return
        raw = await self._store.async_load()
        self._loaded = True
        if not isinstance(raw, dict):
            return
        self.day_key = str(raw.get("day_key") or "")
        self.pv_kwh = float(raw.get("pv_kwh") or 0.0)
        self.battery_discharge_kwh = float(raw.get("battery_discharge_kwh") or 0.0)
        self.house_kwh = float(raw.get("house_kwh") or 0.0)
        self.wasting_consumer_kwh = float(raw.get("wasting_consumer_kwh") or 0.0)

    def _rollover_if_needed(self, now_local: datetime) -> None:
        dk = now_local.date().isoformat()
        if self.day_key == dk:
            return
        self.day_key = dk
        self.pv_kwh = 0.0
        self.battery_discharge_kwh = 0.0
        self.house_kwh = 0.0
        self.wasting_consumer_kwh = 0.0
        self._last_ts = None
        self._dirty = True

    def accumulate(
        self,
        now_local: datetime,
        solar_kw: float,
        battery_kw: float,
        house_kw: float,
        wasting_mode: bool,
        consumer_total_kw: float,
    ) -> None:
        """Add energy since last sample (coordinator tick)."""
        self._rollover_if_needed(now_local)
        bat_dis = max(0.0, float(battery_kw))
        cons = max(0.0, float(consumer_total_kw))
        sk = max(0.0, float(solar_kw))
        hk = max(0.0, float(house_kw))

        if self._last_ts is None:
            self._last_ts = now_local
            self._last_solar_kw = sk
            self._last_bat_dis_kw = bat_dis
            self._last_house_kw = hk
            self._last_consumer_kw = cons
            return

        dt_h = (now_local - self._last_ts).total_seconds() / 3600.0
        if dt_h <= 0:
            return
        if dt_h > _MAX_INTEGRATION_GAP_HOURS:
            self._last_ts = now_local
            self._last_solar_kw = sk
            self._last_bat_dis_kw = bat_dis
            self._last_house_kw = hk
            self._last_consumer_kw = cons
            return

        self.pv_kwh += 0.5 * (self._last_solar_kw + sk) * dt_h
        self.battery_discharge_kwh += 0.5 * (self._last_bat_dis_kw + bat_dis) * dt_h
        self.house_kwh += 0.5 * (self._last_house_kw + hk) * dt_h
        if wasting_mode:
            self.wasting_consumer_kwh += 0.5 * (self._last_consumer_kw + cons) * dt_h

        self._last_ts = now_local
        self._last_solar_kw = sk
        self._last_bat_dis_kw = bat_dis
        self._last_house_kw = hk
        self._last_consumer_kw = cons
        self._dirty = True

    async def async_persist_if_dirty(self) -> None:
        if not self._dirty:
            return
        try:
            await self._store.async_save(
                {
                    "day_key": self.day_key,
                    "pv_kwh": round(self.pv_kwh, 4),
                    "battery_discharge_kwh": round(self.battery_discharge_kwh, 4),
                    "house_kwh": round(self.house_kwh, 4),
                    "wasting_consumer_kwh": round(self.wasting_consumer_kwh, 4),
                }
            )
            self._dirty = False
        except OSError as err:
            _LOGGER.warning("Daily energy stats save failed: %s", err)
