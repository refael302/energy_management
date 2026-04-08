"""
Telegram Bot API (direct): mirror ops-log alerts and optional command polling.

Does not use Home Assistant notify.* — see integration plan.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant

from .const import (
    CONF_TELEGRAM_BOT_TOKEN,
    CONF_TELEGRAM_CHAT_IDS,
    CONF_TELEGRAM_COMMANDS_ENABLED,
    CONF_TELEGRAM_ENABLED,
    CONF_TELEGRAM_EVENTS_DENYLIST,
    CONF_TELEGRAM_MIN_INTERVAL_SEC,
    CONF_TELEGRAM_OUT_CATEGORIES,
    CONF_TELEGRAM_OUT_LEVELS,
    DATA_INTEGRATION_ALERT_LAST,
    DOMAIN,
    OPS_LOG_CATEGORIES,
    OPS_LOG_LEVELS,
    TELEGRAM_MESSAGE_MAX_LEN,
    TELEGRAM_POLL_IDLE_SEC,
)

_LOGGER = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

# (entry_id, fingerprint) -> last monotonic time sent
_telegram_last_sent_mono: dict[tuple[str, tuple[Any, ...]], float] = {}


def _merged_entry_config(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return {}
    return {**entry.data, **(entry.options or {})}


def _telegram_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    cats = cfg.get(CONF_TELEGRAM_OUT_CATEGORIES)
    if not isinstance(cats, list) or not cats:
        cats = list(OPS_LOG_CATEGORIES)
    cats_set = {str(c).upper() for c in cats}
    levels = cfg.get(CONF_TELEGRAM_OUT_LEVELS)
    if not isinstance(levels, list) or not levels:
        levels = list(OPS_LOG_LEVELS)
    levels_set = {str(l).upper() for l in levels}
    deny_raw = str(cfg.get(CONF_TELEGRAM_EVENTS_DENYLIST) or "").strip()
    deny = {p.strip().lower() for p in deny_raw.split(",") if p.strip()}
    try:
        min_iv = float(cfg.get(CONF_TELEGRAM_MIN_INTERVAL_SEC, 0) or 0)
    except (TypeError, ValueError):
        min_iv = 0.0
    return {
        "enabled": bool(cfg.get(CONF_TELEGRAM_ENABLED)),
        "token": str(cfg.get(CONF_TELEGRAM_BOT_TOKEN) or "").strip(),
        "chat_ids": _parse_chat_ids(str(cfg.get(CONF_TELEGRAM_CHAT_IDS) or "")),
        "categories": cats_set,
        "levels": levels_set,
        "deny_events": deny,
        "min_interval_sec": max(0.0, min_iv),
        "commands": bool(cfg.get(CONF_TELEGRAM_COMMANDS_ENABLED)),
    }


def _parse_chat_ids(raw: str) -> list[str]:
    out: list[str] = []
    for part in raw.replace(";", ",").split(","):
        p = part.strip()
        if p:
            out.append(p)
    return out


def _alert_fingerprint(rec: dict[str, Any]) -> tuple[Any, ...]:
    ctx = rec.get("context")
    if not isinstance(ctx, dict):
        ctx = {}
    ctx_items = tuple(sorted((k, str(v)) for k, v in sorted(ctx.items())))
    return (
        str(rec.get("level", "")),
        str(rec.get("category", "")),
        str(rec.get("event", "")),
        str(rec.get("summary", "")),
        ctx_items,
    )


def _passes_filters(rec: dict[str, Any], st: dict[str, Any]) -> bool:
    level = str(rec.get("level", "")).upper()
    category = str(rec.get("category", "")).upper()
    event = str(rec.get("event", "")).lower()
    if level not in st["levels"]:
        return False
    if category not in st["categories"]:
        return False
    if event and event in st["deny_events"]:
        return False
    return True


def _rate_ok(entry_id: str, fp: tuple[Any, ...], min_sec: float) -> bool:
    if min_sec <= 0:
        return True
    key = (entry_id, fp)
    now = time.monotonic()
    last = _telegram_last_sent_mono.get(key)
    if last is not None and (now - last) < min_sec:
        return False
    _telegram_last_sent_mono[key] = now
    return True


def _format_ops_message(rec: dict[str, Any]) -> str:
    seq = rec.get("seq", "")
    ts = rec.get("ts_iso", "")
    level = rec.get("level", "")
    cat = rec.get("category", "")
    ev = rec.get("event", "")
    summary = rec.get("summary", "")
    lines = [
        f"Energy Manager #{seq}",
        f"{ts} [{level}] {cat} · {ev}",
        str(summary),
    ]
    ctx = rec.get("context")
    if isinstance(ctx, dict) and ctx:
        try:
            ctx_s = json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            ctx_s = str(ctx)
        if ctx_s:
            lines.append(ctx_s)
    text = "\n".join(lines)
    if len(text) > TELEGRAM_MESSAGE_MAX_LEN:
        text = text[: TELEGRAM_MESSAGE_MAX_LEN - 1] + "…"
    return text


async def _post_json(
    session: aiohttp.ClientSession, url: str, payload: dict[str, Any]
) -> tuple[bool, str]:
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            body = await resp.text()
            if resp.status != 200:
                return False, f"HTTP {resp.status}: {body[:200]}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return False, "invalid JSON"
            if not data.get("ok"):
                return False, str(data.get("description", body))[:200]
            return True, ""
    except TimeoutError:
        return False, "timeout"
    except aiohttp.ClientError as err:
        return False, str(err)[:200]


async def async_send_ops_record(
    hass: HomeAssistant,
    entry_id: str,
    record: dict[str, Any],
) -> None:
    cfg = _merged_entry_config(hass, entry_id)
    st = _telegram_settings(cfg)
    if not st["enabled"] or not st["token"] or not st["chat_ids"]:
        return
    if not _passes_filters(record, st):
        return
    fp = _alert_fingerprint(record)
    if not _rate_ok(entry_id, fp, st["min_interval_sec"]):
        return
    text = _format_ops_message(record)
    url = f"{TELEGRAM_API}/bot{st['token']}/sendMessage"
    payload_base: dict[str, Any] = {"text": text, "disable_web_page_preview": True}
    async with aiohttp.ClientSession() as session:
        for chat_id in st["chat_ids"]:
            payload = {**payload_base, "chat_id": chat_id}
            ok, err = await _post_json(session, url, payload)
            if not ok:
                _LOGGER.warning("Telegram sendMessage failed: %s", err)


def schedule_ops_log_telegram(
    hass: HomeAssistant, entry_id: str, record: dict[str, Any]
) -> None:
    """Fire-and-forget from sync context (e.g. coordinator.push_integration_alert)."""
    cfg = _merged_entry_config(hass, entry_id)
    st = _telegram_settings(cfg)
    if not st["enabled"] or not st["token"] or not st["chat_ids"]:
        return

    async def _run() -> None:
        await async_send_ops_record(hass, entry_id, record)

    hass.async_create_background_task(
        _run(),
        f"energy_manager_telegram_send_{entry_id}",
    )


def _allowed_chat(st: dict[str, Any], chat_id: int | str) -> bool:
    sid = str(chat_id).strip()
    return sid in set(st["chat_ids"])


def _status_text(hass: HomeAssistant, entry_id: str) -> str:
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return "Energy Manager: coordinator not loaded."
    coord = domain_data.get(entry_id)
    if coord is None or coord.data is None:
        return "Energy Manager: no data yet."
    d = coord.data
    mode = d.get("energy_manager_mode", "?")
    strat = d.get("strategy_recommendation", "?")
    soc = d.get("battery_soc", "?")
    last = d.get(DATA_INTEGRATION_ALERT_LAST)
    last_s = ""
    if isinstance(last, dict):
        last_s = str(last.get("summary", ""))[:300]
    return (
        f"Mode: {mode}\n"
        f"Strategy: {strat}\n"
        f"SOC: {soc}\n"
        f"Last alert: {last_s or '(none)'}"
    )


async def _answer_callback(
    session: aiohttp.ClientSession, token: str, cq_id: str, text: str = ""
) -> None:
    url = f"{TELEGRAM_API}/bot{token}/answerCallbackQuery"
    await _post_json(
        session,
        url,
        {"callback_query_id": cq_id, "text": text or "OK", "show_alert": False},
    )


async def telegram_poll_loop(
    hass: HomeAssistant, entry_id: str, stop_event: asyncio.Event
) -> None:
    offset = 0
    while not stop_event.is_set():
        cfg = _merged_entry_config(hass, entry_id)
        st = _telegram_settings(cfg)
        if not st["enabled"] or not st["token"] or not st["commands"]:
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=TELEGRAM_POLL_IDLE_SEC
                )
            except TimeoutError:
                pass
            continue
        url = f"{TELEGRAM_API}/bot{st['token']}/getUpdates"
        params: dict[str, Any] = {
            "offset": offset,
            "timeout": 25,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=35),
                ) as resp:
                    http_status = resp.status
                    raw = await resp.text()
                if http_status != 200:
                    _LOGGER.debug("Telegram getUpdates HTTP %s", http_status)
                    try:
                        await asyncio.wait_for(
                            stop_event.wait(), timeout=TELEGRAM_POLL_IDLE_SEC
                        )
                    except TimeoutError:
                        pass
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await asyncio.sleep(TELEGRAM_POLL_IDLE_SEC)
                    continue
                if not data.get("ok"):
                    await asyncio.sleep(TELEGRAM_POLL_IDLE_SEC)
                    continue
                send_url = f"{TELEGRAM_API}/bot{st['token']}/sendMessage"
                for upd in data.get("result", []):
                    offset = int(upd.get("update_id", 0)) + 1
                    cq = upd.get("callback_query")
                    if isinstance(cq, dict):
                        cq_id = str(cq.get("id", ""))
                        chat = cq.get("message", {}).get("chat") or {}
                        chat_id = chat.get("id")
                        data_cb = str(cq.get("data") or "")
                        if chat_id is None or not _allowed_chat(st, chat_id):
                            continue
                        if data_cb == "em_ping":
                            await _answer_callback(session, st["token"], cq_id, "pong")
                            await _post_json(
                                session,
                                send_url,
                                {
                                    "chat_id": chat_id,
                                    "text": "Energy Manager: OK (test callback).",
                                },
                            )
                        else:
                            await _answer_callback(
                                session, st["token"], cq_id, "Unknown action"
                            )
                        continue
                    msg = upd.get("message")
                    if not isinstance(msg, dict):
                        continue
                    chat = msg.get("chat") or {}
                    chat_id = chat.get("id")
                    if chat_id is None or not _allowed_chat(st, chat_id):
                        continue
                    text_in = str(msg.get("text") or "").strip()
                    if not text_in:
                        continue
                    parts = text_in.split(maxsplit=1)
                    cmd = parts[0].split("@", 1)[0].lower()

                    if cmd in ("/start", "/help"):
                        reply = (
                            "Energy Manager bot\n"
                            "/status — mode, strategy, SOC, last alert\n"
                            "/clear_alerts — clear in-memory alert ring\n"
                            "/ping — inline test (callback)\n"
                            "/help — this text"
                        )
                    elif cmd == "/status":
                        reply = _status_text(hass, entry_id)
                    elif cmd == "/clear_alerts":
                        domain_data = hass.data.get(DOMAIN)
                        if isinstance(domain_data, dict):
                            coord = domain_data.get(entry_id)
                            if coord is not None and hasattr(
                                coord, "clear_integration_alerts"
                            ):
                                coord.clear_integration_alerts()
                                reply = "Alerts cleared."
                            else:
                                reply = "Coordinator unavailable."
                        else:
                            reply = "Coordinator unavailable."
                    elif cmd == "/ping":
                        await _post_json(
                            session,
                            send_url,
                            {
                                "chat_id": chat_id,
                                "text": "Tap the button (callback test).",
                                "reply_markup": {
                                    "inline_keyboard": [
                                        [
                                            {
                                                "text": "OK",
                                                "callback_data": "em_ping",
                                            }
                                        ]
                                    ]
                                },
                            },
                        )
                        continue
                    else:
                        reply = f"Unknown command: {cmd}. Try /help."
                    await _post_json(
                        session,
                        send_url,
                        {"chat_id": chat_id, "text": reply[:TELEGRAM_MESSAGE_MAX_LEN]},
                    )
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Telegram poll error: %s", err)
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=TELEGRAM_POLL_IDLE_SEC
                )
            except TimeoutError:
                pass
