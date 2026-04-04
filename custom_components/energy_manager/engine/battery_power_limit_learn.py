"""
Track peak battery discharge and charge power (kW) from the battery power sensor.
Positive battery_power_kw = discharge; negative = charge. Peaks are monotonic (max seen).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    DEFAULT_BATTERY_NOMINAL_VOLTAGE,
    DEFAULT_MAX_BATTERY_CURRENT_AMPS,
    MIN_EFFECTIVE_MAX_BATTERY_POWER_KW,
)
from .battery_power_peak_cache import (
    battery_power_peak_fingerprint,
    create_battery_peak_store,
)


def _bootstrap_peak_kw() -> float:
    """Approximate kW from legacy default max amps × nominal V."""
    return max(
        MIN_EFFECTIVE_MAX_BATTERY_POWER_KW,
        float(DEFAULT_MAX_BATTERY_CURRENT_AMPS)
        * float(DEFAULT_BATTERY_NOMINAL_VOLTAGE)
        / 1000.0,
    )


@dataclass
class BatteryPowerPeakLearner:
    hass: HomeAssistant
    entry_id: str
    _store: Any = field(init=False, repr=False)
    fingerprint: str = ""
    peak_discharge_kw: float = field(default_factory=_bootstrap_peak_kw)
    peak_charge_kw: float = field(default_factory=_bootstrap_peak_kw)
    sample_ticks: int = 0
    _loaded: bool = False
    _dirty: bool = False

    def __post_init__(self) -> None:
        self._store = create_battery_peak_store(self.hass, self.entry_id)

    async def async_ensure_loaded(self, config: dict[str, Any]) -> None:
        fp = battery_power_peak_fingerprint(config)
        if self._loaded and fp == self.fingerprint:
            return
        self.fingerprint = fp
        raw = await self._store.async_load()
        data = raw if isinstance(raw, dict) else {}
        if data.get("fingerprint") != fp:
            self.peak_discharge_kw = _bootstrap_peak_kw()
            self.peak_charge_kw = _bootstrap_peak_kw()
            self.sample_ticks = 0
        else:
            try:
                self.peak_discharge_kw = max(
                    MIN_EFFECTIVE_MAX_BATTERY_POWER_KW,
                    float(data.get("peak_discharge_kw", _bootstrap_peak_kw())),
                )
            except (TypeError, ValueError):
                self.peak_discharge_kw = _bootstrap_peak_kw()
            try:
                self.peak_charge_kw = max(
                    MIN_EFFECTIVE_MAX_BATTERY_POWER_KW,
                    float(data.get("peak_charge_kw", _bootstrap_peak_kw())),
                )
            except (TypeError, ValueError):
                self.peak_charge_kw = _bootstrap_peak_kw()
            try:
                self.sample_ticks = int(data.get("sample_ticks", 0))
            except (TypeError, ValueError):
                self.sample_ticks = 0
        self._loaded = True
        self._dirty = False

    def record_sample(self, battery_power_kw: float) -> None:
        """Update peaks from instantaneous battery power (kW)."""
        d = max(0.0, battery_power_kw)
        c = max(0.0, -battery_power_kw)
        updated = False
        if d > self.peak_discharge_kw:
            self.peak_discharge_kw = d
            updated = True
        if c > self.peak_charge_kw:
            self.peak_charge_kw = c
            updated = True
        self.sample_ticks += 1
        if updated:
            self._dirty = True

    async def async_persist_if_dirty(self) -> None:
        if not self._dirty or not self._loaded:
            return
        await self._store.async_save(
            {
                "fingerprint": self.fingerprint,
                "peak_discharge_kw": round(self.peak_discharge_kw, 4),
                "peak_charge_kw": round(self.peak_charge_kw, 4),
                "sample_ticks": self.sample_ticks,
            }
        )
        self._dirty = False
