"""
Append-only TXT operation log per config entry (schema + anti-spam + safe I/O).

Lines are grep-friendly: TIME LEVEL CATEGORY event summary [key=value ...]
See module docstring in const / plan for event codes used by callers.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

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


def _context_kv(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    parts: list[str] = []
    for key in sorted(context.keys()):
        val = context[key]
        if val is None:
            continue
        s = _clamp(str(val), 120)
        parts.append(f"{key}={s}")
    out = " ".join(parts)
    return _clamp(out, INTEGRATION_LOG_CONTEXT_MAX_LEN)


def _dedupe_key(category: str, event: str, context: dict[str, Any] | None) -> str:
    ctx = context or {}
    entity = str(ctx.get("entity_id", ""))
    reason = str(ctx.get("reason_code", ""))
    return f"{category}|{event}|{entity}|{reason}"


def _format_line(
    ts_iso: str,
    level: str,
    category: str,
    event: str,
    summary: str,
    context: dict[str, Any] | None,
) -> str:
    summary_c = _clamp(summary, INTEGRATION_LOG_SUMMARY_MAX_LEN)
    ctx_s = _context_kv(context)
    parts = [ts_iso, level, category, event, summary_c]
    if ctx_s:
        parts.append(ctx_s)
    return " ".join(parts)


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
    Append one logical line to the per-entry ops log. Never raises to callers.

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

        if category in INTEGRATION_LOG_DEDUPE_CATEGORIES:
            last_t = _last_write_mono.get(ek)
            if last_t is not None and (now_mono - last_t) < INTEGRATION_LOG_DEDUPE_WINDOW_SEC:
                _suppressed[ek] = _suppressed.get(ek, 0) + 1
                return
            sup = _suppressed.pop(ek, 0)
            if sup > 0:
                from homeassistant.util import dt as dt_util

                ts_sup = dt_util.now().isoformat()
                extra_lines.append(
                    _format_line(
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

        from homeassistant.util import dt as dt_util

        ts_iso = dt_util.now().isoformat()
        main = _format_line(ts_iso, level, category, event, summary, ctx)
        all_lines = extra_lines + [main]
        path = _ops_log_path(hass, entry_id)
        await hass.async_add_executor_job(_append_lines_sync, path, entry_id, all_lines)
        _last_write_mono[ek] = now_mono
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("integration_log async_log_event failed: %s", err)
