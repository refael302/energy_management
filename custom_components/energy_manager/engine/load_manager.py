"""
Load manager – ACTIONS: turn on/off consumer switches (and optional lights) by priority.
Replicates YAML automation "[חבילת אנרגיה] פעולות – הפעלה/כיבוי צרכנים לפי מצב"
and discharge_over_limit_turn_off_one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    SYSTEM_MODE_EMERGENCY_SAVING,
    SYSTEM_MODE_SAVING,
    SYSTEM_MODE_WASTING,
)

_LOGGER = logging.getLogger(__name__)

# Entities that can be used as consumers (turn_on/turn_off).
CONSUMER_DOMAINS = ("switch", "input_boolean")

# Domains that can be turned off in super-saving (light, switch, input_boolean, fan).
SUPER_SAVING_TURN_OFF_DOMAINS = ("light", "switch", "input_boolean", "fan")


@dataclass
class LoadManagerState:
    """State for load manager: consumers turned on by wasting (to turn off when Off)."""

    consumers_turned_on_by_wasting: list[str] = field(default_factory=list)


class LoadManager:
    """
    Applies actions based on system_mode only (no extra input gates).
    - wasting: turn on one consumer per delay_minutes.
    - normal (Off): turn off one consumer per delay_minutes (LIFO, those turned on by wasting).
    - saving: turn off all consumer switches (and optionally lights when super_saving).
    - emergency_saving: like saving with super_saving (all consumers + lights).
    Discharge over limit: when discharge_state becomes max, turn off one consumer (reverse order).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        consumer_entity_ids: list[str],
        lights_entity_ids: list[str],
        delay_minutes: int,
    ) -> None:
        self.hass = hass
        self.consumer_entity_ids = consumer_entity_ids or []
        self.lights_entity_ids = lights_entity_ids or []
        self.delay_minutes = delay_minutes
        self.state = LoadManagerState()
        self._last_turn_on_time: datetime | None = None
        self._last_turn_off_time: datetime | None = None

    def _consumer_entity_ids(self, entity_ids: list[str]) -> list[str]:
        """Return only switch/input_boolean entities (consumers we can turn on/off)."""
        return [
            eid
            for eid in entity_ids
            if eid.split(".", 1)[0] in CONSUMER_DOMAINS
        ]

    async def apply_mode(
        self,
        system_mode: str,
        super_saving: bool = False,
    ) -> None:
        """
        Apply actions for the given system mode.
        super_saving: when True (very low battery), also turn off lights.
        """
        consumers = self._consumer_entity_ids(self.consumer_entity_ids)
        if system_mode == SYSTEM_MODE_WASTING:
            await self._apply_wasting_once(consumers)
        elif system_mode == SYSTEM_MODE_EMERGENCY_SAVING:
            await self._apply_saving(consumers, super_saving=True)
        elif system_mode == SYSTEM_MODE_SAVING:
            await self._apply_saving(consumers, super_saving)
        else:
            await self._apply_off_once()

    def _domain(self, entity_id: str) -> str | None:
        """Return entity domain if it is a supported consumer, else None."""
        d = entity_id.split(".", 1)[0] if "." in entity_id else ""
        return d if d in CONSUMER_DOMAINS else None

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

    def _can_turn_off_another(self) -> bool:
        """True if at least delay_minutes have passed since last turn_off (for normal mode)."""
        if self._last_turn_off_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_turn_off_time).total_seconds()
        return elapsed >= self.delay_minutes * 60

    async def _apply_off_once(self) -> None:
        """Turn off one consumer that was turned on by wasting (LIFO), per delay_minutes."""
        to_consider = [
            eid
            for eid in self.state.consumers_turned_on_by_wasting
            if self._domain(eid)
        ]
        if not to_consider or not self._can_turn_off_another():
            return
        entity_id = to_consider[-1]
        self.state.consumers_turned_on_by_wasting.remove(entity_id)
        await self._call_turn_off([entity_id])
        self._last_turn_off_time = datetime.now(timezone.utc)
        _LOGGER.debug("Turned off (wasting list, one): %s", entity_id)

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

    def _can_turn_on_another(self) -> bool:
        """True if at least delay_minutes have passed since last turn_on."""
        if self._last_turn_on_time is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_turn_on_time).total_seconds()
        return elapsed >= self.delay_minutes * 60

    async def _apply_wasting_once(self, consumers: list[str]) -> None:
        """
        When delay elapsed, turn on the first consumer that is off.
        Called periodically by coordinator; one consumer per delay_minutes.
        """
        if not consumers or not self._can_turn_on_another():
            return
        for entity_id in consumers:
            state = self.hass.states.get(entity_id)
            if state and state.state != "on":
                domain = self._domain(entity_id)
                if domain:
                    await self.hass.services.async_call(
                        domain,
                        "turn_on",
                        {"entity_id": entity_id},
                        blocking=True,
                    )
                self._last_turn_on_time = datetime.now(timezone.utc)
                if entity_id not in self.state.consumers_turned_on_by_wasting:
                    self.state.consumers_turned_on_by_wasting.append(entity_id)
                _LOGGER.debug("Turned on consumer: %s", entity_id)
                return

    async def discharge_over_limit_turn_off_one(
        self, consumer_entity_ids: list[str]
    ) -> None:
        """Turn off one consumer (reverse order) when discharge is over limit."""
        consumers = self._consumer_entity_ids(consumer_entity_ids or [])
        rev = list(reversed(consumers))
        for entity_id in rev:
            state = self.hass.states.get(entity_id)
            if state and state.state == "on":
                domain = self._domain(entity_id)
                if domain:
                    await self.hass.services.async_call(
                        domain,
                        "turn_off",
                        {"entity_id": entity_id},
                        blocking=True,
                    )
                    _LOGGER.debug(
                        "Discharge over limit: turned off one consumer %s",
                        entity_id,
                    )
                    return
