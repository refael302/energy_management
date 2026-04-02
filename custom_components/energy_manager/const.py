"""Constants for the Energy Manager integration."""

DOMAIN = "energy_manager"
NAME = "Energy Manager"

# Service: clear learned per-consumer power (optional manual reset)
SERVICE_RESET_CONSUMER_LEARN = "reset_consumer_learn"

# Consumer power learning (house meter delta when integration turns a consumer on)
# Delay between consumer actions: learned vs not yet learned (minutes; hardcoded, not user-facing)
CONSUMER_ACTION_DELAY_LEARNED_MINUTES = 1
CONSUMER_ACTION_DELAY_UNLEARNED_MINUTES = 5
# Hysteresis: only adopt new raw budget if relative change >= this ratio vs last locked budget
# (fixed in code; not exposed in config UI)
DEFAULT_CONSUMER_BUDGET_HYSTERESIS_RATIO = 0.15
# Reserve fraction of battery discharge headroom (0.3 = leave 30% for user / transients)
# (fixed in code; not exposed in config UI)
DEFAULT_CONSUMER_DISCHARGE_RESERVE_RATIO = 0.30
# Assumed DC V for kW estimate when only battery current is available (48V nominal system)
DEFAULT_BATTERY_NOMINAL_VOLTAGE = 51.0
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
# Forecast and strategy cache (minutes) – fetch/update every 15 min, use cache between
FORECAST_STRATEGY_CACHE_MINUTES = 15

# Battery strategy levels (same as YAML: low, medium, high, full)
STRATEGY_LOW = "low"
STRATEGY_MEDIUM = "medium"
STRATEGY_HIGH = "high"
STRATEGY_FULL = "full"
STRATEGY_OPTIONS = [STRATEGY_LOW, STRATEGY_MEDIUM, STRATEGY_HIGH, STRATEGY_FULL]

# Battery status levels (from PV Battery Status logic)
BATTERY_VERY_LOW = "very low"   # < 15%
BATTERY_LOW = "low"             # < 30%
BATTERY_MEDIUM = "medium"       # < 70%
BATTERY_HIGH = "high"           # < 95%
BATTERY_FULL = "full"           # >= 95%

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
CONF_BATTERY_CAPACITY = "battery_capacity"
CONF_MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
CONF_SAFETY_FORECAST_FACTOR = "safety_forecast_factor"
CONF_CONSUMER_DELAY = "consumer_delay"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_STRINGS = "strings"
CONF_SYSTEM_SIZE_KW = "system_size_kw"
CONF_TILT = "tilt"
CONF_AZIMUTH = "azimuth"
CONF_EOD_BATTERY_TARGET = "eod_battery_target"
CONF_MAX_BATTERY_CURRENT_AMPS = "max_battery_current_amps"
CONF_DISCHARGE_LIMIT_PERCENT = "discharge_limit_percent"
CONF_DISCHARGE_LIMIT_DEADBAND_PERCENT = "discharge_limit_deadband_percent"
CONF_BATTERY_CURRENT_SENSOR = "battery_current_sensor"
CONF_MANUAL_OVERRIDE = "manual_override"  # legacy: when True, both overrides on
CONF_MANUAL_MODE_OVERRIDE = "manual_mode_override"
CONF_MANUAL_STRATEGY_OVERRIDE = "manual_strategy_override"
CONF_MANUAL_MODE = "manual_mode"
CONF_MANUAL_STRATEGY = "manual_strategy"
CONF_LIGHTS_TO_TURN_OFF = "lights_to_turn_off"
CONF_RECOMMENDED_TO_TURN_OFF = "recommended_to_turn_off"
CONF_INVERTER_SIZE_KW = "inverter_size_kw"
CONF_FORECAST_PR = "forecast_pr"

# Defaults (from YAML initial values)
DEFAULT_LATITUDE = 32.08
DEFAULT_LONGITUDE = 34.78
DEFAULT_BATTERY_CAPACITY = 20.0
DEFAULT_MINIMUM_BATTERY_RESERVE = 20

# Learned hourly baseline: bootstrap kW per hour until enough completed days; rolling window length
BASELINE_PROFILE_BOOTSTRAP_KW = 0.5
BASELINE_PROFILE_WINDOW_DAYS = 7
DEFAULT_SAFETY_FORECAST_FACTOR = 90
DEFAULT_CONSUMER_DELAY = 5
DEFAULT_EOD_BATTERY_TARGET = 90
DEFAULT_MAX_BATTERY_CURRENT_AMPS = 36
DEFAULT_DISCHARGE_LIMIT_PERCENT = 80
DEFAULT_DISCHARGE_LIMIT_DEADBAND_PERCENT = 5
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
