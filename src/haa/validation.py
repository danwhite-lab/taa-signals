"""Declarative, research-only validation contracts for strategy implementations.

Profiles describe tests that a future Research engine may run.  They never
change a strategy's production parameters, current signal, or backtest path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from .engine import BacktestResult, run_backtest
from .metrics import performance_metrics


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


@dataclass(frozen=True)
class ValidationInput:
    """All immutable inputs required to validate one already-defined strategy."""

    name: str
    decisions: pd.DataFrame
    monthly_prices: pd.DataFrame
    daily_prices: pd.DataFrame | None
    benchmark_asset: str
    profile: ValidationProfile
    # Execution-only proxy prices.  Signals remain the supplied published
    # decisions; the proxy is never allowed to rewrite their inputs.
    proxy_monthly_prices: Mapping[str, pd.Series] = field(default_factory=dict)
    proxy_daily_prices: Mapping[str, pd.Series] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    """Standardised deterministic research output; intentionally UI-agnostic."""

    scenarios: pd.DataFrame
    rolling_periods: pd.DataFrame
    subperiods: pd.DataFrame
    data_quality: pd.DataFrame


DEFAULT_SUBPERIODS: tuple[tuple[str, str, str], ...] = (
    ("pre_gfc", "2003-01-01", "2007-12-31"),
    ("global_financial_crisis", "2008-01-01", "2009-12-31"),
    ("post_gfc_expansion", "2010-01-01", "2019-12-31"),
    ("pandemic_inflation", "2020-01-01", "2022-12-31"),
    ("recent", "2023-01-01", "2099-12-31"),
)


def _metrics_row(result: BacktestResult, initial_investment: float, value_column: str) -> dict[str, float]:
    return performance_metrics(result.monthly[value_column], initial_investment)


def _scenario_row(test: str, scenario: str, result: BacktestResult | None, initial_investment: float, value_column: str = "pre_tax_value", detail: str = "") -> dict[str, object]:
    if result is None:
        return {"test": test, "scenario": scenario, "status": "unavailable", "detail": detail}
    return {
        "test": test,
        "scenario": scenario,
        "status": "complete",
        "detail": detail,
        "holding_periods": len(result.monthly),
        "first_holding_end": result.monthly.index.min(),
        "last_holding_end": result.monthly.index.max(),
        **_metrics_row(result, initial_investment, value_column),
    }


def _run(input_data: ValidationInput, initial_investment: float, *, transaction_cost: float = 0.0, tax_enabled: bool = False, tax_rate: float = 0.25, start: pd.Timestamp | None = None, execution_delay_business_days: int = 0) -> BacktestResult:
    return run_backtest(
        input_data.decisions,
        input_data.monthly_prices,
        initial_investment,
        transaction_cost=transaction_cost,
        tax_enabled=tax_enabled,
        tax_rate=tax_rate,
        start=start,
        daily_prices=input_data.daily_prices,
        benchmark_asset=input_data.benchmark_asset,
        execution_delay_business_days=execution_delay_business_days,
    )


def _replace_execution_asset(decisions: pd.DataFrame, source_asset: str, proxy_asset: str) -> pd.DataFrame:
    """Return research-only decisions with a holding role substituted.

    This intentionally changes only executed holdings.  The decisions were
    calculated first from the production signal series, so a proxy cannot
    leak into a published strategy's signal formula.
    """
    substituted = decisions.copy(deep=True)
    if "target_weights" in substituted:
        def replace_weights(weights: object) -> dict[str, float]:
            result: dict[str, float] = {}
            for asset, weight in dict(weights).items():
                target = proxy_asset if asset == source_asset else asset
                result[target] = result.get(target, 0.0) + float(weight)
            return result
        substituted["target_weights"] = substituted["target_weights"].map(replace_weights)
    if "selected_asset" in substituted:
        substituted["selected_asset"] = substituted["selected_asset"].replace(source_asset, proxy_asset)
    for column in ("selected_assets", "previous_asset"):
        if column in substituted:
            substituted[column] = substituted[column].map(
                lambda value: value.replace(source_asset, proxy_asset) if isinstance(value, str) else value
            )
    return substituted


def _proxy_input(input_data: ValidationInput, proxy: ProxySpec) -> ValidationInput:
    monthly_proxy = input_data.proxy_monthly_prices.get(proxy.proxy_asset)
    if monthly_proxy is None:
        raise ValueError(f"No monthly price series was supplied for declared proxy {proxy.proxy_asset}.")
    monthly_prices = input_data.monthly_prices.drop(columns=proxy.proxy_asset, errors="ignore").join(monthly_proxy.rename(proxy.proxy_asset), how="outer")
    if input_data.daily_prices is None:
        daily_prices = None
    else:
        daily_proxy = input_data.proxy_daily_prices.get(proxy.proxy_asset)
        if daily_proxy is None:
            raise ValueError(f"No daily price series was supplied for declared proxy {proxy.proxy_asset}.")
        daily_prices = input_data.daily_prices.drop(columns=proxy.proxy_asset, errors="ignore").join(daily_proxy.rename(proxy.proxy_asset), how="outer")
    return ValidationInput(
        input_data.name,
        _replace_execution_asset(input_data.decisions, proxy.source_asset, proxy.proxy_asset),
        monthly_prices,
        daily_prices,
        input_data.benchmark_asset,
        input_data.profile,
        input_data.proxy_monthly_prices,
        input_data.proxy_daily_prices,
    )


def data_quality_report(input_data: ValidationInput, baseline: BacktestResult | None = None) -> pd.DataFrame:
    """Summarise source coverage and execution-timing checks without repairs."""
    prices = input_data.daily_prices if input_data.daily_prices is not None else input_data.monthly_prices
    frequency = "daily" if input_data.daily_prices is not None else "monthly"
    rows: list[dict[str, object]] = []
    for asset in prices.columns:
        series = pd.to_numeric(prices[asset], errors="coerce")
        observed = series.dropna()
        intervals = observed.index.to_series().diff().dt.days.dropna()
        rows.append({
            "kind": "asset",
            "asset": asset,
            "frequency": frequency,
            "status": "complete" if not observed.empty else "unavailable",
            "first_observation": observed.index.min() if not observed.empty else pd.NaT,
            "last_observation": observed.index.max() if not observed.empty else pd.NaT,
            "observations": len(observed),
            "missing_observations": int(series.isna().sum()),
            "non_positive_observations": int((observed <= 0).sum()),
            "unchanged_observations": int(observed.diff().eq(0).sum()),
            "max_calendar_gap_days": int(intervals.max()) if not intervals.empty else 0,
        })
    if baseline is None:
        rows.append({"kind": "check", "check": "look_ahead", "status": "unavailable", "detail": "No executable baseline result was available."})
    elif input_data.daily_prices is None:
        rows.append({"kind": "check", "check": "look_ahead", "status": "not_verifiable", "detail": "Daily execution prices were not supplied."})
    else:
        audit = baseline.audit
        passed = bool((pd.to_datetime(audit["execution_date"]) > pd.to_datetime(audit.index)).all())
        rows.append({
            "kind": "check",
            "check": "look_ahead",
            "status": "pass" if passed else "fail",
            "detail": "Every execution date is strictly after its signal date." if passed else "At least one execution date is not after its signal date.",
        })
    return pd.DataFrame(rows)


def _window_rows(test: str, periods: pd.Series, initial_investment: float, windows_years: tuple[int, ...]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for years in windows_years:
        window_months = years * 12
        if len(periods) < window_months:
            rows.append({"test": test, "scenario": f"{years}y", "status": "unavailable", "detail": "Insufficient completed holding periods."})
            continue
        for position in range(0, len(periods) - window_months + 1):
            returns = periods.iloc[position:position + window_months]
            values = initial_investment * (1 + returns).cumprod()
            rows.append({
                "test": test,
                "scenario": f"{years}y",
                "status": "complete",
                "start": returns.index.min(),
                "end": returns.index.max(),
                "holding_periods": len(returns),
                **performance_metrics(values, initial_investment),
            })
    return rows


def run_deterministic_validation(input_data: ValidationInput, initial_investment: float = 100_000.0) -> ValidationReport:
    """Run declared, deterministic robustness checks without altering live rules.

    The caller supplies the normal production decisions.  This is deliberate:
    research scenarios cannot silently substitute optimised production signals.
    Parameter sweeps and decision-date shifts require explicit
    strategy-specific adapters. Declared execution proxies are supported
    when their local monthly and daily series are explicitly supplied.
    """
    profile = input_data.profile
    rows: list[dict[str, object]] = []
    try:
        baseline = _run(input_data, initial_investment)
    except ValueError as exc:
        unavailable = _scenario_row("baseline", "published", None, initial_investment, detail=str(exc))
        return ValidationReport(pd.DataFrame([unavailable]), pd.DataFrame(), pd.DataFrame(), data_quality_report(input_data))
    rows.append(_scenario_row("baseline", "published", baseline, initial_investment))

    if "execution_delay" in profile.applicable_tests:
        for delay in profile.execution.delay_business_days:
            try:
                result = _run(input_data, initial_investment, execution_delay_business_days=delay)
                rows.append(_scenario_row("execution_delay", f"+{delay} business day(s)", result, initial_investment))
            except ValueError as exc:
                rows.append(_scenario_row("execution_delay", f"+{delay} business day(s)", None, initial_investment, detail=str(exc)))

    if "transaction_costs" in profile.applicable_tests:
        for cost in (0.0, 0.001, 0.0025):
            try:
                rows.append(_scenario_row("transaction_cost", f"{cost:.2%} per entry/change", _run(input_data, initial_investment, transaction_cost=cost), initial_investment))
            except ValueError as exc:
                rows.append(_scenario_row("transaction_cost", f"{cost:.2%} per entry/change", None, initial_investment, detail=str(exc)))

    if "israeli_tax" in profile.applicable_tests:
        try:
            taxed = _run(input_data, initial_investment, tax_enabled=True, tax_rate=0.25)
            rows.append(_scenario_row("israeli_tax", "25% realised capital-gains tax", taxed, initial_investment, "after_tax_value"))
        except ValueError as exc:
            rows.append(_scenario_row("israeli_tax", "25% realised capital-gains tax", None, initial_investment, detail=str(exc)))

    if "alternate_start_dates" in profile.applicable_tests:
        for year in sorted(set(baseline.monthly.index.year)):
            try:
                rows.append(_scenario_row("alternate_start", str(year), _run(input_data, initial_investment, start=pd.Timestamp(year=year, month=1, day=1)), initial_investment))
            except ValueError as exc:
                rows.append(_scenario_row("alternate_start", str(year), None, initial_investment, detail=str(exc)))

    if "rebalance_shift" in profile.applicable_tests:
        rows.append({
            "test": "rebalance_shift",
            "scenario": "declared shifts",
            "status": "requires_strategy_adapter",
            "detail": "A decision-date shift must recompute strategy signals on shifted dates; it is not approximated as an execution delay.",
        })

    if "parameter_sweep" in profile.applicable_tests:
        rows.append({
            "test": "parameter_sweep",
            "scenario": "declared candidates",
            "status": "requires_strategy_adapter",
            "detail": "Candidate parameters are declared in the profile; a strategy-specific constructor adapter is required to recompute decisions.",
        })

    if "proxy_substitution" in profile.applicable_tests:
        for proxy in profile.proxy_substitutions:
            scenario = f"{proxy.source_asset} → {proxy.proxy_asset}"
            try:
                proxy_result = _run(_proxy_input(input_data, proxy), initial_investment)
                rows.append(_scenario_row("proxy_substitution", scenario, proxy_result, initial_investment, detail=proxy.description))
            except ValueError as exc:
                rows.append(_scenario_row("proxy_substitution", scenario, None, initial_investment, detail=str(exc)))

    rolling = _window_rows("rolling_window", baseline.monthly["pre_tax_monthly_return"], initial_investment, profile.rolling_windows_years) if "rolling_windows" in profile.applicable_tests else []
    subperiod_rows: list[dict[str, object]] = []
    if "subperiods" in profile.applicable_tests:
        for name, start, end in DEFAULT_SUBPERIODS:
            returns = baseline.monthly.loc[(baseline.monthly.index >= pd.Timestamp(start)) & (baseline.monthly.index <= pd.Timestamp(end)), "pre_tax_monthly_return"]
            if returns.empty:
                subperiod_rows.append({"test": "subperiod", "scenario": name, "status": "unavailable", "detail": "No completed holding periods overlap this subperiod."})
                continue
            values = initial_investment * (1 + returns).cumprod()
            subperiod_rows.append({"test": "subperiod", "scenario": name, "status": "complete", "holding_periods": len(returns), "start": returns.index.min(), "end": returns.index.max(), **performance_metrics(values, initial_investment)})
    return ValidationReport(pd.DataFrame(rows), pd.DataFrame(rolling), pd.DataFrame(subperiod_rows), data_quality_report(input_data, baseline))
