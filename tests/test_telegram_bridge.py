"""Tests for Telegram alert filtering and rate limits."""

from __future__ import annotations

from energy_manager.const import (
    TELEGRAM_BURST_MAX_MESSAGES,
    TELEGRAM_NOTIFY_ALL,
    TELEGRAM_NOTIFY_EMERGENCY,
)
from energy_manager import telegram_bridge as tg


def _st(notify_mode: str) -> dict:
    return {
        "notify_mode": notify_mode,
        "levels": {"INFO", "WARN", "ERROR"},
        "categories": {"MODE", "ACTION", "FORECAST", "LEARN", "SYSTEM"},
        "deny_events": set(),
    }


def test_emergency_alert_warn_and_error():
    assert tg.is_emergency_alert({"level": "WARN", "event": "x"})
    assert tg.is_emergency_alert({"level": "ERROR", "event": "x"})
    assert not tg.is_emergency_alert({"level": "INFO", "event": "consumer_turned_on"})


def test_emergency_alert_mode_change():
    rec = {
        "level": "INFO",
        "event": "system_mode_changed",
        "context": {"from_mode": "normal", "to_mode": "emergency_saving"},
    }
    assert tg.is_emergency_alert(rec)


def test_passes_filters_all_vs_emergency():
    info_rec = {
        "level": "INFO",
        "category": "ACTION",
        "event": "consumer_turned_on",
    }
    warn_rec = {"level": "WARN", "category": "FORECAST", "event": "open_meteo_timeout"}
    assert tg._passes_filters(info_rec, _st(TELEGRAM_NOTIFY_ALL))
    assert not tg._passes_filters(info_rec, _st(TELEGRAM_NOTIFY_EMERGENCY))
    assert tg._passes_filters(warn_rec, _st(TELEGRAM_NOTIFY_EMERGENCY))


def test_rate_ok_dedupes_identical_fingerprint():
    tg._telegram_last_sent_mono.clear()
    fp = ("WARN", "FORECAST", "ev", "summary", ())
    assert tg._rate_ok("entry1", fp, 60.0)
    assert not tg._rate_ok("entry1", fp, 60.0)


def test_burst_ok_caps_messages_per_window():
    tg._telegram_burst_times.clear()
    entry = "burst_test"
    for _ in range(TELEGRAM_BURST_MAX_MESSAGES):
        assert tg._burst_ok(entry)
    assert not tg._burst_ok(entry)


def test_telegram_settings_notify_mode_default():
    st = tg._telegram_settings({"telegram_notify_mode": TELEGRAM_NOTIFY_EMERGENCY})
    assert st["notify_mode"] == TELEGRAM_NOTIFY_EMERGENCY


def test_telegram_settings_legacy_levels_infer_emergency():
    st = tg._telegram_settings({"telegram_out_levels": ["WARN", "ERROR"]})
    assert st["notify_mode"] == TELEGRAM_NOTIFY_EMERGENCY


def test_default_deny_blocks_no_effect():
    st = tg._telegram_settings({})
    rec = {"level": "WARN", "event": "consumer_turn_on_no_effect"}
    assert not tg._passes_filters(rec, st)


def test_default_deny_allows_mode_change():
    st = tg._telegram_settings({})
    rec = {"level": "INFO", "event": "system_mode_changed"}
    assert tg._passes_filters(rec, st)
