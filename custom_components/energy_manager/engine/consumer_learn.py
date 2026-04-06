"""
Learn approximate power per consumer from house meter delta when integration turns a consumer on.
Waits for the next house consumption sensor update (not a fixed delay), then records a sample.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    CONSUMER_LEARN_MAX_SAMPLES,
    CONSUMER_LEARN_MIN_SAMPLES,
    CONSUMER_LEARN_SPREAD_MAX,
    CONSUMER_LEARN_TIMEOUT_SEC,
)
from ..integration_log import async_log_event
from .consumer_learn_cache import create_consumer_learn_store

_LOGGER = logging.getLogger(__name__)


def _normalize_pending_w(raw: Any) -> dict[str, list[float]]:
    """Restore pending samples from store JSON (watts per consumer)."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[float]] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not isinstance(v, list):
            continue
        nums: list[float] = []
        for x in v:
            try:
                nums.append(float(x))
            except (TypeError, ValueError):
                continue
        if nums:
            out[k] = nums
    return out


def spread_ratio(vals: list[float]) -> float:
    """Relative spread (max-min)/mean; high if inconsistent."""
    if len(vals) < 2:
        return 0.0
    m = statistics.mean(vals)
    if m <= 0:
        return 999.0
    return (max(vals) - min(vals)) / m


def try_finalize_w(samples: list[float]) -> float | None:
    """
    Return finalized power in watts (mean of a consistent subset) or None.
    If one sample is an outlier and the rest agree within CONSUMER_LEARN_SPREAD_MAX, drop it.
    """
    if len(samples) < CONSUMER_LEARN_MIN_SAMPLES:
        return None
    if spread_ratio(samples) <= CONSUMER_LEARN_SPREAD_MAX:
        return statistics.mean(samples)
    if len(samples) >= 4:
        for i in range(len(samples)):
            sub = [samples[j] for j in range(len(samples)) if j != i]
            if len(sub) >= CONSUMER_LEARN_MIN_SAMPLES and spread_ratio(sub) <= CONSUMER_LEARN_SPREAD_MAX:
                return statistics.mean(sub)
    if len(samples) >= CONSUMER_LEARN_MAX_SAMPLES:
        med = statistics.median(samples)
        worst = max(range(len(samples)), key=lambda i: abs(samples[i] - med))
        sub = [samples[j] for j in range(len(samples)) if j != worst]
        if len(sub) >= CONSUMER_LEARN_MIN_SAMPLES:
            return statistics.mean(sub)
        return statistics.median(sub)
    return None


async def async_wait_house_power_after_turn_on(
    hass: HomeAssistant,
    house_entity_id: str,
    moment_after_turn_on: datetime,
    timeout_sec: float = CONSUMER_LEARN_TIMEOUT_SEC,
) -> float | None:
    """
    Wait until house consumption entity gets a state update with last_changed strictly
    after moment_after_turn_on, then return parsed power in watts.
    """
    loop = hass.loop
    fut: asyncio.Future[float | None] = loop.create_future()

    @callback
    def _on_state(event: Any) -> None:
        if fut.done():
            return
        new_st = event.data.get("new_state")
        if new_st is None:
            return
        try:
            cutoff = dt_util.as_utc(moment_after_turn_on)
            lu = dt_util.as_utc(new_st.last_updated)
            lc = dt_util.as_utc(new_st.last_changed)
            if max(lu, lc) <= cutoff:
                return
            val = float(new_st.state)
        except (TypeError, ValueError):
            return
        if new_st.state in ("unknown", "unavailable", ""):
            return
        fut.set_result(val)

    remove = async_track_state_change_event(hass, [house_entity_id], _on_state)
    try:
        return await asyncio.wait_for(fut, timeout=timeout_sec)
    except asyncio.TimeoutError:
        _LOGGER.debug(
            "Consumer learn: timeout waiting for %s to update after turn_on",
            house_entity_id,
        )
        return None
    finally:
        remove()


