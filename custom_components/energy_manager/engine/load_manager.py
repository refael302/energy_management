"""
Load manager – ACTIONS: turn on/off consumer switches (and optional lights) by priority.
Wasting mode uses learned consumer budget from coordinator (greedy target set), with
1 min between actions for learned entities and 5 min for unlearned (learning path).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    CONSUMER_ACTION_DELAY_LEARNED_MINUTES,
    CONSUMER_ACTION_DELAY_UNLEARNED_MINUTES,
    SYSTEM_MODE_EMERGENCY_SAVING,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)
from .consumer_budget import next_unlearned_for_sampling

_LOGGER = logging.getLogger(__name__)


def _read_power_w(hass: HomeAssistant, entity_id: str | None) -> float | None:
    """House consumption in W; None if missing or not numeric."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


# Entities that can be used as consumers (turn_on/turn_off).
CONSUMER_DOMAINS = ("switch", "input_boolean")

# Domains that can be turned off in super-saving (light, switch, input_boolean, fan).
SUPER_SAVING_TURN_OFF_DOMAINS = ("light", "switch", "input_boolean", "fan")


@dataclass
class WastingContext:
    """Budget-driven wasting session from coordinator (one update tick)."""

    consumers_ordered: list[str]
    learned_kw: dict[str, float]
    learned_target: set[str]
    discharge_headroom_kw: float
    marginal_battery_per_kw: float


@dataclass
class LoadManagerState:
    """Consumers turned on by this integration (LIFO for normal mode ramp-down)."""

    consumers_turned_on_by_wasting: list[str] = field(default_factory=list)


