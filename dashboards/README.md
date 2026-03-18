# Energy Manager Dashboard

This folder contains a ready-to-use Lovelace dashboard for the Energy Manager integration.

## Files

- **energy_manager.yaml** – Panel dashboard with status, power row, consumers, battery time, forecast chart (today + tomorrow with current hour highlighted), and actual production history chart.

## Requirements

1. **ApexCharts Card** – Install via HACS: [RomRider/apexcharts-card](https://github.com/RomRider/apexcharts-card).
2. **Energy Manager** – The integration must be installed and configured so that all sensors exist.

## Entity IDs

The YAML uses entity IDs with the prefix `sensor.energy_manager_*`. Your actual prefix depends on your device name in Home Assistant.

**How to find your entities:**

1. Go to **Settings** → **Devices** → open your **Energy Manager** device.
2. Under **Entities**, note the entity IDs (e.g. `sensor.my_home_energy_forecast_tomorrow`).
3. In `energy_manager.yaml`, replace every `sensor.energy_manager_` with your prefix (e.g. `sensor.my_home_energy_`).

**Entities used by the dashboard:**

| Dashboard section | Entity key / name (suffix after prefix) |
|------------------|-----------------------------------------|
| Status | `energy_manager_mode`, `mode_reason`, `strategy_recommendation`, `strategy_reason` |
| Power | `solar_production`, `house_consumption`, `battery_soc`, `battery_power` |
| Consumers | `consumers_on` |
| Battery time | `charge_state`, `battery_time_to_full`, `battery_runtime` |
| Forecast chart | `forecast_tomorrow` (uses attributes `hourly_forecast_today`, `hourly_forecast`) |
| Actual production chart | Same as Solar Production (e.g. `solar_production`) – uses 24h history |
| Details | `battery_reserve_state`, `daily_margin`, `recommended_to_turn_off` |

## Adding the dashboard to Home Assistant

### Option A: Include as a dashboard

1. Copy the contents of `energy_manager.yaml` into a new dashboard:
   - **Settings** → **Dashboards** → **Add dashboard** → **Take control** (or use an existing dashboard).
2. Edit the dashboard in YAML mode and paste the content (or use **UI** and add the cards manually).
3. Replace all `sensor.energy_manager_` entity IDs with your prefix (see above).

### Option B: Use as a panel

1. In **Settings** → **Dashboards**, create or edit a dashboard that uses **YAML configuration**.
2. Include this file, for example:
   ```yaml
   views:
     - !include_dir_merge_named dashboards/
   ```
   and ensure the `dashboards` folder (with `energy_manager.yaml` and this README) is in your config directory. Adjust paths if your setup uses a different structure.
3. Update entity IDs inside `energy_manager.yaml` as described above.

## Behaviour

- **Status**: Current mode, reason, strategy recommendation, and reason.
- **Power**: Current solar production, house consumption, battery SOC, and battery power (positive = discharge, negative = charge).
- **Consumers**: Number of consumer devices on (e.g. `2 / 5`).
- **Battery time**:  
  - When **charging** (`charge_state` is `on` or `max`): shows **Time to 100%**.  
  - When **not charging**: shows **Time to 10%** (runtime until 10% SOC).
- **Forecast chart**: Hourly forecast from the current hour through today and all of tomorrow. The **current hour** bar is highlighted in orange.
- **Actual production chart**: Last 24 hours of the solar production sensor (same entity as used in the Power row).
- **Details**: Reserve state, daily margin, and “recommended to turn off” (if configured).
