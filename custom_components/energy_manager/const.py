"""Constants for the Energy Manager integration."""

DOMAIN = "energy_manager"
NAME = "Energy Manager"

# Operation log (TXT under config_dir/energy_manager_logs/) — not exposed in UI yet
INTEGRATION_LOG_ENABLED = True
INTEGRATION_LOG_SCHEMA_VERSION = 2
INTEGRATION_LOG_MAX_BYTES = 2_000_000
INTEGRATION_LOG_DEDUPE_WINDOW_SEC = 300.0
# Categories that may spam (Open-Meteo, repeated system notices); ACTION never deduped inside logger
INTEGRATION_LOG_DEDUPE_CATEGORIES = frozenset({"FORECAST", "SYSTEM"})
INTEGRATION_LOG_SUMMARY_MAX_LEN = 200
INTEGRATION_LOG_CONTEXT_MAX_LEN = 480

# In-memory alert feed (mirrors successful ops log writes) + last-alert sensor
INTEGRATION_ALERTS_MAX = 20
INTEGRATION_ALERTS_DISPLAY_MAX = 10
DATA_INTEGRATION_ALERT_LAST = "integration_alert_last"
DATA_INTEGRATION_ALERTS = "integration_alerts"
DATA_INTEGRATION_ALERTS_DISPLAY = "integration_alerts_display"
# Sensor entity key (unique_id suffix)
SENSOR_KEY_INTEGRATION_LAST_ALERT = "integration_last_alert"
INTEGRATION_ALERT_STATE_MAX_LEN = 255

# Service: clear learned per-consumer power (optional manual reset)
SERVICE_RESET_CONSUMER_LEARN = "reset_consumer_learn"
# Service: clear in-memory integration alert ring buffer
SERVICE_CLEAR_INTEGRATION_ALERTS = "clear_integration_alerts"

# Consumer power learning (house meter delta when integration turns a consumer on)
# Delay between consumer actions in wasting (minutes; not user-facing): learned vs unlearned.
# Unlearned interval is also used between turn-offs in Normal mode (LIFO ramp-down).
CONSUMER_ACTION_DELAY_LEARNED_MINUTES = 1
CONSUMER_ACTION_DELAY_UNLEARNED_MINUTES = 5
# Minimum time a consumer must stay on after the integration turns it on, before we may turn it off
# again (wasting / normal LIFO). Saving mode and discharge_over_limit ignore this.
CONSUMER_MIN_ON_MINUTES = 5
# Hysteresis: only adopt new raw budget if relative change >= this ratio vs last locked budget
# (fixed in code; not exposed in config UI)
DEFAULT_CONSUMER_BUDGET_HYSTERESIS_RATIO = 0.15
# Discharge: keep this fraction of max discharge power (kW) as headroom — single source for
# consumer budget ceiling and discharge_state thresholds (not user-configurable).
DISCHARGE_HEADROOM_FRACTION = 0.30
# Hysteresis for discharge_under_limit: band below operational ceiling, as fraction of full max kW
DISCHARGE_DEADBAND_FRACTION_OF_MAX = 0.05

# Unified battery power direction + level (ENUM sensor); derived from charge_state + discharge_state
BATTERY_POWER_STATE_OFF = "off"
BATTERY_POWER_STATE_CHARGE = "charge"
BATTERY_POWER_STATE_MAX_CHARGE = "max_charge"
BATTERY_POWER_STATE_DISCHARGE = "discharge"
BATTERY_POWER_STATE_MAX_DISCHARGE = "max_discharge"
BATTERY_POWER_STATE_OPTIONS: tuple[str, ...] = (
    BATTERY_POWER_STATE_OFF,
    BATTERY_POWER_STATE_CHARGE,
    BATTERY_POWER_STATE_MAX_CHARGE,
    BATTERY_POWER_STATE_DISCHARGE,
    BATTERY_POWER_STATE_MAX_DISCHARGE,
)

