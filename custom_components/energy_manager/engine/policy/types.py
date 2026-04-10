"""Policy layer datatypes (strategy / mode / load constraints)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyAdvice:
    """Forecast- (or SOC-fallback) driven battery strategy target."""

    strategy: str
    reason: str


@dataclass(frozen=True)
class ModeAdvice:
    """Suggested system_mode from SOC vs strategy and forecast headroom."""

    system_mode: str
    mode_reason: str


@dataclass(frozen=True)
class EmergencyAdvice:
    """High-priority mode override (max charge waste, very low SOC)."""

    system_mode: str
    mode_reason: str


@dataclass(frozen=True)
class EmergencyEvaluation:
    """Emergency layer: optional mode override + load guard hints (discharge ceiling)."""

    mode_override: EmergencyAdvice | None = None
    suppress_wasting_turn_ons: bool = False
    force_shed_one_consumer: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    """Merged policy output (extends legacy DecisionResult fields + execution hints)."""

    strategy_recommendation: str
    strategy_reason: str
    system_mode: str
    mode_reason: str
    suppress_wasting_turn_ons: bool = False
    force_shed_one_consumer: bool = False
