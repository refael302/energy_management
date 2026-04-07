"""
Data coordinator – polls sensors and forecast every 30s, runs decision engine and load manager.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .engine.baseline_profile_learn import (
    BaselineProfileLearner,
    residual_house_kw,
    unlearned_consumer_on,
)
from .engine.consumer_learn import ConsumerLearner
from .engine.battery_power_limit_learn import BatteryPowerPeakLearner
from .engine.consumer_learn_cache import consumer_learn_fingerprint
from .engine.forecast_cache import (
    create_forecast_store,
    forecast_config_fingerprint,
    stored_series_covers_now,
)
from .const import (
    BATTERY_SOC_VERY_LOW_PERCENT,
    CONSUMER_ACTION_DELAY_UNLEARNED_MINUTES,
    DATA_INTEGRATION_ALERT_LAST,
    DATA_INTEGRATION_ALERTS,
    DATA_INTEGRATION_ALERTS_DISPLAY,
    INTEGRATION_ALERTS_MAX,
    INTEGRATION_ALERTS_DISPLAY_MAX,
    STRATEGY_MEDIUM,
    DEFAULT_CONSUMER_BUDGET_HYSTERESIS_RATIO,
    SYSTEM_MODE_NORMAL,
    SYSTEM_MODE_WASTING,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_CONSUMERS,
    CONF_CONSUMER_POWER_SENSOR_ENTITY_ID,
    CONF_CONSUMER_SWITCH_ENTITY_ID,
    CONF_FORECAST_PR,
    CONF_HOUSE_CONSUMPTION_SENSOR,
    CONF_INVERTER_SIZE_KW,
    CONF_LATITUDE,
    CONF_LIGHTS_TO_TURN_OFF,
    CONF_MANUAL_MODE,
    CONF_MANUAL_MODE_OVERRIDE,
    CONF_MANUAL_OVERRIDE,
    CONF_MANUAL_STRATEGY,
    CONF_MANUAL_STRATEGY_OVERRIDE,
    CONF_RECOMMENDED_TO_TURN_OFF,
    CONF_LONGITUDE,
    CONF_MAX_BATTERY_CHARGE_POWER_KW,
    CONF_MAX_BATTERY_DISCHARGE_POWER_KW,
    CONF_SOLAR_PRODUCTION_SENSOR,
    CONF_STRINGS,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_FORECAST_PR,
    DEFAULT_INVERTER_SIZE_KW,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_SAFETY_FORECAST_FACTOR,
    DOMAIN,
    EOD_BATTERY_TARGET_PLANNING_PERCENT,
    EMERGENCY_RESERVE_PLANNING_PERCENT,
    FORECAST_STRATEGY_CACHE_MINUTES,
    INTEGRATION_LOG_ENABLED,
    CONSUMER_ACTIVE_POWER_THRESHOLD_KW,
    MIN_EFFECTIVE_MAX_BATTERY_POWER_KW,
    NIGHT_BRIDGE_HOURS_BEFORE_SUNRISE,
    UPDATE_INTERVAL,
)
from .engine import DecisionEngine, EnergyModel, ForecastEngine, LoadManager
from .engine.battery_horizon import compute_battery_edge_horizons
from .engine.consumer_budget import (
    apply_hysteresis,
    compose_raw_budget_kw,
    compute_raw_budget_kw,
    marginal_battery_load_fraction,
    select_learned_consumers,
    trim_learned_consumers_for_very_low_horizon,
)
from .engine.load_manager import WastingContext
from .engine.decision_engine import recommend_battery_strategy
from .hourly_snapshot import build_hourly_snapshot_lines
from .integration_log import async_log_event

_LOGGER = logging.getLogger(__name__)


def _float_state(hass: HomeAssistant, entity_id: str) -> float:
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        return 0.0
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return 0.0


def _numeric_sensor_power_kw(hass: HomeAssistant, entity_id: str) -> float:
    """Parse a sensor state as power in kW using unit_of_measurement when present."""
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        return 0.0
    try:
        val = float(state.state)
    except (TypeError, ValueError):
        return 0.0
    uom = str(state.attributes.get("unit_of_measurement") or "").strip().lower()
    if uom in ("kw", "kilowatt", "kilowatts") or uom == str(UnitOfPower.KILO_WATT).lower():
        return max(0.0, val)
    if uom in ("mw", "megawatt", "megawatts"):
        return max(0.0, val * 1000.0)
    if uom in ("w", "watt", "watts", str(UnitOfPower.WATT).lower()) or not uom:
        return max(0.0, val / 1000.0)
    return max(0.0, val / 1000.0)


def _effective_battery_max_kw(manual_kw: float, learned_kw: float) -> float:
    """Manual max (kW) wins when > 0; else use learned peak (floored)."""
    if manual_kw > 0:
        return max(MIN_EFFECTIVE_MAX_BATTERY_POWER_KW, float(manual_kw))
    return max(MIN_EFFECTIVE_MAX_BATTERY_POWER_KW, float(learned_kw))


def _hours_float_to_hhmm(hours: float | None) -> str:
    if hours is None:
        return "99:59"
    h = int(min(99, max(0, int(hours))))
    m = int((float(hours) % 1.0) * 60)
    return f"{h:02d}:{m:02d}"


def _normalize_consumer_entity_ids(raw: Any) -> list[str]:
    """Normalize consumer list from config (support list of strings or list of dicts with entity_id)."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            eid = item.get("entity_id") or item.get("id")
            if isinstance(eid, str):
                out.append(eid)
    return out


