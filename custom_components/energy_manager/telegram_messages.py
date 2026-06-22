"""Human-readable Hebrew Telegram alert text (ops-log records → user messages)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from homeassistant.core import HomeAssistant

from .const import TELEGRAM_MESSAGE_MAX_LEN

_MODE_HE: dict[str, str] = {
    "saving": "חיסכון",
    "normal": "רגיל",
    "wasting": "בזבוז עודף",
    "emergency_saving": "חירום",
}

_STRATEGY_HE: dict[str, str] = {
    "low": "נמוכה",
    "medium": "בינונית",
    "high": "גבוהה",
    "full": "מלאה",
}

_LEVEL_ICON: dict[str, str] = {
    "ERROR": "🔴",
    "WARN": "⚠️",
    "INFO": "ℹ️",
}


def _ctx(rec: dict[str, Any]) -> dict[str, Any]:
    raw = rec.get("context")
    return raw if isinstance(raw, dict) else {}


def _entity_label(hass: HomeAssistant | None, entity_id: str) -> str:
    eid = (entity_id or "").strip()
    if not eid:
        return "?"
    if hass is None:
        return eid
    state = hass.states.get(eid)
    if state is None:
        return eid
    friendly = state.attributes.get("friendly_name")
    if isinstance(friendly, str) and friendly.strip() and friendly != eid:
        return f"{friendly.strip()} ({eid})"
    return eid


def _mode_he(mode: str) -> str:
    key = (mode or "").strip().lower()
    label = _MODE_HE.get(key)
    return f"{label} ({key})" if label else (mode or "?")


def _strategy_he(strategy: str) -> str:
    key = (strategy or "").strip().lower()
    label = _STRATEGY_HE.get(key)
    return f"{label} ({key})" if label else (strategy or "?")


def _soc_line(ctx: dict[str, Any]) -> str | None:
    soc = ctx.get("battery_soc_percent")
    if soc is None or str(soc).strip() == "":
        return None
    return f"🔋 סוללה: {soc}%"


def _format_time_short(ts_iso: str) -> str:
    raw = (ts_iso or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%d/%m %H:%M")
    except ValueError:
        return raw[:16]


def _lines(*parts: str | None) -> list[str]:
    return [p for p in parts if p]


def _fmt_system_mode_changed(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    frm = _mode_he(str(ctx.get("from_mode", "")))
    to = _mode_he(str(ctx.get("to_mode", "")))
    reason = str(ctx.get("mode_reason") or "").strip()
    out = _lines(
        "🔄 שינוי מצב מערכת",
        f"מ: {frm}",
        f"ל: {to}",
        _soc_line(ctx),
        f"💡 {reason}" if reason else None,
    )
    return out


def _fmt_strategy_changed(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    frm = _strategy_he(str(ctx.get("from_strategy", "")))
    to = _strategy_he(str(ctx.get("to_strategy", "")))
    reason = str(ctx.get("strategy_reason") or "").strip()
    return _lines(
        "📊 שינוי אסטרטגיית סוללה",
        f"מ: {frm}",
        f"ל: {to}",
        _soc_line(ctx),
        f"💡 {reason}" if reason else None,
    )


def _fmt_consumer_on(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    eid = str(ctx.get("entity_id", ""))
    return _lines(
        "✅ הודלק צרכן",
        f"🔌 {_entity_label(hass, eid)}",
        f"מצב: {_mode_he(str(ctx.get('system_mode', '')))}",
        _soc_line(ctx),
    )


def _fmt_consumer_off(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    eid = str(ctx.get("entity_id", ""))
    reason = str(ctx.get("reason_code") or "").strip()
    reason_he = {
        "discharge_over_limit": "מגבלת פריקת סוללה",
        "saving_bulk": "מצב חיסכון",
        "emergency_bulk": "מצב חירום",
        "normal_lifo": "ירידה הדרגתית (רגיל)",
    }.get(reason, reason)
    return _lines(
        "⏹️ כובה צרכן",
        f"🔌 {_entity_label(hass, eid)}",
        f"מצב: {_mode_he(str(ctx.get('system_mode', '')))}",
        f"סיבה: {reason_he}" if reason_he else None,
        _soc_line(ctx),
    )


def _fmt_bulk_off(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    count = ctx.get("count", "?")
    return _lines(
        f"⏹️ כובו {count} צרכנים",
        f"מצב: {_mode_he(str(ctx.get('system_mode', '')))}",
        _soc_line(ctx),
    )


def _fmt_turn_on_failed(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    eid = str(ctx.get("entity_id", ""))
    err = str(ctx.get("error") or "").strip()
    return _lines(
        "❌ נכשלה הדלקת צרכן",
        f"🔌 {_entity_label(hass, eid)}",
        "הפקודה ל-Home Assistant נכשלה.",
        f"פרטים: {err}" if err else None,
        _soc_line(ctx),
    )


def _fmt_forecast_cache(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    event = str(rec.get("event", ""))
    if event == "forecast_using_disk_cache":
        detail = "משתמש בתחזית שמורה בדיסק"
    elif event == "forecast_using_memory_cache":
        detail = "משתמש בתחזית אחרונה בזיכרון"
    else:
        detail = str(rec.get("summary", ""))
    return _lines(
        "☁️ תחזית סולארית",
        "Open-Meteo לא זמין.",
        detail,
        _soc_line(ctx),
    )


def _fmt_forecast_open_meteo(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    event = str(rec.get("event", ""))
    labels = {
        "open_meteo_timeout": "תם הזמן בבקשה לשרת התחזית",
        "open_meteo_http_error": "שגיאת HTTP משרת התחזית",
        "open_meteo_request_failed": "בקשת התחזית נכשלה",
        "open_meteo_empty_response": "תשובה ריקה משרת התחזית",
        "forecast_all_zeros": "התחזית חזרה עם אפס ייצור",
        "forecast_invalid_timezone": "אזור זמן לא תקין לתחזית",
    }
    return _lines(
        "☁️ בעיה בתחזית סולארית",
        labels.get(event, str(rec.get("summary", ""))),
        _soc_line(ctx),
    )


def _fmt_discharge_max(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    discharge = ctx.get("battery_discharge_kw", "?")
    ceiling = ctx.get("discharge_ceiling_kw", "?")
    return _lines(
        "⚡ פריקת סוללה במקסימום",
        f"פריקה נוכחית: {discharge} kW (תקרה {ceiling} kW)",
        _soc_line(ctx),
    )


def _fmt_coordinator_failed(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    err = str(ctx.get("error") or "").strip()
    return _lines(
        "🔴 שגיאה במערכת Energy Manager",
        "עדכון המחזור נכשל.",
        f"פרטים: {err[:200]}" if err else None,
    )


def _fmt_learn_warn(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    eid = str(ctx.get("entity_id", ""))
    return _lines(
        "📉 למידת צריכה",
        f"לא ניתן למדוד צריכת בית עבור {_entity_label(hass, eid)}",
        "ייתכן שהצרכן כבוי או שהחיישנים לא מספיק רגישים.",
    )


def _fmt_generic(
    hass: HomeAssistant | None, rec: dict[str, Any], ctx: dict[str, Any]
) -> list[str]:
    summary = str(rec.get("summary", "")).strip()
    event = str(rec.get("event", "")).replace("_", " ")
    lines = _lines(summary or event, _soc_line(ctx))
    eid = str(ctx.get("entity_id", ""))
    if eid and hass is not None:
        lines.insert(0, f"🔌 {_entity_label(hass, eid)}")
    return lines


_EVENT_FORMATTERS: dict[str, Callable[..., list[str]]] = {
    "system_mode_changed": _fmt_system_mode_changed,
    "strategy_recommendation_changed": _fmt_strategy_changed,
    "consumer_turned_on": _fmt_consumer_on,
    "consumer_turned_off": _fmt_consumer_off,
    "consumers_turned_off_bulk": _fmt_bulk_off,
    "super_saving_devices_off": _fmt_bulk_off,
    "consumer_turn_on_failed": _fmt_turn_on_failed,
    "forecast_using_disk_cache": _fmt_forecast_cache,
    "forecast_using_memory_cache": _fmt_forecast_cache,
    "open_meteo_timeout": _fmt_forecast_open_meteo,
    "open_meteo_http_error": _fmt_forecast_open_meteo,
    "open_meteo_request_failed": _fmt_forecast_open_meteo,
    "open_meteo_empty_response": _fmt_forecast_open_meteo,
    "forecast_all_zeros": _fmt_forecast_open_meteo,
    "forecast_invalid_timezone": _fmt_forecast_open_meteo,
    "discharge_state_max_entered": _fmt_discharge_max,
    "coordinator_update_failed": _fmt_coordinator_failed,
    "consumer_house_delta_unmeasurable": _fmt_learn_warn,
}


def format_telegram_alert(hass: HomeAssistant | None, rec: dict[str, Any]) -> str:
    """Build a concise Hebrew user message from an ops-log alert record."""
    level = str(rec.get("level", "INFO")).upper()
    icon = _LEVEL_ICON.get(level, "ℹ️")
    event = str(rec.get("event", ""))
    ctx = _ctx(rec)
    ts = _format_time_short(str(rec.get("ts_iso", "")))

    formatter = _EVENT_FORMATTERS.get(event, _fmt_generic)
    body_lines = formatter(hass, rec, ctx)

    header = f"{icon} Energy Manager"
    if ts:
        header = f"{header} · {ts}"

    text = "\n".join([header, *body_lines])
    if len(text) > TELEGRAM_MESSAGE_MAX_LEN:
        text = text[: TELEGRAM_MESSAGE_MAX_LEN - 1] + "…"
    return text