# Legacy: used only for migration seed (old max amps → kW). Runtime logic uses power (kW) only.
DEFAULT_BATTERY_NOMINAL_VOLTAGE = 51.0
# Minimum effective max charge/discharge power (kW) to avoid degenerate thresholds
MIN_EFFECTIVE_MAX_BATTERY_POWER_KW = 0.5
# Daily margin (kWh) tiers for strategic waste cap — max consumer budget kW per band
CONSUMER_BUDGET_MARGIN_NEG_CAP_KW = 0.0
CONSUMER_BUDGET_MARGIN_HIGH_CAP_KW = 3.0  # daily_margin <= MARGIN_HIGH_THRESHOLD
CONSUMER_BUDGET_MARGIN_MEDIUM_CAP_KW = 8.0  # up to MARGIN_MEDIUM_MAX
CONSUMER_BUDGET_MARGIN_LARGE_CAP_KW = 80.0  # plenty of headroom

CONSUMER_LEARN_MIN_SAMPLES = 3
CONSUMER_LEARN_MAX_SAMPLES = 12
# Finalize when (max-min)/mean <= this ratio, or after dropping one outlier
CONSUMER_LEARN_SPREAD_MAX = 0.10
# Wait for house sensor to publish a new state after turn_on
CONSUMER_LEARN_TIMEOUT_SEC = 120.0

# Update interval for coordinator (seconds)
UPDATE_INTERVAL = 30
# Ops log: full SYSTEM snapshot interval (seconds)
HOURLY_SNAPSHOT_INTERVAL_SEC = 3600
# Forecast and strategy cache (minutes) – fetch/update every 15 min, use cache between
FORECAST_STRATEGY_CACHE_MINUTES = 15

# Battery strategy levels (same as YAML: low, medium, high, full)
STRATEGY_LOW = "low"
STRATEGY_MEDIUM = "medium"
STRATEGY_HIGH = "high"
STRATEGY_FULL = "full"
STRATEGY_OPTIONS = [STRATEGY_LOW, STRATEGY_MEDIUM, STRATEGY_HIGH, STRATEGY_FULL]

# Battery status levels (from PV Battery Status logic)
BATTERY_VERY_LOW = "very low"
BATTERY_LOW = "low"
BATTERY_MEDIUM = "medium"
BATTERY_HIGH = "high"
BATTERY_FULL = "full"
# SOC % below which status is BATTERY_VERY_LOW (also base for emergency planning reserve)
BATTERY_SOC_VERY_LOW_PERCENT = 15
# Planning emergency reserve (needed_energy_today, night bridge) = very_low_threshold + this (not user-config)
EMERGENCY_RESERVE_OFFSET_ABOVE_VERY_LOW_PERCENT = 5
EMERGENCY_RESERVE_PLANNING_PERCENT = float(
    BATTERY_SOC_VERY_LOW_PERCENT + EMERGENCY_RESERVE_OFFSET_ABOVE_VERY_LOW_PERCENT
)
# Planning target for end of local day (% SOC). Matches EnergyModel battery_status "full" (SOC >= 95).
EOD_BATTERY_TARGET_PLANNING_PERCENT = 95.0

# Energy mode (energy_saver equivalent)
MODE_OFF = "Off"
MODE_ENERGY_SAVING = "Energy saving"
MODE_SUPER_ENERGY_SAVING = "Super energy saving"
MODE_ENERGY_WASTING = "Energy wasting"
MODE_MAX_ENERGY_WASTING = "Max energy wasting"
ENERGY_MODES = [
    MODE_OFF,
    MODE_ENERGY_SAVING,
    MODE_SUPER_ENERGY_SAVING,
    MODE_ENERGY_WASTING,
    MODE_MAX_ENERGY_WASTING,
]

# Simplified modes for decision engine output (saving / normal / wasting / emergency_saving)
SYSTEM_MODE_SAVING = "saving"
SYSTEM_MODE_NORMAL = "normal"
SYSTEM_MODE_WASTING = "wasting"
SYSTEM_MODE_EMERGENCY_SAVING = "emergency_saving"

# Daily margin thresholds for strategy recommendation (kWh)
MARGIN_HIGH_THRESHOLD = 20
MARGIN_MEDIUM_MAX = 40

