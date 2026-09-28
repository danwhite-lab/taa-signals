"""Declarative, research-only validation contracts for strategy implementations.

Profiles describe tests that a future Research engine may run.  They never
change a strategy's production parameters, current signal, or backtest path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParameterSpec:
    """A published setting and its pre-approved research sensitivity values."""

    key: str
    published_value: Any
    candidate_values: tuple[Any, ...]
    description: str
    unit: str | None = None


@dataclass(frozen=True)
class ProxySpec:
    """A declared execution substitute for proxy-robustness research."""

    source_asset: str
    proxy_asset: str
    description: str
    currency: str | None = None


@dataclass(frozen=True)
class ExecutionSpec:
    """Production timing plus bounded, realistic timing stress scenarios."""

    rebalance_frequency: str
    production_timing: str
    delay_business_days: tuple[int, ...] = (0, 1, 2)
    rebalance_shifts_business_days: tuple[int, ...] = (0,)


@dataclass(frozen=True)
class ValidationProfile:
    """Research contract attached to a strategy class.

    ``applicable_tests`` deliberately makes unsupported analyses explicit.
    Future validation code must report a test outside this set as not
    applicable, rather than silently inventing a parameter or proxy.
    """

    profile_id: str
    published_parameters: tuple[ParameterSpec, ...]
    execution: ExecutionSpec
    applicable_tests: frozenset[str]
    proxy_substitutions: tuple[ProxySpec, ...] = ()
    rolling_windows_years: tuple[int, ...] = (5, 10, 20)
    data_confidence: str = "moderate"
    notes: str = ""


def profile_for(strategy: object | type) -> ValidationProfile | None:
    """Return an optional immutable validation profile for a strategy instance/class."""
    strategy_class = strategy if isinstance(strategy, type) else type(strategy)
    profile = getattr(strategy_class, "validation_profile", None)
    if profile is not None and not isinstance(profile, ValidationProfile):
        raise TypeError(f"{strategy_class.__name__}.validation_profile must be a ValidationProfile.")
    return profile
