"""Tests for human-readable Telegram message formatting."""

from __future__ import annotations

from energy_manager import telegram_messages as tm


class _FakeState:
    def __init__(self, friendly_name: str) -> None:
        self.attributes = {"friendly_name": friendly_name}


class _FakeHass:
    def __init__(self, names: dict[str, str]) -> None:
        self._names = names

    @property
    def states(self):
        return self

    def get(self, entity_id: str):
        name = self._names.get(entity_id)
        return _FakeState(name) if name else None


def test_system_mode_changed_hebrew():
    rec = {
        "level": "INFO",
        "event": "system_mode_changed",
        "ts_iso": "2026-06-23T00:07:55.547855+03:00",
        "context": {
            "from_mode": "normal",
            "to_mode": "wasting",
            "battery_soc_percent": "72",
            "mode_reason": "Morning drain to floor before PV",
        },
    }
    text = tm.format_telegram_alert(None, rec)
    assert "שינוי מצב מערכת" in text
    assert "בזבוז עודף" in text
    assert "72%" in text
    assert "Morning drain" in text
    assert "consumer_turn_on_no_effect" not in text


def test_consumer_on_uses_friendly_name():
    hass = _FakeHass({"switch.dvd": "DVD"})
    rec = {
        "level": "INFO",
        "event": "consumer_turned_on",
        "ts_iso": "2026-06-23T08:00:00+03:00",
        "context": {
            "entity_id": "switch.dvd",
            "system_mode": "wasting",
            "battery_soc_percent": "80",
        },
    }
    text = tm.format_telegram_alert(hass, rec)
    assert "הודלק צרכן" in text
    assert "DVD (switch.dvd)" in text


def test_forecast_warn_clear():
    rec = {
        "level": "WARN",
        "event": "open_meteo_timeout",
        "ts_iso": "2026-06-23T12:00:00+03:00",
        "summary": "technical",
        "context": {"battery_soc_percent": "50"},
    }
    text = tm.format_telegram_alert(None, rec)
    assert "בעיה בתחזית" in text
    assert "תם הזמן" in text
