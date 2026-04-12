"""
Load manager – ACTIONS: turn on/off consumer switches (and optional lights) by priority.
Wasting mode uses learned consumer budget from coordinator (greedy target set), with
1 min between actions for learned entities and 5 min for unlearned (learning path).
After the integration turns a consumer on, it is not turned off again until
CONSUMER_MIN_ON_MINUTES have elapsed (saving / discharge_over_limit exempt).
Saving mode runs bulk turn-off only on entry to saving (still only calls turn_off
for entities that are on). Emergency saving repeats bulk at EMERGENCY_SAVING_BULK_INTERVAL_SEC
while the mode stays active.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    CONSUMER_ACTION_DELAY_LEARNED_MINUTES,
    CONSUMER_ACTION_DELAY_UNLEARNED_MINUTES,
    CONSUMER_MIN_ON_MINUTES,
    DISCHARGE_SHED_COOLDOWN_SEC,
    SYSTEM_MODE_EMERGENCY_SAVING,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)
from ..decision_context import DecisionContext
from ..integration_log import async_log_event
from .consumer_budget import next_unlearned_for_sampling

_LOGGER = logging.getLogger(__name__)


def _action_summary_bulk_consumers_off(
    decision_context: DecisionContext, *, count: int, reason_code: str
) -> str:
    d = decision_context.to_flat_log_dict()
    return (
        f"Bulk off {count} consumers | {reason_code} | "
        f"mode={d['system_mode']} soc={d['battery_soc_percent']}%"
    )[:200]


def _action_summary_super_saving(*, count: int, reason_code: str) -> str:
    return f"Super-saving off {count} devices | {reason_code}"[:200]


def _action_summary_entity_off(
    decision_context: DecisionContext, entity_id: str, reason_code: str
) -> str:
    d = decision_context.to_flat_log_dict()
    return (
        f"Turn off {entity_id} | {reason_code} | mode={d['system_mode']}"
    )[:200]


def _action_summary_entity_on(
    decision_context: DecisionContext, entity_id: str, reason_code: str
) -> str:
    d = decision_context.to_flat_log_dict()
    return f"Turn on {entity_id} | {reason_code} | mode={d['system_mode']}"[:200]


def _action_summary_discharge_noop(decision_context: DecisionContext) -> str:
    return "Discharge limit noop | discharge_over_limit_no_targets"[:200]


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
    unmeasurable_entity_ids: set[str] = field(default_factory=set)


@dataclass
class LoadManagerState:
    """Consumers turned on by this integration (LIFO for normal mode ramp-down)."""

    consumers_turned_on_by_wasting: list[str] = field(default_factory=list)


class LoadManager:
    """
    - wasting: match switch states to learned_target + optional unlearned learning path.
    - normal: turn off one consumer per user delay_minutes (LIFO, integration-managed list).
    - saving: turn off all consumer switches (and optional lights when super_saving).
    discharge_over_limit: turn off one on-consumer if any; log when none to turn off.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        consumer_entity_ids: list[str],
        lights_entity_ids: list[str],
        delay_minutes: int,
        schedule_consumer_learn: Callable[[str], None] | None = None,
        *,
        integration_entry_id: str | None = None,
    ) -> None:
        self.hass = hass
        self._integration_entry_id = integration_entry_id or ""
        self.consumer_entity_ids = consumer_entity_ids or []
        self.lights_entity_ids = lights_entity_ids or []
        self.delay_minutes = delay_minutes
        self._schedule_consumer_learn = schedule_consumer_learn
        self.state = LoadManagerState()
        self._last_turn_off_time: datetime | None = None
        self._last_turn_on_time: datetime | None = None
        self._last_turn_on_delay_sec: int = CONSUMER_ACTION_DELAY_UNLEARNED_MINUTES * 60
        self._last_turn_off_delay_sec: int = CONSUMER_ACTION_DELAY_LEARNED_MINUTES * 60
        self._integration_turn_on_at_utc: dict[str, datetime] = {}
        self._integration_turn_on_eids_this_apply: list[str] = []
        # Anti-flap: after discharge-ceiling shed, block re-turn-on for DISCHARGE_SHED_COOLDOWN_SEC.
        self._discharge_shed_until_utc: dict[str, datetime] = {}
        self._last_emergency_saving_bulk_utc: datetime | None = None

    async def _log_action(
        self,
        level: str,
        event: str,
        summary: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        if not self._integration_entry_id:
            return
        await async_log_event(
            self.hass,
            self._integration_entry_id,
            level,
            "ACTION",
            event,
            summary,
            context,
        )

    def _consumer_entity_ids(self, entity_ids: list[str]) -> list[str]:
        """Return only switch/input_boolean entities (consumers we can turn on/off)."""
        return [
            eid
            for eid in entity_ids
            if eid.split(".", 1)[0] in CONSUMER_DOMAINS
        ]

    def _purge_expired_discharge_shed(self, now_utc: datetime) -> None:
        expired = [
            eid
            for eid, until in self._discharge_shed_until_utc.items()
            if until <= now_utc
        ]
        for eid in expired:
            del self._discharge_shed_until_utc[eid]

    def _is_under_discharge_shed_cooldown(self, entity_id: str, *, now_utc: datetime) -> bool:
        until = self._discharge_shed_until_utc.get(entity_id)
        return until is not None and until > now_utc

    def note_discharge_shed(self, entity_id: str) -> None:
        """Call after turning a consumer off due to discharge ceiling (coordinator / tests)."""
        now = datetime.now(timezone.utc)
        self._discharge_shed_until_utc[entity_id] = now + timedelta(
            seconds=max(1, int(DISCHARGE_SHED_COOLDOWN_SEC))
        )

    def emergency_saving_bulk_due(self, interval_sec: int) -> bool:
        """While already in emergency_saving: True if a bulk turn-off pass may run again."""
        last = self._last_emergency_saving_bulk_utc
        if last is None:
            return True
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed >= float(interval_sec)

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

    def _min_on_seconds(self) -> float:
        return float(CONSUMER_MIN_ON_MINUTES) * 60.0

    def _can_turn_off_after_min_on(self, entity_id: str) -> bool:
        """Block turn-off until CONSUMER_MIN_ON_MINUTES after we turned this entity on."""
        t0 = self._integration_turn_on_at_utc.get(entity_id)
        if t0 is None:
            return True
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        return elapsed >= self._min_on_seconds()

    async def _turn_on_consumer(self, entity_id: str) -> None:
        """turn_on consumer and record UTC time when we transition off -> on."""
        if not self._domain(entity_id):
            return
        state = self.hass.states.get(entity_id)
        was_off = state is None or state.state != "on"
        await self._call_turn_on(entity_id)
        if was_off:
            self._integration_turn_on_at_utc[entity_id] = datetime.now(timezone.utc)
            self._integration_turn_on_eids_this_apply.append(entity_id)

    def drain_integration_turn_ons(self) -> list[str]:
        """Entity IDs the integration turned on (off→on) during the last apply_mode call."""
        out = list(self._integration_turn_on_eids_this_apply)
        self._integration_turn_on_eids_this_apply.clear()
        return out

    async def apply_mode(
        self,
        system_mode: str,
        super_saving: bool = False,
        *,
        apply_saving_bulk: bool = True,
        house_consumption_entity_id: str | None = None,
        wasting_context: WastingContext | None = None,
        suppress_wasting_turn_ons: bool = False,
        decision_context: DecisionContext | None = None,
    ) -> None:
        """
        Apply actions for the given system mode.
        wasting_context: when mode is wasting, carries greedy learned_target and discharge hints.
        suppress_wasting_turn_ons: when True, still allow wasting turn-offs but no new turn-ons.
        apply_saving_bulk: when False, saving/emergency_saving skip consumer/super-saving bulk (coordinator).
        decision_context: per-tick snapshot from coordinator for ACTION logs (required when logging).
        """
        self._integration_turn_on_eids_this_apply.clear()
        if system_mode != SYSTEM_MODE_EMERGENCY_SAVING:
            self._last_emergency_saving_bulk_utc = None
        consumers = self._consumer_entity_ids(self.consumer_entity_ids)
        dc = decision_context
        if system_mode == SYSTEM_MODE_WASTING:
            if wasting_context is not None:
                await self._apply_wasting_budget(
                    wasting_context,
                    house_consumption_entity_id,
                    suppress_turn_ons=suppress_wasting_turn_ons,
                    decision_context=dc,
                )
            else:
                await self._apply_wasting_fallback(
                    consumers,
                    house_consumption_entity_id,
                    learned_kw={},
                    suppress_turn_ons=suppress_wasting_turn_ons,
                    decision_context=dc,
                )
        elif system_mode == SYSTEM_MODE_EMERGENCY_SAVING:
            await self._apply_saving(
                consumers,
                super_saving=True,
                decision_context=dc,
                run_bulk=apply_saving_bulk,
                record_emergency_bulk_time=True,
            )
        elif system_mode == SYSTEM_MODE_SAVING:
            await self._apply_saving(
                consumers,
                super_saving,
                decision_context=dc,
                run_bulk=apply_saving_bulk,
                record_emergency_bulk_time=False,
            )
        else:
            await self._apply_off_once(consumers, decision_context=dc)

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

    async def _call_turn_off(self, entity_ids: list[str]) -> list[str]:
        """Call turn_off for each entity using its domain (switch or input_boolean).

        Only send a turn_off when the current state is not already 'off', to avoid
        repeatedly sending identical commands (e.g. to IR-based devices that beep on
        every command even if they stay off).

        Returns entity IDs for which a turn_off service call was issued (order follows
        entity_ids).
        """
        by_domain: dict[str, list[str]] = {}
        turned_off: list[str] = []
        for eid in entity_ids:
            domain = self._domain(eid)
            if not domain:
                continue
            state = self.hass.states.get(eid)
            if state is None or state.state == "off":
                continue
            by_domain.setdefault(domain, []).append(eid)
            turned_off.append(eid)
        for domain, eids in by_domain.items():
            await self.hass.services.async_call(
                domain, "turn_off", {"entity_id": eids}, blocking=True
            )
        return turned_off

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
        self._integration_turn_on_at_utc.pop(entity_id, None)
        while entity_id in self.state.consumers_turned_on_by_wasting:
            self.state.consumers_turned_on_by_wasting.remove(entity_id)

    async def _apply_off_once(
        self,
        consumers: list[str],
        *,
        decision_context: DecisionContext | None,
    ) -> None:
        """Turn off one integration-managed consumer (LIFO), per user delay_minutes."""
        to_consider = [
            eid
            for eid in self.state.consumers_turned_on_by_wasting
            if self._domain(eid)
        ]
        if not to_consider or not self._can_turn_off_another_normal():
            return
        for entity_id in reversed(to_consider):
            if not self._can_turn_off_after_min_on(entity_id):
                continue
            self._remove_managed(entity_id)
            await self._call_turn_off([entity_id])
            self._last_turn_off_time = datetime.now(timezone.utc)
            _LOGGER.debug("Turned off (normal, LIFO): %s", entity_id)
            if decision_context is not None:
                await self._log_action(
                    "INFO",
                    "consumer_turned_off",
                    _action_summary_entity_off(
                        decision_context, entity_id, "normal_lifo"
                    ),
                    decision_context.merge_action_context(
                        reason_code="normal_lifo", entity_id=entity_id
                    ),
                )
            return

    def _super_saving_entity_ids(self, entity_ids: list[str]) -> list[str]:
        """Return only entities in domains we can turn off in super-saving."""
        return [
            eid
            for eid in entity_ids
            if eid.split(".", 1)[0] in SUPER_SAVING_TURN_OFF_DOMAINS
        ]

    async def _turn_off_super_saving_entities(self, entity_ids: list[str]) -> list[str]:
        """Call turn_off for each entity by domain (light, switch, input_boolean, fan).

        Returns entity IDs for which a turn_off service call was issued (order follows
        filtered list order).
        """
        filtered = self._super_saving_entity_ids(entity_ids)
        if not filtered:
            return []
        by_domain: dict[str, list[str]] = {}
        turned_off: list[str] = []
        for eid in filtered:
            domain = eid.split(".", 1)[0]
            state = self.hass.states.get(eid)
            if state is None or state.state == "off":
                continue
            by_domain.setdefault(domain, []).append(eid)
            turned_off.append(eid)
        for domain, eids in by_domain.items():
            await self.hass.services.async_call(
                domain, "turn_off", {"entity_id": eids}, blocking=True
            )
        return turned_off

    async def _apply_saving(
        self,
        consumers: list[str],
        super_saving: bool,
        *,
        decision_context: DecisionContext | None,
        run_bulk: bool = True,
        record_emergency_bulk_time: bool = False,
    ) -> None:
        """Turn off all consumer switches/input_booleans; if super_saving, also turn off configured devices (lights, switches, etc.)."""
        if not run_bulk:
            return
        if consumers:
            turned = await self._call_turn_off(consumers)
            _LOGGER.debug("Turned off all consumers: %s", consumers)
            if decision_context is not None and turned:
                n = len(turned)
                await self._log_action(
                    "INFO",
                    "consumers_turned_off_bulk",
                    _action_summary_bulk_consumers_off(
                        decision_context, count=n, reason_code="saving"
                    ),
                    decision_context.merge_action_context(
                        reason_code="saving", count=str(n)
                    ),
                )
        if super_saving and self.lights_entity_ids:
            lights_turned = await self._turn_off_super_saving_entities(
                self.lights_entity_ids
            )
            _LOGGER.debug(
                "Turned off super-saving devices: %s", self.lights_entity_ids
            )
            if decision_context is not None and lights_turned:
                n = len(lights_turned)
                await self._log_action(
                    "INFO",
                    "super_saving_devices_off",
                    _action_summary_super_saving(
                        count=n, reason_code="super_saving"
                    ),
                    decision_context.merge_action_context(
                        reason_code="super_saving", count=str(n)
                    ),
                )
        self.state.consumers_turned_on_by_wasting.clear()
        self._integration_turn_on_at_utc.clear()
        if record_emergency_bulk_time:
            self._last_emergency_saving_bulk_utc = datetime.now(timezone.utc)

    async def _apply_wasting_budget(
        self,
        ctx: WastingContext,
        house_consumption_entity_id: str | None,
        *,
        suppress_turn_ons: bool = False,
        decision_context: DecisionContext | None = None,
    ) -> None:
        """One turn-on or turn-off per eligible tick, prioritizing turn-off for safety."""
        now_utc = datetime.now(timezone.utc)
        self._purge_expired_discharge_shed(now_utc)
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
            if not self._can_turn_off_after_min_on(eid):
                continue
            await self._call_turn_off([eid])
            self._remove_managed(eid)
            self._last_turn_off_time = datetime.now(timezone.utc)
            self._last_turn_off_delay_sec = self._delay_seconds_for_entity(eid, learned_kw)
            _LOGGER.debug("Wasting budget: turned off %s (not in target)", eid)
            if decision_context is not None:
                await self._log_action(
                    "INFO",
                    "consumer_turned_off",
                    _action_summary_entity_off(
                        decision_context, eid, "wasting_not_in_target"
                    ),
                    decision_context.merge_action_context(
                        reason_code="wasting_not_in_target", entity_id=eid
                    ),
                )
            return

        if suppress_turn_ons:
            return

        for eid in ordered:
            if eid not in learned_kw:
                continue
            if eid not in target:
                continue
            if is_on(eid):
                continue
            if self._is_under_discharge_shed_cooldown(eid, now_utc=now_utc):
                continue
            if not self._can_turn_on_after_delay(eid, learned_kw):
                continue
            await self._turn_on_consumer(eid)
            self._append_managed(eid)
            self._last_turn_on_time = datetime.now(timezone.utc)
            self._last_turn_on_delay_sec = self._delay_seconds_for_entity(eid, learned_kw)
            _LOGGER.debug("Wasting budget: turned on %s (target)", eid)
            if decision_context is not None:
                await self._log_action(
                    "INFO",
                    "consumer_turned_on",
                    _action_summary_entity_on(
                        decision_context, eid, "wasting_target"
                    ),
                    decision_context.merge_action_context(
                        reason_code="wasting_target", entity_id=eid
                    ),
                )
            if self._schedule_consumer_learn:
                self._schedule_consumer_learn(eid)
            return

        candidate = next_unlearned_for_sampling(
            ordered,
            learned_kw,
            target,
            discharge_headroom_kw=ctx.discharge_headroom_kw,
            marginal_battery_per_kw=ctx.marginal_battery_per_kw,
            unmeasurable_entity_ids=ctx.unmeasurable_entity_ids,
        )
        if candidate and not is_on(candidate):
            if not self._is_under_discharge_shed_cooldown(candidate, now_utc=now_utc):
                if self._can_turn_on_after_delay(candidate, learned_kw):
                    await self._turn_on_consumer(candidate)
                    self._append_managed(candidate)
                    self._last_turn_on_time = datetime.now(timezone.utc)
                    self._last_turn_on_delay_sec = self._delay_seconds_for_entity(
                        candidate, learned_kw
                    )
                    _LOGGER.debug(
                        "Wasting budget: turned on %s (learn path)", candidate
                    )
                    if decision_context is not None:
                        await self._log_action(
                            "INFO",
                            "consumer_turned_on",
                            _action_summary_entity_on(
                                decision_context,
                                candidate,
                                "wasting_learn_path",
                            ),
                            decision_context.merge_action_context(
                                reason_code="wasting_learn_path",
                                entity_id=candidate,
                            ),
                        )
                    if self._schedule_consumer_learn:
                        self._schedule_consumer_learn(candidate)

    async def _apply_wasting_fallback(
        self,
        consumers: list[str],
        house_consumption_entity_id: str | None,
        learned_kw: dict[str, float],
        *,
        suppress_turn_ons: bool = False,
        decision_context: DecisionContext | None = None,
    ) -> None:
        """Legacy one-per-delay when no wasting_context provided."""
        if suppress_turn_ons:
            return
        if not consumers or not self._can_turn_on_after_delay(
            consumers[0], learned_kw
        ):
            return
        for entity_id in consumers:
            state = self.hass.states.get(entity_id)
            if state and state.state != "on":
                if not self._domain(entity_id):
                    continue
                await self._turn_on_consumer(entity_id)
                self._last_turn_on_time = datetime.now(timezone.utc)
                self._last_turn_on_delay_sec = self._delay_seconds_for_entity(
                    entity_id, learned_kw
                )
                self._append_managed(entity_id)
                _LOGGER.debug("Turned on consumer (fallback): %s", entity_id)
                if decision_context is not None:
                    await self._log_action(
                        "INFO",
                        "consumer_turned_on",
                        _action_summary_entity_on(
                            decision_context, entity_id, "wasting_fallback"
                        ),
                        decision_context.merge_action_context(
                            reason_code="wasting_fallback", entity_id=entity_id
                        ),
                    )
                if self._schedule_consumer_learn:
                    self._schedule_consumer_learn(entity_id)
                return

    async def discharge_over_limit_turn_off_one(
        self,
        consumer_entity_ids: list[str],
        learned_kw: dict[str, float] | None = None,  # unused; kept for call-site compatibility
        *,
        decision_context: DecisionContext | None = None,
    ) -> None:
        """Turn off one on-consumer: lowest config priority first (inverse of turn-on order)."""
        consumers = self._consumer_entity_ids(consumer_entity_ids or [])
        on_list = [
            eid
            for eid in consumers
            if (st := self.hass.states.get(eid)) and st.state == "on"
        ]
        if not on_list:
            if decision_context is not None:
                await self._log_action(
                    "INFO",
                    "discharge_over_limit_no_action",
                    _action_summary_discharge_noop(decision_context),
                    decision_context.merge_action_context(
                        reason_code="discharge_over_limit_no_targets"
                    ),
                )
            return
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
            self.note_discharge_shed(entity_id)
            _LOGGER.debug(
                "Discharge over limit: turned off one consumer %s",
                entity_id,
            )
            if decision_context is not None:
                d = decision_context.to_flat_log_dict()
                summary = (
                    f"Turn off {entity_id} | discharge_over_limit | "
                    f"dis={d['battery_discharge_kw']} ceiling={d['discharge_ceiling_kw']}"
                )[:200]
                await self._log_action(
                    "WARN",
                    "consumer_turned_off",
                    summary,
                    decision_context.merge_action_context(
                        reason_code="discharge_over_limit", entity_id=entity_id
                    ),
                )
