"""
Learn residual house consumption (kW) per clock hour from a 7-day rolling window of completed calendar days.
Skips samples when an unlearned managed consumer is on (cannot neutralize load).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import BASELINE_PROFILE_BOOTSTRAP_KW, BASELINE_PROFILE_WINDOW_DAYS
from .baseline_profile_cache import create_baseline_profile_store
from .consumer_learn_cache import consumer_learn_fingerprint

_LOGGER = logging.getLogger(__name__)


def unlearned_consumer_on(
    hass: HomeAssistant,
    consumer_ids: list[str],
    learned_kw: dict[str, float],
    *,
    has_power_sensor: dict[str, bool] | None = None,
    actual_on_map: dict[str, bool | None] | None = None,
) -> bool:
    """True if some configured consumer is on and not yet learned (must skip baseline sample)."""
    for eid in consumer_ids:
        if eid in learned_kw:
            continue
        if has_power_sensor and not has_power_sensor.get(eid, False):
            st = hass.states.get(eid)
            if st is not None and st.state == "on":
                return True
            continue
        if actual_on_map is not None:
            if actual_on_map.get(eid) is True:
                return True
            continue
        st = hass.states.get(eid)
        if st is not None and st.state == "on":
            return True
    return False


def residual_house_kw(
    hass: HomeAssistant,
    house_kw: float,
    consumer_ids: list[str],
    learned_kw: dict[str, float],
    *,
    actual_on_map: dict[str, bool | None] | None = None,
) -> float:
    """House kW minus sum of learned kW for consumers that are on."""
    r = house_kw
    for eid in consumer_ids:
        kw = learned_kw.get(eid)
        if kw is None:
            continue
        if actual_on_map is not None:
            if actual_on_map.get(eid) is True:
                r -= kw
            continue
        st = hass.states.get(eid)
        if st is not None and st.state == "on":
            r -= kw
    return max(0.0, r)


@dataclass
class BaselineProfileRuntime:
    fingerprint: str = ""
    completed: deque[tuple[str, list[float | None]]] = field(default_factory=lambda: deque(maxlen=BASELINE_PROFILE_WINDOW_DAYS))
    today_key: str | None = None
    today_sums: list[float] = field(default_factory=lambda: [0.0] * 24)
    today_counts: list[int] = field(default_factory=lambda: [0] * 24)
    dirty: bool = False

    def zero_today(self) -> None:
        self.today_sums = [0.0] * 24
        self.today_counts = [0] * 24

    def apply_store(self, fp: str, data: dict[str, Any] | None) -> None:
        self.fingerprint = fp
        self.completed.clear()
        self.today_key = None
        self.zero_today()
        self.dirty = False
        if not data or data.get("fingerprint") != fp:
            return
        comp = data.get("completed")
        if isinstance(comp, list):
            for item in comp[-BASELINE_PROFILE_WINDOW_DAYS:]:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    continue
                day_s, prof = item
                if not isinstance(day_s, str) or not isinstance(prof, list):
                    continue
                row: list[float | None] = []
                for x in prof[:24]:
                    if x is None:
                        row.append(None)
                    else:
                        try:
                            row.append(float(x))
                        except (TypeError, ValueError):
                            row.append(None)
                while len(row) < 24:
                    row.append(None)
                self.completed.append((day_s, row))
        tk = data.get("today_key")
        if isinstance(tk, str):
            self.today_key = tk
        sums = data.get("today_sums")
        counts = data.get("today_counts")
        if isinstance(sums, list) and isinstance(counts, list):
            for i in range(24):
                try:
                    self.today_sums[i] = float(sums[i]) if i < len(sums) else 0.0
                except (TypeError, ValueError):
                    self.today_sums[i] = 0.0
                try:
                    self.today_counts[i] = int(counts[i]) if i < len(counts) else 0
                except (TypeError, ValueError):
                    self.today_counts[i] = 0

    def _finalize_day(self) -> None:
        if self.today_key is None:
            return
        prof: list[float | None] = []
        for i in range(24):
            c = self.today_counts[i]
            prof.append(self.today_sums[i] / c if c > 0 else None)
        self.completed.append((self.today_key, prof))
        self.dirty = True

    def ensure_today(self, d: date) -> None:
        if self.today_key is None:
            self.today_key = d.isoformat()
            self.zero_today()
            return
        td = date.fromisoformat(self.today_key)
        while d > td:
            self._finalize_day()
            td = td + timedelta(days=1)
            self.today_key = td.isoformat()
            self.zero_today()
        if d < td:
            self.today_key = d.isoformat()
            self.zero_today()

    def record_sample(self, residual_kw: float, now_local: datetime) -> None:
        self.ensure_today(now_local.date())
        h = now_local.hour
        self.today_sums[h] += residual_kw
        self.today_counts[h] += 1
        self.dirty = True

    def effective_profile_kw(self, bootstrap_kw: float) -> list[float]:
        out: list[float] = []
        for hour in range(24):
            vals: list[float] = []
            for _day, prof in self.completed:
                if hour < len(prof) and prof[hour] is not None:
                    vals.append(prof[hour])  # type: ignore[arg-type]
            if vals:
                out.append(round(sum(vals) / len(vals), 4))
            else:
                out.append(round(bootstrap_kw, 4))
        return out

    def to_save_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "completed": [[d, p] for d, p in self.completed],
            "today_key": self.today_key,
            "today_sums": list(self.today_sums),
            "today_counts": list(self.today_counts),
        }


class BaselineProfileLearner:
    """Rolling 7 completed calendar days of hourly residual kW; persist to disk."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._store: Store = create_baseline_profile_store(hass, entry_id)
        self._runtime = BaselineProfileRuntime()
        self._lock = asyncio.Lock()
        self._loaded = False

    @property
    def store(self) -> Store:
        return self._store

    async def async_ensure_loaded(self, config: dict[str, Any]) -> None:
        fp = consumer_learn_fingerprint(config)
        async with self._lock:
            if not self._loaded:
                raw = await self._store.async_load()
                self._loaded = True
                disk = raw if isinstance(raw, dict) else {}
                self._runtime.apply_store(fp, disk)
                if disk.get("fingerprint") != fp:
                    await self._store.async_save(self._runtime.to_save_dict())
                return
            if fp != self._runtime.fingerprint:
                raw = await self._store.async_load()
                disk = raw if isinstance(raw, dict) else {}
                if disk.get("fingerprint") == fp:
                    self._runtime.apply_store(fp, disk)
                else:
                    self._runtime.apply_store(fp, None)
                    await self._store.async_save(self._runtime.to_save_dict())

    def record_sample_if_allowed(
        self,
        residual_kw: float,
        now_local: datetime | None,
    ) -> bool:
        """Return True if sample was recorded."""
        if now_local is None:
            return False
        self._runtime.record_sample(residual_kw, now_local)
        return True

    def get_effective_profile_kw(self) -> list[float]:
        return self._runtime.effective_profile_kw(BASELINE_PROFILE_BOOTSTRAP_KW)

    def get_current_hour_forecast_kw(self, now_local: datetime | None) -> float:
        prof = self.get_effective_profile_kw()
        if now_local is None:
            return prof[0] if prof else BASELINE_PROFILE_BOOTSTRAP_KW
        return prof[now_local.hour]

    def estimated_daily_kwh(self) -> float:
        return round(sum(self.get_effective_profile_kw()), 4)

    def completed_days_count(self) -> int:
        return len(self._runtime.completed)

    async def async_persist_if_dirty(self) -> None:
        async with self._lock:
            if not self._runtime.dirty:
                return
            self._runtime.dirty = False
            await self._store.async_save(self._runtime.to_save_dict())
