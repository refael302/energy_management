"""
Append-only TXT operation log per config entry (schema + anti-spam + safe I/O).

Schema 2 (human-readable):
  Line 1: TIME | LEVEL | CATEGORY | event | summary
  Line 2 (optional):   | key=value | key=value ...  (context; keys in stable priority order)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

# Context keys emitted in this order first (then remaining keys, sorted); improves readability vs raw sort.
_CONTEXT_KEY_PRIORITY: tuple[str, ...] = (
    "reason_code",
    "entity_id",
    "from_mode",
    "to_mode",
    "from_strategy",
    "to_strategy",
    "from_available",
    "to_available",
    "mode_reason",
    "strategy_reason",
    "error",
    "learned_kw",
    "samples_used",
    "count",
    "suppressed_count",
    "parent_event",
)

from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    INTEGRATION_LOG_CONTEXT_MAX_LEN,
    INTEGRATION_LOG_DEDUPE_CATEGORIES,
    INTEGRATION_LOG_DEDUPE_WINDOW_SEC,
    INTEGRATION_LOG_ENABLED,
    INTEGRATION_LOG_MAX_BYTES,
    INTEGRATION_LOG_SCHEMA_VERSION,
    INTEGRATION_LOG_SUMMARY_MAX_LEN,
)


def _notify_coordinator_integration_alerts(
    hass: HomeAssistant, entry_id: str, records: list[dict[str, Any]]
) -> None:
    """Push structured log records to the coordinator in-memory ring (no circular import)."""
    if not records:
        return
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return
    coord = domain_data.get(entry_id)
    push = getattr(coord, "push_integration_alert", None)
    if not callable(push):
        return
    for rec in records:
        try:
            push(rec)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("push_integration_alert failed: %s", err)

_LOGGER = logging.getLogger(__name__)

_VALID_LEVELS = frozenset({"INFO", "WARN", "ERROR"})
_VALID_CATEGORIES = frozenset({"MODE", "ACTION", "FORECAST", "LEARN", "SYSTEM"})

# (entry_id, dedupe_key) -> last_write_monotonic
_last_write_mono: dict[tuple[str, str], float] = {}
# (entry_id, dedupe_key) -> suppressed count since last successful write
_suppressed: dict[tuple[str, str], int] = {}


def _ops_log_path(hass: HomeAssistant, entry_id: str) -> str:
    base = hass.config.config_dir
    return os.path.join(base, "energy_manager_logs", f"ops_{entry_id}.txt")


def _clamp(text: str, max_len: int) -> str:
    t = text.replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    if max_len < 2:
        return t[:max_len]
    return t[: max_len - 1] + "…"


def _ordered_context_pairs(context: dict[str, Any]) -> list[tuple[str, str]]:
    """Key=value pairs: priority keys first, then any other keys alphabetically."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for key in _CONTEXT_KEY_PRIORITY:
        if key not in context:
            continue
        val = context[key]
        if val is None:
            continue
        seen.add(key)
        out.append((key, _clamp(str(val).replace("|", "/"), 120)))
    for key in sorted(k for k in context if k not in seen):
        val = context[key]
        if val is None:
            continue
        out.append((key, _clamp(str(val).replace("|", "/"), 120)))
    return out


def _dedupe_key(category: str, event: str, context: dict[str, Any] | None) -> str:
    ctx = context or {}
    entity = str(ctx.get("entity_id", ""))
    reason = str(ctx.get("reason_code", ""))
    return f"{category}|{event}|{entity}|{reason}"


def _format_event_lines(
    ts_iso: str,
    level: str,
    category: str,
    event: str,
    summary: str,
    context: dict[str, Any] | None,
) -> list[str]:
    """Schema 2: main line with | separators; optional second line for context."""
    summary_c = _clamp(
        summary.replace("\n", " ").replace("|", "/"), INTEGRATION_LOG_SUMMARY_MAX_LEN
    )
    event_c = event.replace("|", "/").replace("\n", " ").strip()
    main = (
        f"{ts_iso} | {level} | {category} | {event_c} | {summary_c}"
    )
    lines = [main]
    pairs = _ordered_context_pairs(context) if context else []
    if pairs:
        body = " | ".join(f"{k}={v}" for k, v in pairs)
        body = _clamp(body, INTEGRATION_LOG_CONTEXT_MAX_LEN)
        lines.append(f"  | {body}")
    return lines