# Open-Meteo API
OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_HOURLY = "shortwave_radiation,direct_radiation,diffuse_radiation,direct_normal_irradiance"
OPEN_METEO_FORECAST_DAYS = 2

# Config keys
CONF_BATTERY_SOC_SENSOR = "battery_soc_sensor"
CONF_BATTERY_POWER_SENSOR = "battery_power_sensor"
CONF_SOLAR_PRODUCTION_SENSOR = "solar_production_sensor"
CONF_HOUSE_CONSUMPTION_SENSOR = "house_consumption_sensor"
CONF_CONSUMER_SWITCHES = "consumer_switches"
CONF_CONSUMERS = "consumers"
CONF_CONSUMER_SWITCH_ENTITY_ID = "switch_entity_id"
CONF_CONSUMER_POWER_SENSOR_ENTITY_ID = "power_sensor_entity_id"
CONF_BATTERY_CAPACITY = "battery_capacity"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_STRINGS = "strings"
CONF_SYSTEM_SIZE_KW = "system_size_kw"
CONF_TILT = "tilt"
CONF_AZIMUTH = "azimuth"
CONF_MAX_BATTERY_DISCHARGE_POWER_KW = "max_battery_discharge_power_kw"
CONF_MAX_BATTERY_CHARGE_POWER_KW = "max_battery_charge_power_kw"
CONF_MANUAL_OVERRIDE = "manual_override"  # legacy: when True, both overrides on
CONF_MANUAL_MODE_OVERRIDE = "manual_mode_override"
CONF_MANUAL_STRATEGY_OVERRIDE = "manual_strategy_override"
CONF_MANUAL_MODE = "manual_mode"
CONF_MANUAL_STRATEGY = "manual_strategy"
CONF_LIGHTS_TO_TURN_OFF = "lights_to_turn_off"
CONF_RECOMMENDED_TO_TURN_OFF = "recommended_to_turn_off"
CONF_INVERTER_SIZE_KW = "inverter_size_kw"
CONF_FORECAST_PR = "forecast_pr"
CONF_BATTERY_HORIZON_VERBOSE_ATTRIBUTES = "battery_horizon_verbose_attributes"

# Defaults (from YAML initial values)
DEFAULT_LATITUDE = 32.08
DEFAULT_LONGITUDE = 34.78
DEFAULT_BATTERY_CAPACITY = 20.0

# Learned hourly baseline: bootstrap kW per hour until enough completed days; rolling window length
BASELINE_PROFILE_BOOTSTRAP_KW = 0.5
BASELINE_PROFILE_WINDOW_DAYS = 7
# PV forecast safety margin (percent of Open-Meteo kWh); fixed — not user-configurable
DEFAULT_SAFETY_FORECAST_FACTOR = 90
# Legacy default max battery current (A) — only for migration seed; not in UI
DEFAULT_MAX_BATTERY_CURRENT_AMPS = 36
DEFAULT_INVERTER_SIZE_KW = 0  # 0 = no cap
DEFAULT_FORECAST_PR = 0.75
# String (PV) defaults – used in config flow when no strings configured yet
DEFAULT_SYSTEM_SIZE_KW = 5.0
DEFAULT_TILT = 30.0
DEFAULT_AZIMUTH = 0.0

# Runtime sensor: battery usable down to this SOC %
BATTERY_RUNTIME_MIN_SOC_PERCENT = 10

# Max strings (phase 1: 2)
MAX_STRINGS = 2

# Night bridge: relax "no PV next hour" strategy when safe to drain toward sunrise
NIGHT_BRIDGE_HOURS_BEFORE_SUNRISE = 2.0
# First forecast hour with PV above this (kW) counts as solar production started
NIGHT_BRIDGE_FORECAST_PV_THRESHOLD_KW = 0.05
# Solar sensor (kW) must be below this while sun is below horizon for "dark" guard
NIGHT_BRIDGE_SOLAR_SENSOR_THRESHOLD_KW = 0.05

# Consumer telemetry (internal power is kW; ~10 W on threshold)
CONSUMER_ACTIVE_POWER_THRESHOLD_KW = 0.01
