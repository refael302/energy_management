# Energy Manager

Home Assistant custom integration for **solar home energy management**: battery state, PV production, house consumption, **Open-Meteo + pvlib** solar forecast, strategy recommendations, and **automatic consumer (switch) control** with delays and priorities.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories)

## Features

- **Sensors** — Battery SOC, battery power, solar production, house consumption, forecast remaining / next hour / tomorrow, daily margin, hours until sunset & sunrise, diagnostic charge/discharge states, and more.
- **Solar forecast** — Hourly irradiance from [Open-Meteo](https://open-meteo.com/), plane-of-array and power via [pvlib](https://pvlib-python.readthedocs.io/), support for **multiple PV strings** (tilt, azimuth, size) and optional inverter AC cap. **Hourly kW (after PR) is saved** under Home Assistant’s `.storage` when a fetch succeeds; if the API is down, the integration **rebuilds the forecast from that cache** (when the series still covers “now” and your PV geometry matches).
- **Decision engine** — Modes: `saving`, `normal`, `wasting`, `emergency_saving`; battery strategy levels: `low` / `medium` / `high` / `full` based on daily margin and next-hour PV vs consumption. **If the solar forecast is unavailable**, strategy follows **SOC bands** so the system can still waste down one level at a time (e.g. full→high→medium→low); **low / very low** stay conservative (`FULL`).
- **Night bridge** — In the ~2 hours before sunrise, when it is dark and conditions are safe (including tomorrow’s forecast vs. charging needs), the integration can relax the strict “no PV next hour → full strategy” rule so behaviour matches long daily surplus without staying stuck conservative before dawn.
- **Load manager** — Turns consumers (switches / `input_boolean`) on in **wasting** mode with a configurable delay; turns them off gradually when returning to **normal**; optional lights / devices for super-saving; discharge-over-limit can turn off one consumer.

## Requirements

- Home Assistant (Supervised, Container, or OS).
- Python packages (installed automatically by HA): `pvlib`, `aiohttp`, `pandas` (see `manifest.json`).

## Installation (HACS)

1. Open **HACS** → **Integrations** → **⋮** → **Custom repositories**.
2. Add repository URL: `https://github.com/refael302/energy_management`, category **Integration**.
3. Install **Energy Manager** and restart Home Assistant.
4. Add the integration via **Settings** → **Devices & services** → **Add integration** → **Energy Manager**.

## Configuration

Configuration is done through the UI (config flow): battery and power sensors, optional current sensor, PV string geometry, baseline consumption, safety forecast factor, emergency reserve, EOD battery target, consumers, delays, manual overrides, etc.

## Documentation & support

- **Documentation / repository:** [github.com/refael302/energy_management](https://github.com/refael302/energy_management)
- **Issues:** [GitHub Issues](https://github.com/refael302/energy_management/issues)

## Project layout

```text
custom_components/energy_manager/   # Integration package
hacs.json                           # HACS metadata (render_readme)
```

---

*Hebrew overview is also available in [`custom_components/energy_manager/info.md`](custom_components/energy_manager/info.md).*