def _append_lines_sync(path: str, entry_id: str, lines: list[str]) -> None:
    """Blocking I/O; run via hass.async_add_executor_job."""
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        if os.path.isfile(path) and os.path.getsize(path) > INTEGRATION_LOG_MAX_BYTES:
            bak = f"{path}.1"
            if os.path.isfile(bak):
                os.remove(bak)
            os.replace(path, bak)
        new_file = not os.path.isfile(path) or os.path.getsize(path) == 0
        chunks: list[str] = []
        if new_file:
            chunks.append(
                f"# schema={INTEGRATION_LOG_SCHEMA_VERSION} entry_id={entry_id} domain={DOMAIN}\n"
            )
        for line in lines:
            chunks.append(line if line.endswith("\n") else f"{line}\n")
        with open(path, "a", encoding="utf-8", errors="replace") as handle:
            handle.writelines(chunks)
    except OSError as err:
        _LOGGER.debug("integration_log append failed: %s", err)


async def async_log_event(
    hass: HomeAssistant,
    entry_id: str,
    level: str,
    category: str,
    event: str,
    summary: str,
    context: dict[str, Any] | None = None,
) -> None:
    """
    Append one logical event to the per-entry ops log (main line; optional context line).
    Never raises to callers.

    level: INFO | WARN | ERROR
    category: MODE | ACTION | FORECAST | LEARN | SYSTEM
    event: stable snake_case code (e.g. system_mode_changed)
    """
    if not INTEGRATION_LOG_ENABLED or not entry_id:
        return
    try:
        if level not in _VALID_LEVELS or category not in _VALID_CATEGORIES:
            _LOGGER.debug("integration_log: invalid level/category skipped")
            return
        ctx = dict(context) if context else None
        now_mono = time.monotonic()
        dk = _dedupe_key(category, event, ctx)
        ek = (entry_id, dk)

        extra_lines: list[str] = []
        records_to_push: list[dict[str, Any]] = []

        if category in INTEGRATION_LOG_DEDUPE_CATEGORIES:
            last_t = _last_write_mono.get(ek)
            if last_t is not None and (now_mono - last_t) < INTEGRATION_LOG_DEDUPE_WINDOW_SEC:
                _suppressed[ek] = _suppressed.get(ek, 0) + 1
                return
            sup = _suppressed.pop(ek, 0)
            if sup > 0:
                from homeassistant.util import dt as dt_util

                ts_sup = dt_util.now().isoformat()
                extra_lines.extend(
                    _format_event_lines(
                        ts_sup,
                        "INFO",
                        category,
                        "events_suppressed",
                        f"Repeated {event} suppressed while throttling",
                        {
                            "reason_code": "dedupe",
                            "suppressed_count": str(sup),
                            "parent_event": event,
                        },
                    )
                )
                records_to_push.append(
                    {
                        "ts_iso": ts_sup,
                        "level": "INFO",
                        "category": category,
                        "event": "events_suppressed",
                        "summary": f"Repeated {event} suppressed while throttling",
                        "context": {
                            "reason_code": "dedupe",
                            "suppressed_count": str(sup),
                            "parent_event": event,
                        },
                    }
                )

        from homeassistant.util import dt as dt_util

        ts_iso = dt_util.now().isoformat()
        all_lines = extra_lines + _format_event_lines(
            ts_iso, level, category, event, summary, ctx
        )
        path = _ops_log_path(hass, entry_id)
        await hass.async_add_executor_job(_append_lines_sync, path, entry_id, all_lines)
        _last_write_mono[ek] = now_mono
        records_to_push.append(
            {
                "ts_iso": ts_iso,
                "level": level,
                "category": category,
                "event": event,
                "summary": summary,
                "context": ctx if ctx else {},
            }
        )
        _notify_coordinator_integration_alerts(hass, entry_id, records_to_push)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("integration_log async_log_event failed: %s", err)