@dataclass
class ConsumerLearnRuntime:
    """In-memory learned kW and pending samples (watts) per consumer entity_id."""

    fingerprint: str = ""
    learned_kw: dict[str, float] = field(default_factory=dict)
    pending_w: dict[str, list[float]] = field(default_factory=dict)

    def apply_fingerprint(self, fp: str, store_data: dict[str, Any] | None) -> None:
        """Load learned + pending from store when fingerprint matches; else clear both."""
        self.fingerprint = fp
        self.learned_kw.clear()
        self.pending_w.clear()
        if not store_data or store_data.get("fingerprint") != fp:
            return
        kw_raw = store_data.get("learned_kw")
        if isinstance(kw_raw, dict):
            self.learned_kw = {
                k: float(v) for k, v in kw_raw.items() if isinstance(k, str)
            }
        self.pending_w = _normalize_pending_w(store_data.get("pending_w"))
        for eid in list(self.pending_w.keys()):
            if eid in self.learned_kw:
                del self.pending_w[eid]


class ConsumerLearner:
    """Coordinates disk persistence and sample recording (thread-safe per entry)."""

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
            "learned_kw": dict(self._runtime.learned_kw),
            "pending_w": {k: list(v) for k, v in self._runtime.pending_w.items() if v},
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
        return dict(self._runtime.learned_kw)

    def get_pending_counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self._runtime.pending_w.items()}

    def get_pending_samples_kw(self) -> dict[str, list[float]]:
        """Per consumer not yet finalized: house-meter delta samples as kW (same scale as learned_kw)."""
        return {
            eid: [round(w / 1000.0, 3) for w in watts]
            for eid, watts in self._runtime.pending_w.items()
            if watts
        }

    def is_learned(self, entity_id: str) -> bool:
        return entity_id in self._runtime.learned_kw

    async def async_reset(self, fingerprint: str) -> None:
        """Clear finalized learned power only; keep in-progress pending samples (and persist)."""
        async with self._lock:
            self._runtime.fingerprint = fingerprint
            self._runtime.learned_kw.clear()
            await self._store.async_save(self._persist_dict())

    async def async_record_delta_w(
        self, consumer_entity_id: str, delta_w: float, fingerprint: str
    ) -> None:
        """Append one sample (watts); persist only when a value is finalized."""
        if delta_w <= 0:
            _LOGGER.debug(
                "Consumer learn: skip non-positive delta %.0f W for %s",
                delta_w,
                consumer_entity_id,
            )
            return
        async with self._lock:
            if fingerprint != self._runtime.fingerprint:
                return
            if consumer_entity_id in self._runtime.learned_kw:
                return
            pending = self._runtime.pending_w.setdefault(consumer_entity_id, [])
            pending.append(delta_w)
            if len(pending) > CONSUMER_LEARN_MAX_SAMPLES:
                pending.pop(0)
            finalized = try_finalize_w(pending)
            if finalized is not None:
                n_used = len(pending)
                kw = round(finalized / 1000.0, 3)
                self._runtime.learned_kw[consumer_entity_id] = kw
                self._runtime.pending_w.pop(consumer_entity_id, None)
                _LOGGER.info(
                    "Consumer learn: %s ≈ %.3f kW (%d samples)",
                    consumer_entity_id,
                    kw,
                    n_used,
                )
                await async_log_event(
                    self.hass,
                    self._entry_id,
                    "INFO",
                    "LEARN",
                    "consumer_learn_finalized",
                    f"Learned power for {consumer_entity_id}",
                    {
                        "entity_id": consumer_entity_id,
                        "learned_kw": str(kw),
                        "samples_used": str(n_used),
                    },
                )
                await self._store.async_save(self._persist_dict())
            else:
                _LOGGER.debug(
                    "Consumer learn: %s sample %.0f W (n=%d)",
                    consumer_entity_id,
                    delta_w,
                    len(pending),
                )
                await self._store.async_save(self._persist_dict())
