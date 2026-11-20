"""Anti-flap: min-on / min-off cooldowns for consumer cycling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Any
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from energy_manager.const import (
    CONSUMER_MIN_OFF_MINUTES,
    CONSUMER_MIN_ON_MINUTES,
    CONSUMER_MIN_ON_UNLEARNED_MINUTES,
    DISCHARGE_SHED_COOLDOWN_SEC,
    SYSTEM_MODE_NORMAL_WASTING_DWELL_SEC,
)


def test_antiflap_constants() -> None:
    """Boiler-like loads need long on/off floors; dwell reduces mode flap."""
    assert CONSUMER_MIN_ON_MINUTES >= 20
    assert CONSUMER_MIN_ON_UNLEARNED_MINUTES >= 20
    assert CONSUMER_MIN_OFF_MINUTES >= 15
    assert DISCHARGE_SHED_COOLDOWN_SEC == CONSUMER_MIN_OFF_MINUTES * 60
    assert SYSTEM_MODE_NORMAL_WASTING_DWELL_SEC >= 300


def _load_load_manager():
    """Import load_manager with lightweight HA / log mocks (no full HA runtime)."""
    if "energy_manager.engine.load_manager" in sys.modules:
        return sys.modules["energy_manager.engine.load_manager"]

    root = Path(__file__).resolve().parents[1]
    em_root = root / "custom_components" / "energy_manager"

    ha_exc = ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    ha_exc.HomeAssistantError = HomeAssistantError
    sys.modules["homeassistant.exceptions"] = ha_exc

    async def _noop_log(*_a: Any, **_k: Any) -> None:
        return None

    log_mod = ModuleType("energy_manager.integration_log")
    log_mod.async_log_event = _noop_log
    sys.modules["energy_manager.integration_log"] = log_mod

    dc_mod = ModuleType("energy_manager.decision_context")

    class DecisionContext:  # noqa: D101
        pass

    dc_mod.DecisionContext = DecisionContext
    sys.modules["energy_manager.decision_context"] = dc_mod

    path = em_root / "engine" / "load_manager.py"
    spec = importlib.util.spec_from_file_location(
        "energy_manager.engine.load_manager", path
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["energy_manager.engine.load_manager"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeHass:
    def __init__(self) -> None:
        self.states = _FakeStates()
        self.services = _FakeServices(self.states)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []


class _FakeStates:
    def __init__(self) -> None:
        self._data: dict[str, SimpleNamespace] = {}

    def set(self, entity_id: str, state: str) -> None:
        self._data[entity_id] = SimpleNamespace(state=state)

    def get(self, entity_id: str) -> SimpleNamespace | None:
        return self._data.get(entity_id)


class _FakeServices:
    def __init__(self, states: _FakeStates) -> None:
        self._states = states
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def async_call(
        self, domain: str, service: str, data: dict[str, Any], blocking: bool = False
    ) -> None:
        self.calls.append((domain, service, data))
        eid = data.get("entity_id")
        eids = eid if isinstance(eid, list) else [eid]
        for e in eids:
            if e and service == "turn_on":
                self._states.set(e, "on")
            elif e and service == "turn_off":
                self._states.set(e, "off")


@pytest.fixture
def lm_mod():
    return _load_load_manager()


def test_note_turn_off_cooldown_blocks_then_expires(lm_mod) -> None:
    hass = _FakeHass()
    mgr = lm_mod.LoadManager(hass, ["switch.dvd"], [], delay_minutes=5)
    eid = "switch.dvd"
    mgr.note_turn_off_cooldown(eid)
    now = datetime.now(timezone.utc)
    assert mgr._is_under_turn_on_cooldown(eid, now_utc=now) is True
    later = now + timedelta(minutes=CONSUMER_MIN_OFF_MINUTES, seconds=1)
    mgr._purge_expired_turn_on_blocks(later)
    assert mgr._is_under_turn_on_cooldown(eid, now_utc=later) is False


def test_wasting_not_in_target_sets_min_off_cooldown(lm_mod) -> None:
    async def _run() -> None:
        hass = _FakeHass()
        eid = "switch.dvd"
        hass.states.set(eid, "on")
        mgr = lm_mod.LoadManager(hass, [eid], [], delay_minutes=5)
        # Pretend we turned it on long enough ago to pass min-on.
        mgr._integration_turn_on_at_utc[eid] = datetime.now(timezone.utc) - timedelta(
            minutes=CONSUMER_MIN_ON_MINUTES + 1
        )
        mgr._append_managed(eid)
        ctx = lm_mod.WastingContext(
            consumers_ordered=[eid],
            learned_kw={eid: 2.5},
            learned_target=set(),  # not in target → turn off
            discharge_headroom_kw=10.0,
            marginal_battery_per_kw=1.0,
        )
        await mgr._apply_wasting_budget(ctx, None)
        assert hass.states.get(eid).state == "off"
        assert mgr._is_under_turn_on_cooldown(
            eid, now_utc=datetime.now(timezone.utc)
        )

        # Even if budget re-includes the consumer, cooldown blocks turn-on.
        hass.states.set(eid, "off")
        ctx2 = lm_mod.WastingContext(
            consumers_ordered=[eid],
            learned_kw={eid: 2.5},
            learned_target={eid},
            discharge_headroom_kw=10.0,
            marginal_battery_per_kw=1.0,
        )
        await mgr._apply_wasting_budget(ctx2, None)
        assert hass.states.get(eid).state == "off"
        assert not any(c[1] == "turn_on" for c in hass.services.calls)

    asyncio.run(_run())


def test_discharge_shed_uses_min_off_floor(lm_mod) -> None:
    hass = _FakeHass()
    mgr = lm_mod.LoadManager(hass, ["switch.dvd"], [], delay_minutes=5)
    mgr.note_discharge_shed("switch.dvd")
    until = mgr._turn_on_blocked_until_utc["switch.dvd"]
    remaining = (until - datetime.now(timezone.utc)).total_seconds()
    assert remaining >= DISCHARGE_SHED_COOLDOWN_SEC - 2