class LoadManager:
    """
    - wasting: match switch states to learned_target + optional unlearned learning path.
    - normal: turn off one consumer per user delay_minutes (LIFO, integration-managed list).
    - saving: turn off all consumer switches (and optional lights when super_saving).
    discharge_over_limit: turn off one consumer (prefer highest learned power if known).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        consumer_entity_ids: list[str],
        lights_entity_ids: list[str],
        delay_minutes: int,
        schedule_consumer_learn: Callable[[str, float], None] | None = None,
    ) -> None:
        self.hass = hass
        self.consumer_entity_ids = consumer_entity_ids or []
        self.lights_entity_ids = lights_entity_ids or []
        self.delay_minutes = delay_minutes
        self._schedule_consumer_learn = schedule_consumer_learn
        self.state = LoadManagerState()
        self._last_turn_off_time: datetime | None = None
        self._last_turn_on_time: datetime | None = None
        self._last_turn_on_delay_sec: int = CONSUMER_ACTION_DELAY_UNLEARNED_MINUTES * 60
        self._last_turn_off_delay_sec: int = CONSUMER_ACTION_DELAY_LEARNED_MINUTES * 60

    def _consumer_entity_ids(self, entity_ids: list[str]) -> list[str]:
        """Return only switch/input_boolean entities (consumers we can turn on/off)."""
        return [
            eid
            for eid in entity_ids
            if eid.split(".", 1)[0] in CONSUMER_DOMAINS
        ]

    def _delay_seconds_for_entity(
        self, entity_id: str, learned_kw: dict[str, float]
    ) -> int:
        if entity_id in learned_kw:
            return CONSUMER_ACTION_DELAY_LEARNED_MINUTES * 60
        return CONSUMER_ACTION_DELAY_UNLEARNED_MINUTES * 60

    def _can_turn_on_after_delay(self, entity_id: str, learned_kw: dict[str, float]) -> bool:
        need = self._delay_seconds_for_entity(entity_id, learned_kw)
        if self._last_turn_on_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_turn_on_time).total_seconds()
        return elapsed >= max(need, self._last_turn_on_delay_sec)

    def _can_turn_off_after_delay(self, entity_id: str, learned_kw: dict[str, float]) -> bool:
        need = self._delay_seconds_for_entity(entity_id, learned_kw)
        if self._last_turn_off_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_turn_off_time).total_seconds()
        return elapsed >= max(need, self._last_turn_off_delay_sec)

    async def apply_mode(
        self,
        system_mode: str,
        super_saving: bool = False,
        *,
        house_consumption_entity_id: str | None = None,
        wasting_context: WastingContext | None = None,
    ) -> None:
        """
        Apply actions for the given system mode.
        wasting_context: when mode is wasting, carries greedy learned_target and discharge hints.
        """
        consumers = self._consumer_entity_ids(self.consumer_entity_ids)
        if system_mode == SYSTEM_MODE_WASTING:
            if wasting_context is not None:
                await self._apply_wasting_budget(
                    wasting_context,
                    house_consumption_entity_id,
                )
            else:
                await self._apply_wasting_fallback(
                    consumers,
                    house_consumption_entity_id,
                    learned_kw={},
                )
        elif system_mode == SYSTEM_MODE_EMERGENCY_SAVING:
            await self._apply_saving(consumers, super_saving=True)
        elif system_mode == SYSTEM_MODE_SAVING:
            await self._apply_saving(consumers, super_saving)
        else:
            await self._apply_off_once(consumers)

    def _domain(self, entity_id: str) -> str | None:
        """Return entity domain if it is a supported consumer, else None."""
        d = entity_id.split(".", 1)[0] if "." in entity_id else ""
        return d if d in CONSUMER_DOMAINS else None

    async def _call_turn_on(self, entity_id: str) -> None:
        domain = self._domain(entity_id)
        if not domain:
            return
        state = self.hass.states.get(entity_id)
        if state is not None and state.state == "on":
            return
        await self.hass.services.async_call(
            domain, "turn_on", {"entity_id": entity_id}, blocking=True
        )

    async def _call_turn_off(self, entity_ids: list[str]) -> None:
        """Call turn_off for each entity using its domain (switch or input_boolean).

        Only send a turn_off when the current state is not already 'off', to avoid
        repeatedly sending identical commands (e.g. to IR-based devices that beep on
        every command even if they stay off).
        """
        by_domain: dict[str, list[str]] = {}
        for eid in entity_ids:
            domain = self._domain(eid)
            if not domain:
                continue
            state = self.hass.states.get(eid)
            if state is None or state.state == "off":
                continue
            by_domain.setdefault(domain, []).append(eid)
        for domain, eids in by_domain.items():
            await self.hass.services.async_call(
                domain, "turn_off", {"entity_id": eids}, blocking=True
            )

    def _can_turn_off_another_normal(self) -> bool:
        """True if at least delay_minutes have passed since last turn_off (normal mode)."""
        if self._last_turn_off_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_turn_off_time).total_seconds()
        return elapsed >= self.delay_minutes * 60

    def _append_managed(self, entity_id: str) -> None:
        if entity_id not in self.state.consumers_turned_on_by_wasting:
            self.state.consumers_turned_on_by_wasting.append(entity_id)

    def _remove_managed(self, entity_id: str) -> None:
        while entity_id in self.state.consumers_turned_on_by_wasting:
            self.state.consumers_turned_on_by_wasting.remove(entity_id)

    async def _apply_off_once(self, consumers: list[str]) -> None:
        """Turn off one integration-managed consumer (LIFO), per user delay_minutes."""
        to_consider = [
            eid
            for eid in self.state.consumers_turned_on_by_wasting
            if self._domain(eid)
        ]
        if not to_consider or not self._can_turn_off_another_normal():
            return
        entity_id = to_consider[-1]
        self._remove_managed(entity_id)
        await self._call_turn_off([entity_id])
        self._last_turn_off_time = datetime.now(timezone.utc)
        _LOGGER.debug("Turned off (normal, LIFO): %s", entity_id)

    def _super_saving_entity_ids(self, entity_ids: list[str]) -> list[str]:
        """Return only entities in domains we can turn off in super-saving."""
        return [
            eid
            for eid in entity_ids
            if eid.split(".", 1)[0] in SUPER_SAVING_TURN_OFF_DOMAINS
        ]

    async def _turn_off_super_saving_entities(self, entity_ids: list[str]) -> None:
        """Call turn_off for each entity by domain (light, switch, input_boolean, fan)."""
        filtered = self._super_saving_entity_ids(entity_ids)
        if not filtered:
            return
        by_domain: dict[str, list[str]] = {}
        for eid in filtered:
            domain = eid.split(".", 1)[0]
            state = self.hass.states.get(eid)
            if state is None or state.state == "off":
                continue
            by_domain.setdefault(domain, []).append(eid)
        for domain, eids in by_domain.items():
            await self.hass.services.async_call(
                domain, "turn_off", {"entity_id": eids}, blocking=True
            )

    async def _apply_saving(
        self, consumers: list[str], super_saving: bool
    ) -> None:
        """Turn off all consumer switches/input_booleans; if super_saving, also turn off configured devices (lights, switches, etc.)."""
        if consumers:
            await self._call_turn_off(consumers)
            _LOGGER.debug("Turned off all consumers: %s", consumers)
        if super_saving and self.lights_entity_ids:
            await self._turn_off_super_saving_entities(self.lights_entity_ids)
            _LOGGER.debug(
                "Turned off super-saving devices: %s", self.lights_entity_ids
            )
        self.state.consumers_turned_on_by_wasting.clear()

    async def _apply_wasting_budget(
        self,
        ctx: WastingContext,
        house_consumption_entity_id: str | None,
    ) -> None:
        """One turn-on or turn-off per eligible tick, prioritizing turn-off for safety."""
        learned_kw = ctx.learned_kw
        ordered = ctx.consumers_ordered
        target = ctx.learned_target

        def is_on(eid: str) -> bool:
            st = self.hass.states.get(eid)
            return st is not None and st.state == "on"

        rev = list(reversed(ordered))
        for eid in rev:
            if eid not in learned_kw:
                continue
            if eid in target:
                continue
            if not is_on(eid):
                continue
            if not self._can_turn_off_after_delay(eid, learned_kw):
                continue
            await self._call_turn_off([eid])
            self._remove_managed(eid)
            self._last_turn_off_time = datetime.now(timezone.utc)
            self._last_turn_off_delay_sec = self._delay_seconds_for_entity(eid, learned_kw)
            _LOGGER.debug("Wasting budget: turned off %s (not in target)", eid)
            return

        for eid in ordered:
            if eid not in learned_kw:
                continue
            if eid not in target:
                continue
            if is_on(eid):
                continue
            if not self._can_turn_on_after_delay(eid, learned_kw):
                continue
            baseline_w: float | None = None
            if self._schedule_consumer_learn and house_consumption_entity_id:
                baseline_w = _read_power_w(self.hass, house_consumption_entity_id)
            await self._call_turn_on(eid)
            self._append_managed(eid)
            self._last_turn_on_time = datetime.now(timezone.utc)
            self._last_turn_on_delay_sec = self._delay_seconds_for_entity(eid, learned_kw)
            _LOGGER.debug("Wasting budget: turned on %s (target)", eid)
            if (
                self._schedule_consumer_learn
                and house_consumption_entity_id
                and baseline_w is not None
            ):
                self._schedule_consumer_learn(eid, baseline_w)
            return

        candidate = next_unlearned_for_sampling(
            ordered,
            learned_kw,
            target,
            discharge_headroom_kw=ctx.discharge_headroom_kw,
            marginal_battery_per_kw=ctx.marginal_battery_per_kw,
        )
        if candidate and not is_on(candidate):
            if self._can_turn_on_after_delay(candidate, learned_kw):
                baseline_w: float | None = None
                if self._schedule_consumer_learn and house_consumption_entity_id:
                    baseline_w = _read_power_w(self.hass, house_consumption_entity_id)
                await self._call_turn_on(candidate)
                self._append_managed(candidate)
                self._last_turn_on_time = datetime.now(timezone.utc)
                self._last_turn_on_delay_sec = self._delay_seconds_for_entity(
                    candidate, learned_kw
                )
                _LOGGER.debug("Wasting budget: turned on %s (learn path)", candidate)
                if (
                    self._schedule_consumer_learn
                    and house_consumption_entity_id
                    and baseline_w is not None
                ):
                    self._schedule_consumer_learn(candidate, baseline_w)

    async def _apply_wasting_fallback(
        self,
        consumers: list[str],
        house_consumption_entity_id: str | None,
        learned_kw: dict[str, float],
    ) -> None:
        """Legacy one-per-delay when no wasting_context provided."""
        if not consumers or not self._can_turn_on_after_delay(
            consumers[0], learned_kw
        ):
            return
        for entity_id in consumers:
            state = self.hass.states.get(entity_id)
            if state and state.state != "on":
                baseline_w: float | None = None
                if self._schedule_consumer_learn and house_consumption_entity_id:
                    baseline_w = _read_power_w(self.hass, house_consumption_entity_id)
                domain = self._domain(entity_id)
                if domain:
                    await self.hass.services.async_call(
                        domain,
                        "turn_on",
                        {"entity_id": entity_id},
                        blocking=True,
                    )
                self._last_turn_on_time = datetime.now(timezone.utc)
                self._last_turn_on_delay_sec = self._delay_seconds_for_entity(
                    entity_id, learned_kw
                )
                self._append_managed(entity_id)
                _LOGGER.debug("Turned on consumer (fallback): %s", entity_id)
                if (
                    self._schedule_consumer_learn
                    and house_consumption_entity_id
                    and baseline_w is not None
                ):
                    self._schedule_consumer_learn(entity_id, baseline_w)
                return

    async def discharge_over_limit_turn_off_one(
        self,
        consumer_entity_ids: list[str],
        learned_kw: dict[str, float] | None = None,
    ) -> None:
        """Turn off one on-consumer: prefer highest learned kW, else reverse list order."""
        consumers = self._consumer_entity_ids(consumer_entity_ids or [])
        learned_kw = learned_kw or {}
        on_list = [
            eid
            for eid in consumers
            if (st := self.hass.states.get(eid)) and st.state == "on"
        ]
        if not on_list:
            return
        if learned_kw:
            on_list.sort(key=lambda e: learned_kw.get(e, 0.0), reverse=True)
        else:
            order_i = {e: i for i, e in enumerate(consumers)}
            on_list.sort(key=lambda e: order_i.get(e, 999), reverse=True)
        entity_id = on_list[0]
        domain = self._domain(entity_id)
        if domain:
            await self.hass.services.async_call(
                domain,
                "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )
            self._remove_managed(entity_id)
            _LOGGER.debug(
                "Discharge over limit: turned off one consumer %s",
                entity_id,
            )
