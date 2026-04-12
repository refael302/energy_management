# Energy Manager

Home Assistant custom integration for **solar home energy management**: battery state, PV production, house consumption, **Open-Meteo + pvlib** solar forecast, strategy recommendations, and **automatic consumer (switch) control** with delays and priorities.

**Version:** see [`custom_components/energy_manager/manifest.json`](custom_components/energy_manager/manifest.json) (`version` field). Runtime Python dependencies are listed there under `requirements`.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- **Sensors** — Battery SOC, battery power, solar production, house consumption, forecast remaining / next hour / tomorrow, daily margin, hours until sunset & sunrise, diagnostic charge/discharge states, integration last-alert text, and more.
- **Solar forecast** — Hourly irradiance from [Open-Meteo](https://open-meteo.com/), plane-of-array and power via [pvlib](https://pvlib-python.readthedocs.io/), support for **multiple PV strings** (tilt, azimuth, size) and optional inverter AC cap. **Hourly kW (after PR) is saved** under Home Assistant’s `.storage` when a fetch succeeds; if the API is down, the integration **rebuilds the forecast from that cache** (when the series still covers “now” and your PV geometry matches).
- **Decision engine** — Modes: `saving`, `normal`, `wasting`, `emergency_saving`; battery strategy levels: `low` / `medium` / `high` / `full` based on daily margin and next-hour PV vs consumption. **If the solar forecast is unavailable**, strategy follows **SOC bands** so the system can still waste down one level at a time (e.g. full→high→medium→low); **low / very low** stay conservative (`FULL`).
- **Night bridge** — In the ~2 hours before sunrise, when it is dark and conditions are safe (including tomorrow’s forecast vs. charging needs), the integration can relax the strict “no PV next hour → full strategy” rule so behaviour matches long daily surplus without staying stuck conservative before dawn.
- **Load manager** — Turns consumers (switches / `input_boolean`) on in **wasting** mode with a configurable delay; turns them off gradually when returning to **normal**; optional lights / devices for super-saving; discharge-over-limit can turn off one consumer.
- **Select entities** — When **Manual Mode Override** or **Manual Strategy Override** is enabled, use the matching **Select** entities to choose mode or strategy (see config flow).
- **Optional Telegram** — Config flow menu **Telegram**: forward ops-log style events to chats, optional command polling (bot token and chat IDs in options).
- **Diagnostics & logging** — Optional **text operation log** under your HA config directory (`energy_manager_logs/`); an in-memory **integration alerts** ring drives a **last alert** sensor. Services can clear alerts or reset learned consumer power (see below).

## Services

Registered for use in **Developer tools → Services** (schemas in [`custom_components/energy_manager/services.yaml`](custom_components/energy_manager/services.yaml)):

| Service | Purpose |
|--------|---------|
| `energy_manager.reset_consumer_learn` | Clears learned per-consumer power; optional `config_entry_id` to target one entry. |
| `energy_manager.clear_integration_alerts` | Clears the in-memory alert buffer / last-alert sensor; optional `config_entry_id`. |

## Requirements

- Home Assistant (Supervised, Container, or OS).
- Python packages (installed automatically by HA): `pvlib`, `aiohttp`, `pandas` (see `manifest.json`).

## Installation (HACS)

1. Open **HACS** → **Integrations** → **⋮** → **Custom repositories**.
2. Add repository URL: `https://github.com/refael302/energy_management`, category **Integration**.
3. Install **Energy Manager** and restart Home Assistant.
4. Add the integration via **Settings** → **Devices & services** → **Add integration** → **Energy Manager**.

## Configuration

Configuration is done through the UI (config flow): battery and power sensors, optional current sensor, PV string geometry, baseline consumption, safety forecast factor, emergency reserve, EOD battery target, consumers, delays, manual overrides, **Telegram** (optional), etc.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

CI runs the same on Python 3.12 and 3.13 (see [`.github/workflows/tests.yml`](.github/workflows/tests.yml)).

## Documentation & support

- **Documentation / repository:** [github.com/refael302/energy_management](https://github.com/refael302/energy_management)
- **Issues:** [GitHub Issues](https://github.com/refael302/energy_management/issues)

## License

This project is licensed under the [MIT License](LICENSE).

## Project layout

```text
.github/workflows/          # CI (pytest)
custom_components/energy_manager/
  __init__.py               # Setup, platforms, services
  manifest.json             # Domain, version, HA requirements
  coordinator.py            # Data updates, orchestration
  config_flow.py            # UI configuration
  const.py                  # Domain constants, log/alert tuning
  integration_log.py        # Optional file log + alert feed
  telegram_bridge.py        # Optional Telegram notifications / commands
  services.yaml             # Service descriptions for HA UI
  entities/                 # Sensor, switch, select implementations
  engine/                   # Forecast, model, load manager, policy/
  translations/             # en.json, he.json
  brand/                    # icon.png (integration branding)
  info.md                   # Hebrew overview
hacs.json                   # HACS metadata (render_readme)
requirements-dev.txt        # pytest (local + CI)
pyproject.toml              # pytest configuration
tests/                      # Unit tests (no full HA runtime)
```

---

*Hebrew overview: [`custom_components/energy_manager/info.md`](custom_components/energy_manager/info.md).*
