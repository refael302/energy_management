"""Learn per-consumer power: dedicated power sensors and house-meter delta when no sensor."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    CONSUMER_ACTIVE_POWER_THRESHOLD_KW,
    CONSUMER_HOUSE_DELTA_FALLBACK_SEC,
    CONSUMER_HOUSE_DELTA_MAX_SAMPLES,
    CONSUMER_HOUSE_DELTA_MIN_GUARD_SEC,
    CONSUMER_LEARN_MIN_SAMPLES,
    CONSUMER_LEARN_SPREAD_MAX,
)
from ..integration_log import async_log_event
from .consumer_learn_cache import create_consumer_learn_store
from .house_delta_sample_math import best_triple_from_four, relative_spread_kw as _relative_spread_kw

_LOGGER = logging.getLogger(__name__)

LEARN_SOURCE_POWER_SENSOR = "power_sensor"
LEARN_SOURCE_HOUSE_DELTA = "house_delta"


def _load_max_power_kw_from_stored(m: dict[str, Any]) -> float:
    """Restore peak power in kW; legacy field max_power_w stored watts from older builds."""
    raw_kw = m.get("max_power_kw")
    if raw_kw is not None:
        try:
            return max(0.0, float(raw_kw))
        except (TypeError, ValueError):
            pass
    raw_w = m.get("max_power_w")
    if raw_w is None:
        return 0.0
    try:
        v = max(0.0, float(raw_w))
    except (TypeError, ValueError):
        return 0.0
    if v > 100:
        return v / 1000.0
    return v


@dataclass
class _HouseDeltaWait:
    baseline_kw: float
    house_entity_id: str
    turn_on_utc: datetime
    min_sample_utc: datetime
    fallback_deadline_utc: datetime


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
    learn_source: dict[str, str] = field(default_factory=dict)
    house_delta_samples: dict[str, list[float]] = field(default_factory=dict)
    unmeasurable: set[str] = field(default_factory=set)

    def apply_fingerprint(self, fp: str, store_data: dict[str, Any] | None) -> None:
        """Load metrics from store when fingerprint matches; else clear."""
        self.fingerprint = fp
        self.metrics.clear()
        self.hour_key = None
        self.expected_kwh_sum.clear()
        self.expected_seconds.clear()
        self.active_kwh_sum.clear()
        self.active_seconds.clear()
        self.learn_source.clear()
        self.house_delta_samples.clear()
        self.unmeasurable.clear()
        if not store_data or store_data.get("fingerprint") != fp:
            return
        raw_metrics = store_data.get("metrics")
        if isinstance(raw_metrics, dict):
            for eid, m in raw_metrics.items():
                if not isinstance(eid, str) or not isinstance(m, dict):
                    continue
                try:
                    max_kw = _load_max_power_kw_from_stored(m)
                    self.metrics[eid] = {
                        "max_power_kw": max_kw,
                        "energy_per_hour_latest_kwh": float(m.get("energy_per_hour_latest_kwh") or 0.0),
                        "energy_per_hour_active_avg_kwh": float(
                            m.get("energy_per_hour_active_avg_kwh") or 0.0
                        ),
                    }
                except (TypeError, ValueError):
                    continue
        src = store_data.get("learn_source")
        if isinstance(src, dict):
            for eid, v in src.items():
                if isinstance(eid, str) and isinstance(v, str):
                    self.learn_source[eid] = v
        hd = store_data.get("house_delta_samples")
        if isinstance(hd, dict):
            for eid, lst in hd.items():
                if not isinstance(eid, str) or not isinstance(lst, list):
                    continue
                row: list[float] = []
                for x in lst:
                    try:
                        row.append(max(0.0, float(x)))
                    except (TypeError, ValueError):
                        continue
                if row:
                    self.house_delta_samples[eid] = row


class ConsumerLearner:
    """Coordinates disk persistence and per-consumer learning (sensor + house delta)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._store: Store = create_consumer_learn_store(hass, entry_id)
        self._runtime = ConsumerLearnRuntime()
        self._lock = asyncio.Lock()
        self._loaded = False
        self._house_delta_wait: dict[str, _HouseDeltaWait] = {}

    def _persist_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self._runtime.fingerprint,
            "metrics": dict(self._runtime.metrics),
            "learn_source": dict(self._runtime.learn_source),
            "house_delta_samples": {
                k: list(v) for k, v in self._runtime.house_delta_samples.items()
            },
            # Legacy key kept empty: unmeasurable no longer blocks scheduling after load.
            "unmeasurable": [],
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

    def get_unmeasurable(self) -> set[str]:
        return set(self._runtime.unmeasurable)

    def get_learn_source(self) -> dict[str, str]:
        return dict(self._runtime.learn_source)

    def get_house_delta_samples(self) -> dict[str, list[float]]:
        return {k: list(v) for k, v in self._runtime.house_delta_samples.items()}

    def get_pending_counts(self) -> dict[str, int]:
        """Collected house-delta samples per consumer still in learning (not stabilizing wait)."""
        out: dict[str, int] = {}
        for eid, samples in self._runtime.house_delta_samples.items():
            if eid not in self._runtime.metrics and eid not in self._runtime.unmeasurable:
                n = len(samples)
                if n:
                    out[eid] = n
        return out

    def get_pending_samples_kw(self) -> dict[str, list[float]]:
        return self.get_house_delta_samples()

    def get_stabilizing_entity_ids(self) -> set[str]:
        return set(self._house_delta_wait.keys())

    def get_metrics(self) -> dict[str, dict[str, float]]:
        return {eid: dict(vals) for eid, vals in self._runtime.metrics.items()}

    def is_learned(self, entity_id: str) -> bool:
        return entity_id in self._runtime.metrics

    def is_unmeasurable(self, entity_id: str) -> bool:
        return entity_id in self._runtime.unmeasurable

    async def async_reset(self, fingerprint: str) -> None:
        """Clear all metrics for current mapping."""
        async with self._lock:
            self._runtime.fingerprint = fingerprint
            self._runtime.metrics.clear()
            self._runtime.learn_source.clear()
            self._runtime.house_delta_samples.clear()
            self._runtime.unmeasurable.clear()
            self._house_delta_wait.clear()
            await self._store.async_save(self._persist_dict())

    async def async_clear_consumer_entity(
        self, consumer_entity_id: str, fingerprint: str
    ) -> None:
        """Clear learned data, samples, wait, and unmeasurable flag for one consumer switch."""
        async with self._lock:
            if fingerprint != self._runtime.fingerprint:
                return
            self._runtime.metrics.pop(consumer_entity_id, None)
            self._runtime.learn_source.pop(consumer_entity_id, None)
            self._runtime.unmeasurable.discard(consumer_entity_id)
            self._runtime.house_delta_samples.pop(consumer_entity_id, None)
            self._house_delta_wait.pop(consumer_entity_id, None)
            self._runtime.expected_kwh_sum.pop(consumer_entity_id, None)
            self._runtime.expected_seconds.pop(consumer_entity_id, None)
            self._runtime.active_kwh_sum.pop(consumer_entity_id, None)
            self._runtime.active_seconds.pop(consumer_entity_id, None)
            await self._store.async_save(self._persist_dict())

    def _ensure_metric(self, entity_id: str) -> dict[str, float]:
        return self._runtime.metrics.setdefault(
            entity_id,
            {
                "max_power_kw": 0.0,
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
        power_kw: float | None,
        expected_on: bool,
        now_local: datetime,
        dt_seconds: float,
        fingerprint: str,
    ) -> None:
        """Record one update tick for a consumer with dedicated power sensor (power in kW)."""
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
            self._runtime.learn_source.setdefault(
                consumer_entity_id, LEARN_SOURCE_POWER_SENSOR
            )
            p = max(0.0, float(power_kw or 0.0))
            if p > float(metric.get("max_power_kw", 0.0)):
                metric["max_power_kw"] = round(p, 3)
                changed = True
            dt_h = max(0.0, float(dt_seconds)) / 3600.0
            if expected_on:
                self._runtime.expected_kwh_sum[consumer_entity_id] += p * dt_h
                self._runtime.expected_seconds[consumer_entity_id] += max(0.0, float(dt_seconds))
            if p >= CONSUMER_ACTIVE_POWER_THRESHOLD_KW:
                self._runtime.active_kwh_sum[consumer_entity_id] += p * dt_h
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
                        "max_power_kw": str(metric["max_power_kw"]),
                    },
                )
                await self._store.async_save(self._persist_dict())

    async def async_schedule_house_delta_sample(
        self,
        consumer_entity_id: str,
        baseline_house_kw: float,
        *,
        house_entity_id: str,
        has_power_sensor: bool,
        house_sensor_configured: bool,
        fingerprint: str,
    ) -> None:
        """After integration turn-on: wait for next house state change (after min guard), then sample delta."""
        async with self._lock:
            if fingerprint != self._runtime.fingerprint:
                return
            if (
                not house_sensor_configured
                or has_power_sensor
                or not str(house_entity_id).strip()
            ):
                return
            if consumer_entity_id in self._runtime.metrics:
                return
            self._runtime.unmeasurable.discard(consumer_entity_id)
            now = dt_util.utcnow()
            guard = max(0.5, float(CONSUMER_HOUSE_DELTA_MIN_GUARD_SEC))
            fb = max(guard + 1.0, float(CONSUMER_HOUSE_DELTA_FALLBACK_SEC))
            self._house_delta_wait[consumer_entity_id] = _HouseDeltaWait(
                baseline_kw=max(0.0, float(baseline_house_kw)),
                house_entity_id=str(house_entity_id).strip(),
                turn_on_utc=now,
                min_sample_utc=now + timedelta(seconds=guard),
                fallback_deadline_utc=now + timedelta(seconds=fb),
            )
            _LOGGER.debug(
                "House-delta learn scheduled for %s (baseline %.3f kW, guard=%.1fs)",
                consumer_entity_id,
                baseline_house_kw,
                guard,
            )

    def _house_delta_should_sample(
        self, wait: _HouseDeltaWait, now_utc: datetime
    ) -> bool:
        """True when house entity reported a new value after min guard, or fallback time elapsed."""
        if now_utc < wait.min_sample_utc:
            return False
        h_st = self.hass.states.get(wait.house_entity_id)
        if h_st is None:
            return now_utc >= wait.fallback_deadline_utc
        if h_st.state in ("unknown", "unavailable", ""):
            return now_utc >= wait.fallback_deadline_utc
        try:
            lc = dt_util.as_utc(h_st.last_changed)
        except (AttributeError, TypeError, ValueError):
            lc = now_utc
        if lc >= wait.min_sample_utc:
            return True
        return now_utc >= wait.fallback_deadline_utc

    async def async_process_house_delta_pending(
        self,
        house_kw: float,
        fingerprint: str,
    ) -> None:
        """Sample pending deltas on first qualifying house state change (or fallback deadline)."""
        async with self._lock:
            if fingerprint != self._runtime.fingerprint:
                return
            now = dt_util.utcnow()
            hk = max(0.0, float(house_kw))
            to_finalize: list[str] = []
            for eid, wait in list(self._house_delta_wait.items()):
                st = self.hass.states.get(eid)
                if st is None or st.state != "on":
                    del self._house_delta_wait[eid]
                    _LOGGER.debug(
                        "House-delta learn cancelled (switch not on): %s", eid
                    )
                    continue
                if not self._house_delta_should_sample(wait, now):
                    continue
                delta_kw = max(0.0, hk - wait.baseline_kw)
                del self._house_delta_wait[eid]
                samples = self._runtime.house_delta_samples.setdefault(eid, [])
                samples.append(round(delta_kw, 4))
                _LOGGER.debug(
                    "House-delta sample for %s: %.3f kW (n=%s)",
                    eid,
                    delta_kw,
                    len(samples),
                )
                to_finalize.append(eid)

            log_events: list[tuple[str, str, str, dict[str, str]]] = []
            persist = False
            for eid in to_finalize:
                if self._try_finalize_house_delta_unlocked(eid, log_events):
                    persist = True

            if persist:
                await self._store.async_save(self._persist_dict())

        for level, event, summary, ctx in log_events:
            await async_log_event(
                self.hass,
                self._entry_id,
                level,
                "LEARN",
                event,
                summary,
                ctx,
            )

    def _apply_house_delta_learn_unlocked(
        self,
        entity_id: str,
        kw: float,
        samples: list[float],
        spread: float,
        log_events: list[tuple[str, str, str, dict[str, str]]],
    ) -> bool:
        kw = round(max(0.0, kw), 4)
        self._runtime.metrics[entity_id] = {
            "max_power_kw": round(kw, 3),
            "energy_per_hour_latest_kwh": kw,
            "energy_per_hour_active_avg_kwh": kw,
        }
        self._runtime.learn_source[entity_id] = LEARN_SOURCE_HOUSE_DELTA
        self._runtime.house_delta_samples.pop(entity_id, None)
        log_events.append(
            (
                "INFO",
                "consumer_house_delta_learned",
                f"Learned {entity_id} from house meter delta (~{kw} kW)",
                {
                    "entity_id": entity_id,
                    "learned_kw": str(kw),
                    "samples": str(samples),
                    "spread_ratio": str(round(spread, 4)),
                },
            )
        )
        _LOGGER.info(
            "House-delta learned %s: %.3f kW (samples=%s spread=%.4f)",
            entity_id,
            kw,
            samples,
            spread,
        )
        return True

    def _try_finalize_house_delta_unlocked(
        self,
        entity_id: str,
        log_events: list[tuple[str, str, str, dict[str, str]]],
    ) -> bool:
        if entity_id in self._runtime.metrics or entity_id in self._runtime.unmeasurable:
            return False
        raw = self._runtime.house_delta_samples.get(entity_id, [])
        if len(raw) > CONSUMER_HOUSE_DELTA_MAX_SAMPLES:
            raw = raw[-CONSUMER_HOUSE_DELTA_MAX_SAMPLES :]
            self._runtime.house_delta_samples[entity_id] = raw
        samples = list(raw)
        n = len(samples)
        if n < CONSUMER_LEARN_MIN_SAMPLES:
            return False

        if n == 3:
            spread = _relative_spread_kw(samples)
            if spread <= CONSUMER_LEARN_SPREAD_MAX:
                avg = sum(samples) / 3.0
                return self._apply_house_delta_learn_unlocked(
                    entity_id, avg, samples, spread, log_events
                )
            return False

        # n == 4: try dropping one outlier; no 5th sample is ever used
        assert n == 4
        triple = best_triple_from_four(samples, CONSUMER_LEARN_SPREAD_MAX)
        if triple is not None:
            mean_kw, triple_spread = triple
            return self._apply_house_delta_learn_unlocked(
                entity_id, mean_kw, samples, triple_spread, log_events
            )

        self._runtime.unmeasurable.add(entity_id)
        self._runtime.house_delta_samples.pop(entity_id, None)
        full_spread = _relative_spread_kw(samples)
        log_events.append(
            (
                "WARN",
                "consumer_house_delta_unmeasurable",
                f"House meter delta for {entity_id} inconsistent after {CONSUMER_HOUSE_DELTA_MAX_SAMPLES} samples",
                {
                    "entity_id": entity_id,
                    "samples": str(samples),
                    "spread_ratio": str(round(full_spread, 4)),
                },
            )
        )
        _LOGGER.warning(
            "House-delta unmeasurable: %s (samples=%s spread=%.3f)",
            entity_id,
            samples,
            full_spread,
        )
        return True