def _normalize_consumers(raw: Any) -> list[dict[str, str | None]]:
    """Normalize consumer definitions to [{switch_entity_id, power_sensor_entity_id}]."""
    if not raw:
        return []
    out: list[dict[str, str | None]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                out.append(
                    {
                        CONF_CONSUMER_SWITCH_ENTITY_ID: item,
                        CONF_CONSUMER_POWER_SENSOR_ENTITY_ID: None,
                    }
                )
                continue
            if isinstance(item, dict):
                switch_eid = item.get(CONF_CONSUMER_SWITCH_ENTITY_ID)
                if not isinstance(switch_eid, str):
                    continue
                sensor_eid = item.get(CONF_CONSUMER_POWER_SENSOR_ENTITY_ID)
                out.append(
                    {
                        CONF_CONSUMER_SWITCH_ENTITY_ID: switch_eid,
                        CONF_CONSUMER_POWER_SENSOR_ENTITY_ID: sensor_eid if isinstance(sensor_eid, str) and sensor_eid else None,
                    }
                )
    return out


def _hours_until_sunset(hass: HomeAssistant) -> float:
    sun = hass.states.get("sun.sun")
    if sun is None:
        return 0.0
    next_set = sun.attributes.get("next_setting")
    if next_set is None:
        return 0.0
    try:
        from homeassistant.util import dt as dt_util
        end_ts = dt_util.as_timestamp(next_set)
        now_ts = datetime.now(timezone.utc).timestamp()
        return max(0.0, round((end_ts - now_ts) / 3600, 2))
    except Exception as e:
        _LOGGER.debug("sun sunset: %s", e)
        return 0.0


def _hours_until_sunrise(hass: HomeAssistant) -> float:
    sun = hass.states.get("sun.sun")
    if sun is None:
        return 0.0
    next_rise = sun.attributes.get("next_rising")
    if next_rise is None:
        return 0.0
    try:
        from homeassistant.util import dt as dt_util
        rise_ts = dt_util.as_timestamp(next_rise)
        now_ts = datetime.now(timezone.utc).timestamp()
        return max(0.0, round((rise_ts - now_ts) / 3600, 2))
    except Exception as e:
        _LOGGER.debug("sun sunrise: %s", e)
        return 0.0


class EnergyManagerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Fetches sensor data and forecast every UPDATE_INTERVAL, updates EnergyModel,
    runs DecisionEngine, applies LoadManager, and exposes data for sensors.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        data = dict(entry.data)
        data.update(entry.options or {})
        self._config = data
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.model = EnergyModel(
            battery_capacity_kwh=float(data.get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY)),
            eod_battery_target_percent=float(EOD_BATTERY_TARGET_PLANNING_PERCENT),
            emergency_reserve_percent=float(EMERGENCY_RESERVE_PLANNING_PERCENT),
            safety_forecast_factor_percent=float(DEFAULT_SAFETY_FORECAST_FACTOR),
        )
        self.forecast_engine = ForecastEngine(
            latitude=float(data.get(CONF_LATITUDE, DEFAULT_LATITUDE)),
            longitude=float(data.get(CONF_LONGITUDE, DEFAULT_LONGITUDE)),
            strings=data.get(CONF_STRINGS, []),
            pr_factor=float(data.get(CONF_FORECAST_PR, DEFAULT_FORECAST_PR)),
        )
        self.decision_engine = DecisionEngine()
        self._consumers = _normalize_consumers(data.get(CONF_CONSUMERS))
        consumer_switches = [
            c.get(CONF_CONSUMER_SWITCH_ENTITY_ID)
            for c in self._consumers
            if isinstance(c.get(CONF_CONSUMER_SWITCH_ENTITY_ID), str)
        ]
        lights = data.get(CONF_LIGHTS_TO_TURN_OFF) or []
        if isinstance(lights, str):
            lights = [lights]
        self._recommended_to_turn_off_entity_ids = (
            data.get(CONF_RECOMMENDED_TO_TURN_OFF) or []
        )
        if isinstance(self._recommended_to_turn_off_entity_ids, str):
            self._recommended_to_turn_off_entity_ids = [
                self._recommended_to_turn_off_entity_ids
            ]
        self.consumer_learner = ConsumerLearner(hass, entry.entry_id)
        self.baseline_profile_learner = BaselineProfileLearner(hass, entry.entry_id)
        self.battery_peak_learner = BatteryPowerPeakLearner(hass, entry.entry_id)
        self.load_manager = LoadManager(
            hass,
            consumer_switches,
            lights,
            CONSUMER_ACTION_DELAY_UNLEARNED_MINUTES,
            schedule_consumer_learn=self._schedule_consumer_learn,
            integration_entry_id=entry.entry_id,
        )
        self._entity_ids = {
            "battery_soc": data.get(CONF_BATTERY_SOC_SENSOR),
            "battery_power": data.get(CONF_BATTERY_POWER_SENSOR),
            "solar": data.get(CONF_SOLAR_PRODUCTION_SENSOR),
            "house": data.get(CONF_HOUSE_CONSUMPTION_SENSOR),
        }
        self._prev_discharge_state: str = ""
        self._last_decision: Any = None
        self._last_forecast: Any = None
        self._last_forecast_time: datetime | None = None
        self._last_strategy: str | None = None
        self._last_strategy_reason: str = ""
        self._last_strategy_time: datetime | None = None
        self._prev_forecast_available: bool | None = None
        self._forecast_store = create_forecast_store(hass, entry.entry_id)
        self._forecast_disk_cache: dict[str, Any] | None = None
        self._locked_consumer_budget_kw: float | None = None
        self._ops_prev_system_mode: str | None = None
        self._ops_prev_strategy: str | None = None
        self._integration_alerts: deque[dict[str, Any]] = deque(maxlen=INTEGRATION_ALERTS_MAX)
        self._integration_alert_seq: int = 0

    @staticmethod
    def _integration_alert_fingerprint(
        level: str,
        category: str,
        event: str,
        summary: str,
        context: dict[str, Any],
    ) -> tuple[Any, ...]:
        """Identity for dedupe: same logical alert is not stored twice while it remains in the deque."""
        ctx_items = tuple(sorted((k, str(v)) for k, v in sorted(context.items())))
        return (level, category, event, summary, ctx_items)

    def _integration_alert_fingerprint_stored(self, alert: dict[str, Any]) -> tuple[Any, ...]:
        ctx = alert.get("context")
        if not isinstance(ctx, dict):
            ctx = {}
        return self._integration_alert_fingerprint(
            str(alert.get("level", "")),
            str(alert.get("category", "")),
            str(alert.get("event", "")),
            str(alert.get("summary", "")),
            dict(ctx),
        )

    def _integration_alert_data(self) -> dict[str, Any]:
        """Keys merged into coordinator.data for the last-alert sensor."""
        last = self._integration_alerts[-1] if self._integration_alerts else None
        full_list = list(self._integration_alerts)
        display = full_list[-INTEGRATION_ALERTS_DISPLAY_MAX:]
        return {
            DATA_INTEGRATION_ALERT_LAST: last,
            DATA_INTEGRATION_ALERTS: full_list,
            DATA_INTEGRATION_ALERTS_DISPLAY: display,
        }

    def push_integration_alert(self, record: dict[str, Any]) -> None:
        """Append one ops-log record to the in-memory ring and refresh coordinator data."""
        ctx = record.get("context")
        if not isinstance(ctx, dict):
            ctx = {}
        ctx = dict(ctx)
        level = str(record.get("level", ""))
        category = str(record.get("category", ""))
        event = str(record.get("event", ""))
        summary = str(record.get("summary", ""))
        fp = self._integration_alert_fingerprint(level, category, event, summary, ctx)
        if any(self._integration_alert_fingerprint_stored(a) == fp for a in self._integration_alerts):
            return
        self._integration_alert_seq += 1
        full: dict[str, Any] = {
            "ts_iso": str(record.get("ts_iso", "")),
            "level": level,
            "category": category,
            "event": event,
            "summary": summary,
            "context": ctx,
            "seq": self._integration_alert_seq,
        }
        self._integration_alerts.append(full)
        self.async_set_updated_data({**(self.data or {}), **self._integration_alert_data()})

    def clear_integration_alerts(self) -> None:
        """Clear the in-memory alert ring (e.g. after user dismisses in UI)."""
        self._integration_alerts.clear()
        self._integration_alert_seq = 0
        self.async_set_updated_data({**(self.data or {}), **self._integration_alert_data()})

    async def async_log_hourly_snapshot(self) -> None:
        """Append a readable multi-line SYSTEM snapshot to the ops log (once per hour)."""
        if not INTEGRATION_LOG_ENABLED or not self.data:
            return
        try:
            snapshot_id = dt_util.now().isoformat(timespec="seconds")
            lines = build_hourly_snapshot_lines(
                self.hass, self.data, self._entity_ids
            )
            n = len(lines)
            for i, summary in enumerate(lines):
                await async_log_event(
                    self.hass,
                    self.entry.entry_id,
                    "INFO",
                    "SYSTEM",
                    "hourly_system_snapshot",
                    summary,
                    {
                        "reason_code": f"snapshot_line_{i + 1:02d}_of_{n:02d}",
                        "snapshot_id": snapshot_id,
                    },
                    integration_alerts=(i == 0),
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Hourly ops snapshot skipped: %s", err)

    def _schedule_consumer_learn(self, entity_id: str) -> None:
        """No-op hook kept for load-manager compatibility."""
        _LOGGER.debug("Consumer learn scheduling hook called for %s", entity_id)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch sensors, forecast, update model, run decision, apply load manager."""
        try:
            # 1. Sensor values (power in W -> kW where needed)
            soc = _float_state(self.hass, self._entity_ids["battery_soc"] or "")
            battery_power_w = _float_state(self.hass, self._entity_ids["battery_power"] or "")
            solar_w = _float_state(self.hass, self._entity_ids["solar"] or "")
            house_w = _float_state(self.hass, self._entity_ids["house"] or "")

            self.model.battery_soc = soc
            self.model.battery_power_kw = battery_power_w / 1000.0
            self.model.solar_production_kw = solar_w / 1000.0
            self.model.house_consumption_kw = house_w / 1000.0
            current_config = {**self.entry.data, **(self.entry.options or {})}
            consumers_cfg = _normalize_consumers(current_config.get(CONF_CONSUMERS))

            await self.battery_peak_learner.async_ensure_loaded(current_config)
            self.battery_peak_learner.record_sample(self.model.battery_power_kw)
            await self.battery_peak_learner.async_persist_if_dirty()
            manual_d = float(current_config.get(CONF_MAX_BATTERY_DISCHARGE_POWER_KW) or 0)
            manual_c = float(current_config.get(CONF_MAX_BATTERY_CHARGE_POWER_KW) or 0)
            learned_d = self.battery_peak_learner.peak_discharge_kw
            learned_c = self.battery_peak_learner.peak_charge_kw
            # Peaks are positive kW magnitudes. Auto discharge uses the larger of learned
            # discharge/charge peaks (symmetric inverter hint), capped by charge_effective
            # (manual charge ceiling when set).
            charge_effective = _effective_battery_max_kw(manual_c, learned_c)
            self.model.max_battery_charge_kw = charge_effective
            if manual_d > 0:
                self.model.max_battery_discharge_kw = _effective_battery_max_kw(
                    manual_d, learned_d
                )
            else:
                symmetric_kw = max(float(learned_d), float(learned_c))
                self.model.max_battery_discharge_kw = max(
                    MIN_EFFECTIVE_MAX_BATTERY_POWER_KW,
                    min(symmetric_kw, float(charge_effective)),
                )

            fp_learn = consumer_learn_fingerprint(current_config)
            await self.consumer_learner.async_ensure_loaded(fp_learn)
            await self.baseline_profile_learner.async_ensure_loaded(current_config)

            sample_local = dt_util.now()
            consumer_entity_ids = [
                str(c.get(CONF_CONSUMER_SWITCH_ENTITY_ID))
                for c in consumers_cfg
                if c.get(CONF_CONSUMER_SWITCH_ENTITY_ID)
            ]
            consumer_power_kw: dict[str, float | None] = {}
            consumer_has_sensor: dict[str, bool] = {}
            actual_on_map: dict[str, bool | None] = {}
            for c in consumers_cfg:
                switch_eid = c.get(CONF_CONSUMER_SWITCH_ENTITY_ID)
                if not isinstance(switch_eid, str):
                    continue
                sensor_eid = c.get(CONF_CONSUMER_POWER_SENSOR_ENTITY_ID)
                consumer_has_sensor[switch_eid] = isinstance(sensor_eid, str) and bool(sensor_eid)
                p_kw: float | None = None
                if isinstance(sensor_eid, str) and sensor_eid:
                    p_kw = _numeric_sensor_power_kw(self.hass, sensor_eid)
                    consumer_power_kw[switch_eid] = p_kw
                    actual_on_map[switch_eid] = p_kw >= CONSUMER_ACTIVE_POWER_THRESHOLD_KW
                else:
                    consumer_power_kw[switch_eid] = None
                    actual_on_map[switch_eid] = None
                st = self.hass.states.get(switch_eid)
                expected_on = st is not None and st.state == "on"
                if isinstance(sensor_eid, str) and sensor_eid:
                    await self.consumer_learner.async_record_power_tick(
                        switch_eid,
                        p_kw,
                        expected_on=expected_on,
                        now_local=sample_local,
                        dt_seconds=float(UPDATE_INTERVAL),
                        fingerprint=fp_learn,
                    )
            learned_kw = self.consumer_learner.get_learned_kw()
            baseline_sampled = False
            if not unlearned_consumer_on(
                self.hass,
                consumer_entity_ids,
                learned_kw,
                has_power_sensor=consumer_has_sensor,
                actual_on_map=actual_on_map,
            ):
                res_kw = residual_house_kw(
                    self.hass,
                    self.model.house_consumption_kw,
                    consumer_entity_ids,
                    learned_kw,
                    actual_on_map=actual_on_map,
                )
                baseline_sampled = self.baseline_profile_learner.record_sample_if_allowed(
                    res_kw, sample_local
                )
            self.model.baseline_hourly_kw = self.baseline_profile_learner.get_effective_profile_kw()
            await self.baseline_profile_learner.async_persist_if_dirty()

            # 2. Forecast: refresh from Open-Meteo on interval; persist hourly series to disk;
            #    on API failure use disk cache (then in-memory) so decisions still use last good hourly data.
            now_utc = datetime.now(timezone.utc)
            cache_min = timedelta(minutes=FORECAST_STRATEGY_CACHE_MINUTES)
            inverter_size_kw = float(
                current_config.get(CONF_INVERTER_SIZE_KW, DEFAULT_INVERTER_SIZE_KW) or 0
            )
            fp = forecast_config_fingerprint(current_config)
            if self._forecast_disk_cache is None:
                self._forecast_disk_cache = await self._forecast_store.async_load()

            if (
                self._last_forecast is None
                or self._last_forecast_time is None
                or (now_utc - self._last_forecast_time) >= cache_min
            ):
                now_ha = dt_util.now()
                forecast = await self.forecast_engine.fetch_and_compute(
                    self.hass,
                    now_ha,
                    inverter_size_kw=inverter_size_kw,
                    integration_entry_id=self.entry.entry_id,
                )
                if forecast.available:
                    self._last_forecast = forecast
                    self._last_forecast_time = now_utc
                    payload = self.forecast_engine.get_cache_payload()
                    if payload and payload.get("times_iso") and payload.get("total_kw_after_pr"):
                        try:
                            await self._forecast_store.async_save(
                                {
                                    "fingerprint": fp,
                                    "times_iso": payload["times_iso"],
                                    "total_kw_after_pr": payload["total_kw_after_pr"],
                                }
                            )
                            self._forecast_disk_cache = await self._forecast_store.async_load()
                        except Exception as e:
                            _LOGGER.debug("Forecast disk save failed: %s", e)
                else:
                    disk = self._forecast_disk_cache
                    rebuilt = None
                    if (
                        disk
                        and disk.get("fingerprint") == fp
                        and disk.get("times_iso")
                        and disk.get("total_kw_after_pr")
                        and stored_series_covers_now(disk["times_iso"], self.hass, now_ha)
                    ):
                        rebuilt = self.forecast_engine.build_from_stored(
                            self.hass,
                            now_ha,
                            list(disk["times_iso"]),
                            [float(x) for x in disk["total_kw_after_pr"]],
                            inverter_size_kw,
                        )
                    if rebuilt is not None and rebuilt.available:
                        forecast = rebuilt
                        self._last_forecast = forecast
                        self._last_forecast_time = now_utc
                        _LOGGER.warning(
                            "Open-Meteo unavailable; using persisted hourly forecast cache"
                        )
                        await async_log_event(
                            self.hass,
                            self.entry.entry_id,
                            "WARN",
                            "FORECAST",
                            "forecast_using_disk_cache",
                            "Open-Meteo unavailable; using persisted hourly cache",
                            {"reason_code": "disk_cache"},
                        )
                    elif self._last_forecast is not None and getattr(
                        self._last_forecast, "available", False
                    ):
                        forecast = self._last_forecast
                        self._last_forecast_time = now_utc
                        _LOGGER.warning(
                            "Open-Meteo unavailable; using last in-memory forecast"
                        )
                        await async_log_event(
                            self.hass,
                            self.entry.entry_id,
                            "WARN",
                            "FORECAST",
                            "forecast_using_memory_cache",
                            "Open-Meteo unavailable; using in-memory forecast",
                            {"reason_code": "memory_cache"},
                        )
                    else:
                        self._last_forecast = forecast
                        self._last_forecast_time = now_utc
            else:
                forecast = self._last_forecast
            forecast_available = getattr(forecast, "available", True)
            forecast_availability_changed = (
                self._prev_forecast_available is not None
                and self._prev_forecast_available != forecast_available
            )
            if forecast_availability_changed:
                await async_log_event(
                    self.hass,
                    self.entry.entry_id,
                    "INFO",
                    "FORECAST",
                    "forecast_availability_changed",
                    f"Forecast available {self._prev_forecast_available} -> {forecast_available}",
                    {
                        "reason_code": "availability_toggle",
                        "from_available": str(self._prev_forecast_available),
                        "to_available": str(forecast_available),
                    },
                )
            self._prev_forecast_available = forecast_available
            self.model.forecast_available = forecast_available
            if forecast_available:
                self.model.forecast_next_hour_kwh = forecast.forecast_next_hour_kwh
                self.model.forecast_today_remaining_kwh = forecast.forecast_today_remaining_kwh
                self.model.forecast_tomorrow_kwh = forecast.forecast_tomorrow_kwh
                self.model.hours_until_first_pv = getattr(
                    forecast, "hours_until_first_pv", 0.0
                )
            else:
                self.model.forecast_next_hour_kwh = 0.0
                self.model.forecast_today_remaining_kwh = 0.0
                self.model.forecast_tomorrow_kwh = 0.0
                self.model.hours_until_first_pv = 0.0
            self.model.hours_until_eod = _hours_until_sunset(self.hass)
            hours_until_sunrise = _hours_until_sunrise(self.hass)
            self.model.hours_until_sunrise = hours_until_sunrise
            sun_ent = self.hass.states.get("sun.sun")
            self.model.sun_below_horizon = (
                sun_ent.state == "below_horizon"
                if sun_ent is not None
                else True
            )

            # 3. Derived (hourly baseline uses local midnight for consumption_till_eod_kwh)
            now_local = dt_util.now()
            self.model.update_derived(now_local)

            # 4. Decision engine (charge state duration: assume ~0.5 min per update)
            self.decision_engine.update_charge_state_duration(
                self.model.charge_state, UPDATE_INTERVAL / 60.0
            )
            manual_mode_override = bool(current_config.get(CONF_MANUAL_MODE_OVERRIDE, current_config.get(CONF_MANUAL_OVERRIDE, False)))
            manual_strategy_override = bool(current_config.get(CONF_MANUAL_STRATEGY_OVERRIDE, current_config.get(CONF_MANUAL_OVERRIDE, False)))
            manual_mode = current_config.get(CONF_MANUAL_MODE) or SYSTEM_MODE_NORMAL
            manual_strategy = current_config.get(CONF_MANUAL_STRATEGY) or STRATEGY_MEDIUM
            night_bridge_window = (
                0.0 < self.model.hours_until_sunrise
                <= NIGHT_BRIDGE_HOURS_BEFORE_SUNRISE
            )
            if (
                self._last_strategy_time is None
                or (now_utc - self._last_strategy_time) >= cache_min
                or night_bridge_window
                or not forecast_available
                or forecast_availability_changed
            ):
                self._last_strategy, self._last_strategy_reason = recommend_battery_strategy(
                    self.model
                )
                self._last_strategy_time = now_utc
            cached_strategy = (
                (self._last_strategy, self._last_strategy_reason)
                if self._last_strategy is not None
                else None
            )
            decision = self.decision_engine.decide(
                self.model,
                manual_mode_override=manual_mode_override,
                manual_strategy_override=manual_strategy_override,
                manual_mode=manual_mode,
                manual_strategy=manual_strategy,
                cached_strategy=cached_strategy,
            )
            self._last_decision = decision

            if self._ops_prev_system_mode is not None:
                if self._ops_prev_system_mode != decision.system_mode:
                    await async_log_event(
                        self.hass,
                        self.entry.entry_id,
                        "INFO",
                        "MODE",
                        "system_mode_changed",
                        f"System mode {self._ops_prev_system_mode} -> {decision.system_mode}",
                        {
                            "reason_code": "decision_engine",
                            "from_mode": self._ops_prev_system_mode,
                            "to_mode": decision.system_mode,
                            "mode_reason": decision.mode_reason,
                        },
                    )
            self._ops_prev_system_mode = decision.system_mode

            if self._ops_prev_strategy is not None:
                if self._ops_prev_strategy != decision.strategy_recommendation:
                    await async_log_event(
                        self.hass,
                        self.entry.entry_id,
                        "INFO",
                        "MODE",
                        "strategy_recommendation_changed",
                        f"Strategy {self._ops_prev_strategy} -> {decision.strategy_recommendation}",
                        {
                            "reason_code": "strategy_update",
                            "from_strategy": self._ops_prev_strategy,
                            "to_strategy": decision.strategy_recommendation,
                            "strategy_reason": decision.strategy_reason,
                        },
                    )
            self._ops_prev_strategy = decision.strategy_recommendation

            # 5. Consumer budget (wasting) + load manager
            super_saving = self.model.battery_status == "very low"
            wasting_context: WastingContext | None = None
            budget_ceilings: Any = None
            raw_budget_kw = 0.0
            effective_budget_kw = 0.0

            if decision.system_mode != SYSTEM_MODE_WASTING:
                self._locked_consumer_budget_kw = None

            if decision.system_mode == SYSTEM_MODE_WASTING:
                marginal = marginal_battery_load_fraction(
                    self.model.solar_production_kw,
                    self.model.house_consumption_kw,
                )
                discharge_kw = max(0.0, self.model.battery_power_kw)
                hyst_ratio = float(DEFAULT_CONSUMER_BUDGET_HYSTERESIS_RATIO)
                budget_ceilings = compute_raw_budget_kw(self.model, inverter_size_kw)
                raw_budget_kw = compose_raw_budget_kw(
                    budget_ceilings,
                    marginal_battery_per_kw=marginal,
                    battery_discharging_kw=discharge_kw,
                )
                effective_budget_kw, budget_updated = apply_hysteresis(
                    raw_budget_kw,
                    self._locked_consumer_budget_kw,
                    hyst_ratio,
                )
                if budget_updated:
                    self._locked_consumer_budget_kw = effective_budget_kw
                learned_map = self.consumer_learner.get_learned_kw()
                consumer_list = consumer_entity_ids
                learned_target = select_learned_consumers(
                    consumer_list,
                    learned_map,
                    effective_budget_kw,
                    budget_ceilings.discharge_kw,
                    marginal,
                )
                pv_guard: list[float] = []
                time_guard: list[str] = []
                if forecast_available:
                    pv_guard = list(
                        getattr(forecast, "forecast_today_remaining_hourly_kw", []) or []
                    ) + list(
                        getattr(forecast, "forecast_tomorrow_hourly_kw", []) or []
                    )
                    time_guard = list(
                        getattr(forecast, "forecast_today_remaining_times_iso", []) or []
                    ) + list(
                        getattr(forecast, "forecast_tomorrow_hourly_times_iso", []) or []
                    )
                learned_target = trim_learned_consumers_for_very_low_horizon(
                    learned_target,
                    consumer_list,
                    learned_map,
                    marginal,
                    now_local=dt_util.now(),
                    soc_percent=float(soc),
                    capacity_kwh=float(self.model.battery_capacity_kwh),
                    very_low_percent=float(BATTERY_SOC_VERY_LOW_PERCENT),
                    target_full_percent=float(EOD_BATTERY_TARGET_PLANNING_PERCENT),
                    max_charge_kw=float(self.model.max_battery_charge_kw),
                    max_discharge_kw=float(self.model.max_battery_discharge_kw),
                    baseline_hourly_kw=list(self.model.baseline_hourly_kw),
                    pv_kw_slots=pv_guard,
                    time_iso_slots=time_guard,
                    hours_until_first_pv=float(self.model.hours_until_first_pv),
                )
                wasting_context = WastingContext(
                    consumers_ordered=consumer_list,
                    learned_kw=dict(learned_map),
                    learned_target=learned_target,
                    discharge_headroom_kw=budget_ceilings.discharge_kw,
                    marginal_battery_per_kw=marginal,
                )

            await self.load_manager.apply_mode(
                decision.system_mode,
                super_saving=super_saving,
                house_consumption_entity_id=self._entity_ids.get("house"),
                wasting_context=wasting_context,
            )

            # 6. Discharge over limit: turn off one consumer when discharge_state -> max
            if (
                self.model.discharge_state == "max"
                and self._prev_discharge_state != "max"
            ):
                await async_log_event(
                    self.hass,
                    self.entry.entry_id,
                    "WARN",
                    "SYSTEM",
                    "discharge_over_limit_handling",
                    "Discharge at max; turning off one consumer",
                    {"reason_code": "discharge_max"},
                )
                consumer_list = _normalize_consumer_entity_ids(
                    [c.get(CONF_CONSUMER_SWITCH_ENTITY_ID) for c in consumers_cfg]
                )
                await self.load_manager.discharge_over_limit_turn_off_one(
                    consumer_list,
                    learned_kw=self.consumer_learner.get_learned_kw(),
                )
            self._prev_discharge_state = self.model.discharge_state

            # Recommendation: turn off intermediate devices when battery low and forecast short
            recommended_entity_ids: list[str] = []
            if (
                self._recommended_to_turn_off_entity_ids
                and self.model.battery_status in ("low", "very low")
                and (not self.model.forecast_available or self.model.daily_margin_kwh < 0)
            ):
                recommended_entity_ids = list(self._recommended_to_turn_off_entity_ids)

            # Count consumers (use current config; normalize list for EntitySelector dict format)
            expected_on_count = 0
            actual_on_count = 0
            unknown_actual_count = 0
            consumers_details: dict[str, Any] = {}
            total_actual_power_kw = 0.0
            for eid in consumer_entity_ids:
                state = self.hass.states.get(eid)
                expected_on = bool(state and state.state == "on")
                if expected_on:
                    expected_on_count += 1
                p_kw = consumer_power_kw.get(eid)
                actual = actual_on_map.get(eid)
                if actual is True:
                    actual_on_count += 1
                if actual is None:
                    unknown_actual_count += 1
                if p_kw is not None:
                    total_actual_power_kw += max(0.0, float(p_kw))
                metrics = self.consumer_learner.get_metrics().get(eid, {})
                consumers_details[eid] = {
                    "expected_on": expected_on,
                    "actual_on": actual,
                    "power_kw": round(float(p_kw), 4) if p_kw is not None else None,
                    "energy_today_kwh": metrics.get("energy_per_hour_latest_kwh"),
                    "has_power_sensor": bool(consumer_has_sensor.get(eid)),
                }
            consumers_total = len(consumer_entity_ids)

            # 7. Expose for sensors (forecast already capped by inverter in fetch_and_compute)
            if forecast_available:
                f_next = forecast.forecast_next_hour_kwh
                f_today = forecast.forecast_today_remaining_kwh
                f_tomorrow = forecast.forecast_tomorrow_kwh
                f_tomorrow_hourly = getattr(
                    forecast, "forecast_tomorrow_hourly_kw", []
                )
                f_today_hourly = getattr(
                    forecast, "forecast_today_remaining_hourly_kw", []
                )
                f_today_full_hourly = getattr(
                    forecast, "forecast_today_full_hourly_kw", []
                )
                f_today_hourly_times_iso = getattr(
                    forecast, "forecast_today_hourly_times_iso", []
                )
                f_today_remaining_times_iso = getattr(
                    forecast, "forecast_today_remaining_hourly_times_iso", []
                )
                f_current_hour_index = getattr(
                    forecast, "forecast_current_hour_index", -1
                )
                f_tomorrow_hourly_times_iso = getattr(
                    forecast, "forecast_tomorrow_hourly_times_iso", []
                )
                f_current = getattr(forecast, "forecast_current_power_kw", None) or 0.0
                daily_margin = self.model.daily_margin_kwh
                pv_safe = self.model.pv_remaining_today_safe_kwh
            else:
                f_next = f_today = f_tomorrow = f_current = daily_margin = pv_safe = None
                f_tomorrow_hourly = []
                f_today_hourly = []
                f_today_full_hourly = []
                f_today_hourly_times_iso = []
                f_today_remaining_times_iso = []
                f_current_hour_index = -1
                f_tomorrow_hourly_times_iso = []

            # Battery horizon (forecast) vs instantaneous fallback
            battery_horizon_method = "instantaneous"
            battery_horizon_hourly: list[dict[str, Any]] = []
            battery_horizon_to_full_edge_iso: str | None = None
            battery_horizon_to_very_low_edge_iso: str | None = None

            usable_kwh = max(
                0.0,
                (soc - BATTERY_SOC_VERY_LOW_PERCENT) / 100.0
                * self.model.battery_capacity_kwh,
            )
            discharge_kw = max(self.model.battery_power_kw or 0.0, 0.0)
            battery_runtime_hours: float | None
            battery_runtime_hhmm = "99:59"
            if discharge_kw <= 0:
                battery_runtime_hours = None
            else:
                runtime_hours = usable_kwh / discharge_kw
                battery_runtime_hours = float(runtime_hours)
                battery_runtime_hhmm = _hours_float_to_hhmm(battery_runtime_hours)

            battery_time_to_full_hours: float | None = None
            battery_time_to_full_hhmm = "99:59"
            if soc is not None and soc < EOD_BATTERY_TARGET_PLANNING_PERCENT:
                remaining_kwh = max(
                    0.0,
                    (EOD_BATTERY_TARGET_PLANNING_PERCENT - soc)
                    / 100.0
                    * self.model.battery_capacity_kwh,
                )
                charge_kw = max(-(self.model.battery_power_kw or 0.0), 0.0)
                if charge_kw > 0:
                    charge_hours = remaining_kwh / charge_kw
                    battery_time_to_full_hours = float(charge_hours)
                    battery_time_to_full_hhmm = _hours_float_to_hhmm(
                        battery_time_to_full_hours
                    )
            elif soc is not None and soc >= EOD_BATTERY_TARGET_PLANNING_PERCENT:
                battery_time_to_full_hours = 0.0
                battery_time_to_full_hhmm = "00:00"

            if forecast_available:
                pv_slots = list(f_today_hourly) + list(f_tomorrow_hourly)
                time_slots = list(f_today_remaining_times_iso) + list(
                    f_tomorrow_hourly_times_iso
                )
                if (
                    len(pv_slots) >= 1
                    and len(time_slots) == len(pv_slots)
                    and self.model.battery_capacity_kwh > 0
                ):
                    now_local = dt_util.now()
                    to_full, to_vl = compute_battery_edge_horizons(
                        now_local=now_local,
                        soc_percent=float(soc),
                        capacity_kwh=float(self.model.battery_capacity_kwh),
                        max_charge_kw=float(self.model.max_battery_charge_kw),
                        max_discharge_kw=float(self.model.max_battery_discharge_kw),
                        pv_kw_slots=pv_slots,
                        time_iso_slots=time_slots,
                        baseline_hourly_kw=list(self.model.baseline_hourly_kw),
                        target_full_percent=float(EOD_BATTERY_TARGET_PLANNING_PERCENT),
                        target_very_low_percent=float(BATTERY_SOC_VERY_LOW_PERCENT),
                    )
                    battery_horizon_method = "forecast"
                    battery_horizon_hourly = to_full.hourly_steps[:48]
                    battery_horizon_to_full_edge_iso = to_full.edge_time_iso
                    battery_horizon_to_very_low_edge_iso = to_vl.edge_time_iso
                    if to_full.hours_until is not None:
                        battery_time_to_full_hours = float(to_full.hours_until)
                        battery_time_to_full_hhmm = _hours_float_to_hhmm(
                            battery_time_to_full_hours
                        )
                    else:
                        battery_time_to_full_hours = None
                        battery_time_to_full_hhmm = "99:59"
                    if to_vl.hours_until is not None:
                        battery_runtime_hours = float(to_vl.hours_until)
                        battery_runtime_hhmm = _hours_float_to_hhmm(
                            battery_runtime_hours
                        )
                    else:
                        battery_runtime_hours = None
                        battery_runtime_hhmm = "99:59"

            _LOGGER.debug(
                "update ok: mode=%s strategy=%s",
                decision.system_mode,
                decision.strategy_recommendation,
            )
            return {
                "model": self.model,
                "forecast": forecast,
                "decision": decision,
                "forecast_available": forecast_available,
                "forecast_from_cache": getattr(forecast, "from_cache", False),
                "battery_soc": soc,
                "battery_power_kw": self.model.battery_power_kw,
                "solar_production_kw": self.model.solar_production_kw,
                "house_consumption_kw": self.model.house_consumption_kw,
                "forecast_next_hour_kwh": f_next,
                "forecast_today_remaining_kwh": f_today,
                "forecast_tomorrow_kwh": f_tomorrow,
                "forecast_tomorrow_hourly_kw": f_tomorrow_hourly,
                "forecast_today_remaining_hourly_kw": f_today_hourly,
                "forecast_today_full_hourly_kw": f_today_full_hourly,
                "forecast_today_hourly_times_iso": f_today_hourly_times_iso,
                "forecast_today_remaining_hourly_times_iso": f_today_remaining_times_iso,
                "forecast_current_hour_index": f_current_hour_index,
                "forecast_tomorrow_hourly_times_iso": f_tomorrow_hourly_times_iso,
                "forecast_current_power_kw": f_current,
                "energy_manager_mode": decision.system_mode,
                "strategy_recommendation": decision.strategy_recommendation,
                "strategy_reason": decision.strategy_reason,
                "mode_reason": decision.mode_reason,
                "forecast_remaining_kwh": f_today,
                "battery_reserve_state": self.model.battery_status,
                "daily_margin_kwh": daily_margin,
                "recommended_to_turn_off_entity_ids": recommended_entity_ids,
                "battery_power_state": self.model.battery_power_state,
                "charge_state": self.model.charge_state,
                "discharge_state": self.model.discharge_state,
                "needed_energy_today_kwh": self.model.needed_energy_today_kwh,
                "pv_remaining_today_safe_kwh": pv_safe,
                "hours_until_eod": self.model.hours_until_eod,
                "hours_until_sunrise": hours_until_sunrise,
                "hours_until_first_pv": self.model.hours_until_first_pv,
                "night_bridge_relaxed": self.model.night_bridge_relaxed,
                "night_bridge_tomorrow_ok": self.model.night_bridge_tomorrow_ok,
                "night_bridge_energy_need_kwh": self.model.night_bridge_energy_need_kwh,
                "night_bridge_usable_kwh": self.model.night_bridge_usable_kwh,
                "battery_runtime_hours": battery_runtime_hours,
                "battery_runtime_hhmm": battery_runtime_hhmm,
                "battery_time_to_full_hours": battery_time_to_full_hours,
                "battery_time_to_full_hhmm": battery_time_to_full_hhmm,
                "battery_horizon_method": battery_horizon_method,
                "battery_horizon_hourly": battery_horizon_hourly,
                "battery_horizon_to_full_edge_iso": battery_horizon_to_full_edge_iso,
                "battery_horizon_to_very_low_edge_iso": battery_horizon_to_very_low_edge_iso,
                "consumers_on_count": expected_on_count,
                "consumers_total": consumers_total,
                "consumer_expected_on_count": expected_on_count,
                "consumer_actual_on_count": actual_on_count,
                "consumer_unknown_actual_count": unknown_actual_count,
                "consumer_total_actual_power_kw": round(total_actual_power_kw, 4),
                "consumer_power_status_details": consumers_details,
                "consumer_learned_kw": self.consumer_learner.get_learned_kw(),
                "consumer_learned_power_kw": round(
                    sum(self.consumer_learner.get_learned_kw().values()), 3
                ),
                "consumer_learned_metrics": self.consumer_learner.get_metrics(),
                "consumer_learn_pending_samples": self.consumer_learner.get_pending_counts(),
                "consumer_learn_pending_kw": self.consumer_learner.get_pending_samples_kw(),
                "consumer_budget_raw_kw": round(raw_budget_kw, 3)
                if decision.system_mode == SYSTEM_MODE_WASTING
                else None,
                "consumer_budget_locked_kw": round(
                    self._locked_consumer_budget_kw or 0.0, 3
                )
                if decision.system_mode == SYSTEM_MODE_WASTING
                else None,
                "consumer_budget_effective_kw": round(effective_budget_kw, 3)
                if decision.system_mode == SYSTEM_MODE_WASTING
                else None,
                "consumer_budget_ceilings": {
                    "instant_kw": budget_ceilings.instant_kw,
                    "strategic_kw": budget_ceilings.strategic_kw,
                    "night_spread_kw": budget_ceilings.night_spread_kw,
                    "discharge_kw": budget_ceilings.discharge_kw,
                }
                if budget_ceilings is not None
                else None,
                "consumer_learned_target_ids": sorted(
                    wasting_context.learned_target,
                )
                if wasting_context is not None
                else [],
                "baseline_hourly_forecast_kw": list(self.model.baseline_hourly_kw),
                "baseline_forecast_kw": self.baseline_profile_learner.get_current_hour_forecast_kw(
                    now_local
                ),
                "baseline_estimated_daily_kwh": self.baseline_profile_learner.estimated_daily_kwh(),
                "baseline_completed_days": self.baseline_profile_learner.completed_days_count(),
                "baseline_sample_recorded": baseline_sampled,
                "battery_learned_max_discharge_kw": round(learned_d, 3),
                "battery_learned_max_charge_kw": round(learned_c, 3),
                "battery_effective_max_discharge_kw": round(
                    self.model.max_battery_discharge_kw, 3
                ),
                "battery_effective_max_charge_kw": round(
                    self.model.max_battery_charge_kw, 3
                ),
                "battery_peak_manual_discharge_kw": manual_d if manual_d > 0 else None,
                "battery_peak_manual_charge_kw": manual_c if manual_c > 0 else None,
                "battery_peak_sample_ticks": self.battery_peak_learner.sample_ticks,
                "battery_peak_learn_state": (
                    "manual"
                    if (manual_d > 0 or manual_c > 0)
                    else "auto"
                ),
                **self._integration_alert_data(),
            }
        except Exception as e:
            _LOGGER.exception("Error updating energy manager: %s", e)
            try:
                await async_log_event(
                    self.hass,
                    self.entry.entry_id,
                    "ERROR",
                    "SYSTEM",
                    "coordinator_update_failed",
                    "Coordinator update raised an exception",
                    {"reason_code": "exception", "error": str(e)},
                )
            except Exception:  # noqa: BLE001
                pass
            raise UpdateFailed(str(e)) from e

