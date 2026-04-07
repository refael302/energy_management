"""Learn per-consumer power metrics from dedicated consumer power sensors."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import (
    CONSUMER_ACTIVE_POWER_THRESHOLD_W,
)
from ..integration_log import async_log_event
from .consumer_learn_cache import create_consumer_learn_store

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConsumerLearnRuntime:
    """In-memory learned per-consumer metrics."""

    fingerprint: str = ""
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    hour_key: str | None = None
    expected_kwh_sum: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    expected_seconds: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    active_kwh_sum: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    active_seconds: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def apply_fingerprint(self, fp: str, store_data: dict[str, Any] | None) -> None:
        """Load metrics from store when fingerprint matches; else clear."""
        self.fingerprint = fp
        self.metrics.clear()
        self.hour_key = None
        self.expected_kwh_sum.clear()
        self.expected_seconds.clear()
        self.active_kwh_sum.clear()
        self.active_seconds.clear()
        if not store_data or store_data.get("fingerprint") != fp:
            return
        raw_metrics = store_data.get("metrics")
        if isinstance(raw_metrics, dict):
            for eid, m in raw_metrics.items():
                if not isinstance(eid, str) or not isinstance(m, dict):
                    continue
                try:
                    self.metrics[eid] = {
                        "max_power_w": float(m.get("max_power_w") or 0.0),
                        "energy_per_hour_latest_kwh": float(m.get("energy_per_hour_latest_kwh") or 0.0),
                        "energy_per_hour_active_avg_kwh": float(m.get("energy_per_hour_active_avg_kwh") or 0.0),
                    }
                except (TypeError, ValueError):
                    continue


class ConsumerLearner:
    """Coordinates disk persistence and sensor-based per-consumer learning."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._store: Store = create_consumer_learn_store(hass, entry_id)
        self._runtime = ConsumerLearnRuntime()
        self._lock = asyncio.Lock()
        self._loaded = False

    def _persist_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self._runtime.fingerprint,
            "metrics": dict(self._runtime.metrics),
        }

    @property
    def store(self) -> Store:
        return self._store

    async def async_ensure_loaded(self, fingerprint: str) -> None:
        async with self._lock:
            if not self._loaded:
                raw = await self._store.async_load()
                self._loaded = True
                data = raw if isinstance(raw, dict) else {}
                if data.get("fingerprint") == fingerprint:
                    self._runtime.apply_fingerprint(fingerprint, data)
                else:
                    self._runtime.apply_fingerprint(fingerprint, None)
                return
            if fingerprint != self._runtime.fingerprint:
                raw = await self._store.async_load()
                disk = raw if isinstance(raw, dict) else {}
                if disk.get("fingerprint") == fingerprint:
                    self._runtime.apply_fingerprint(fingerprint, disk)
                else:
                    self._runtime.apply_fingerprint(fingerprint, None)
                    await self._store.async_save(self._persist_dict())

    def get_learned_kw(self) -> dict[str, float]:
        return {
            eid: round(float(m.get("energy_per_hour_active_avg_kwh") or 0.0), 3)
            for eid, m in self._runtime.metrics.items()
        }

    def get_pending_counts(self) -> dict[str, int]:
        return {}

    def get_pending_samples_kw(self) -> dict[str, list[float]]:
        return {}

    def get_metrics(self) -> dict[str, dict[str, float]]:
        return {eid: dict(vals) for eid, vals in self._runtime.metrics.items()}

    def is_learned(self, entity_id: str) -> bool:
        return entity_id in self._runtime.metrics

    async def async_reset(self, fingerprint: str) -> None:
        """Clear all metrics for current mapping."""
        async with self._lock:
            self._runtime.fingerprint = fingerprint
            self._runtime.metrics.clear()
            await self._store.async_save(self._persist_dict())

    def _ensure_metric(self, entity_id: str) -> dict[str, float]:
        return self._runtime.metrics.setdefault(
            entity_id,
            {
                "max_power_w": 0.0,
                "energy_per_hour_latest_kwh": 0.0,
                "energy_per_hour_active_avg_kwh": 0.0,
            },
        )

    def _finalize_hour(self) -> bool:
        changed = False
        for eid, metric in self._runtime.metrics.items():
            exp_s = float(self._runtime.expected_seconds.get(eid, 0.0))
            if exp_s > 0:
                exp_kwh = float(self._runtime.expected_kwh_sum.get(eid, 0.0))
                latest = exp_kwh * 3600.0 / exp_s
                if abs(latest - float(metric.get("energy_per_hour_latest_kwh", 0.0))) > 1e-6:
                    metric["energy_per_hour_latest_kwh"] = round(latest, 4)
                    changed = True
            act_s = float(self._runtime.active_seconds.get(eid, 0.0))
            if act_s > 0:
                act_kwh = float(self._runtime.active_kwh_sum.get(eid, 0.0))
                active_avg = act_kwh * 3600.0 / act_s
                if abs(active_avg - float(metric.get("energy_per_hour_active_avg_kwh", 0.0))) > 1e-6:
                    metric["energy_per_hour_active_avg_kwh"] = round(active_avg, 4)
                    changed = True
        self._runtime.expected_kwh_sum.clear()
        self._runtime.expected_seconds.clear()
        self._runtime.active_kwh_sum.clear()
        self._runtime.active_seconds.clear()
        return changed

    async def async_record_power_tick(
        self,
        consumer_entity_id: str,
        power_w: float | None,
        expected_on: bool,
        now_local: datetime,
        dt_seconds: float,
        fingerprint: str,
    ) -> None:
        """Record one update tick for a consumer with dedicated power sensor."""
        async with self._lock:
            if fingerprint != self._runtime.fingerprint:
                return
            hour_key = now_local.strftime("%Y-%m-%dT%H")
            changed = False
            if self._runtime.hour_key is None:
                self._runtime.hour_key = hour_key
            elif self._runtime.hour_key != hour_key:
                changed = self._finalize_hour() or changed
                self._runtime.hour_key = hour_key
            metric = self._ensure_metric(consumer_entity_id)
            p = max(0.0, float(power_w or 0.0))
            if p > float(metric.get("max_power_w", 0.0)):
                metric["max_power_w"] = round(p, 3)
                changed = True
            dt_h = max(0.0, float(dt_seconds)) / 3600.0
            if expected_on:
                self._runtime.expected_kwh_sum[consumer_entity_id] += (p / 1000.0) * dt_h
                self._runtime.expected_seconds[consumer_entity_id] += max(0.0, float(dt_seconds))
            if p >= CONSUMER_ACTIVE_POWER_THRESHOLD_W:
                self._runtime.active_kwh_sum[consumer_entity_id] += (p / 1000.0) * dt_h
                self._runtime.active_seconds[consumer_entity_id] += max(0.0, float(dt_seconds))
            if changed:
                _LOGGER.debug("Consumer sensor learn updated for %s", consumer_entity_id)
                await async_log_event(
                    self.hass,
                    self._entry_id,
                    "INFO",
                    "LEARN",
                    "consumer_sensor_metrics_updated",
                    f"Updated metrics for {consumer_entity_id}",
                    {
                        "entity_id": consumer_entity_id,
                        "max_power_w": str(metric["max_power_w"]),
                    },
                )
                await self._store.async_save(self._persist_dict())
