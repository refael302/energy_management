"""
Register energy_manager subpackages without loading integration __init__.py (no homeassistant).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _ensure_energy_manager_pkg() -> None:
    if "energy_manager.const" in sys.modules:
        return
    root = Path(__file__).resolve().parents[1]
    cc = root / "custom_components"
    em_root = cc / "energy_manager"
    eng_root = em_root / "engine"

    def load_file(qualname: str, path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(qualname, path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[qualname] = mod
        spec.loader.exec_module(mod)
        return mod

    em = ModuleType("energy_manager")
    em.__path__ = [str(em_root)]
    sys.modules["energy_manager"] = em

    eng = ModuleType("energy_manager.engine")
    eng.__path__ = [str(eng_root)]
    sys.modules["energy_manager.engine"] = eng

    pol = ModuleType("energy_manager.engine.policy")
    pol.__path__ = [str(eng_root / "policy")]
    sys.modules["energy_manager.engine.policy"] = pol

    load_file("energy_manager.const", em_root / "const.py")
    load_file("energy_manager.engine.baseline_integrals", eng_root / "baseline_integrals.py")
    load_file("energy_manager.engine.energy_model", eng_root / "energy_model.py")
    load_file(
        "energy_manager.engine.policy.types",
        eng_root / "policy" / "types.py",
    )
    load_file(
        "energy_manager.engine.policy.forecast_strategy_advisor",
        eng_root / "policy" / "forecast_strategy_advisor.py",
    )
    load_file(
        "energy_manager.engine.policy.state_mode_advisor",
        eng_root / "policy" / "state_mode_advisor.py",
    )
    load_file(
        "energy_manager.engine.policy.emergency_advisor",
        eng_root / "policy" / "emergency_advisor.py",
    )
    load_file(
        "energy_manager.engine.policy.arbiter",
        eng_root / "policy" / "arbiter.py",
    )
    _ensure_telegram_bridge_mocks()
    load_file("energy_manager.telegram_messages", em_root / "telegram_messages.py")
    load_file("energy_manager.telegram_bridge", em_root / "telegram_bridge.py")


def _ensure_telegram_bridge_mocks() -> None:
    if "homeassistant.core" in sys.modules:
        return
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")

    class HomeAssistant:  # noqa: D101
        pass

    ha_core.HomeAssistant = HomeAssistant
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core

    aiohttp_mod = ModuleType("aiohttp")

    class ClientSession:  # noqa: D101
        pass

    class ClientError(Exception):  # noqa: D101
        pass

    class ClientTimeout:  # noqa: D101
        def __init__(self, total: float = 0) -> None:
            self.total = total

    aiohttp_mod.ClientSession = ClientSession
    aiohttp_mod.ClientError = ClientError
    aiohttp_mod.ClientTimeout = ClientTimeout
    sys.modules["aiohttp"] = aiohttp_mod


_ensure_energy_manager_pkg()
