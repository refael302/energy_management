"""Constants for the Energy Manager integration."""

DOMAIN = "energy_manager"
NAME = "Energy Manager"

# Update interval for coordinator (seconds)
UPDATE_INTERVAL = 30

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

# Simplified modes for decision engine output (saving / normal / wasting)
SYSTEM_MODE_SAVING = "saving"
SYSTEM_MODE_NORMAL = "normal"
SYSTEM_MODE_WASTING = "wasting"

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
CONF_BASELINE_CONSUMPTION = "baseline_consumption"
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
CONF_MANUAL_OVERRIDE = "manual_override"
CONF_MANUAL_MODE = "manual_mode"
CONF_MANUAL_STRATEGY = "manual_strategy"
CONF_LIGHTS_TO_TURN_OFF = "lights_to_turn_off"
CONF_RECOMMENDED_TO_TURN_OFF = "recommended_to_turn_off"

# Defaults (from YAML initial values)
DEFAULT_BATTERY_CAPACITY = 20.0
DEFAULT_BASELINE_CONSUMPTION = 0.8
DEFAULT_MINIMUM_BATTERY_RESERVE = 20
DEFAULT_SAFETY_FORECAST_FACTOR = 90
DEFAULT_CONSUMER_DELAY = 5
DEFAULT_EOD_BATTERY_TARGET = 90
DEFAULT_MAX_BATTERY_CURRENT_AMPS = 36
DEFAULT_DISCHARGE_LIMIT_PERCENT = 80
DEFAULT_DISCHARGE_LIMIT_DEADBAND_PERCENT = 5

# Max strings (phase 1: 2)
MAX_STRINGS = 2
