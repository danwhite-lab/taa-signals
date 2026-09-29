"""Declarative, research-only validation contracts for strategy implementations.

Profiles describe tests that a future Research engine may run.  They never
change a strategy's production parameters, current signal, or backtest path.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
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
class BootstrapSpec:
    """Fixed, reproducible block-bootstrap assumptions for return-path research."""

    simulations: int = 2_000
    block_months: int = 6
    horizons_years: tuple[int, ...] = (5, 10, 20)
    seed: int = 20_260_927


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
    signal_perturbation_bps: tuple[float, ...] = (10.0,)
    bootstrap: BootstrapSpec = field(default_factory=BootstrapSpec)
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
    # The immutable production instance and exact input used to generate its
    # decisions.  Research copies this instance before applying a declared
    # candidate, so no live strategy object is ever modified.
    strategy: object | None = None
    signal_prices: pd.DataFrame | None = None


@dataclass(frozen=True)
class ValidationReport:
    """Standardised deterministic research output; intentionally UI-agnostic."""

    scenarios: pd.DataFrame
    rolling_periods: pd.DataFrame
    subperiods: pd.DataFrame
    data_quality: pd.DataFrame
    scorecard: pd.DataFrame
    monte_carlo: pd.DataFrame


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


def _with_decisions(input_data: ValidationInput, decisions: pd.DataFrame) -> ValidationInput:
    """Keep every immutable validation input while substituting research decisions."""
    return ValidationInput(
        input_data.name, decisions, input_data.monthly_prices, input_data.daily_prices,
        input_data.benchmark_asset, input_data.profile, input_data.proxy_monthly_prices,
        input_data.proxy_daily_prices, input_data.strategy, input_data.signal_prices,
    )


def _shifted_monthly_signal_prices(daily_prices: pd.DataFrame, shift_business_days: int) -> pd.DataFrame:
    """Sample one real close per calendar month at a bounded shifted date.

    The output retains the actual sampled trading date.  It therefore forces
    the strategy to recalculate its complete lookback series at those dates,
    rather than treating a later execution as a shifted signal.
    """
    prices = daily_prices.sort_index()
    sampled_dates: list[pd.Timestamp] = []
    for _, dates in prices.index.to_series().groupby(prices.index.to_period("M")):
        month_end = dates.iloc[-1]
        position = prices.index.get_indexer([month_end])[0] + shift_business_days
        if 0 <= position < len(prices.index):
            sampled_dates.append(prices.index[position])
    return prices.loc[pd.DatetimeIndex(sampled_dates)].loc[lambda frame: ~frame.index.duplicated(keep="last")]


def _shifted_month_end_dates(daily_prices: pd.DataFrame, shift_business_days: int) -> pd.DatetimeIndex:
    """Return actual shifted trading dates, one per completed calendar month."""
    prices = daily_prices.sort_index()
    sampled_dates: list[pd.Timestamp] = []
    for _, dates in prices.index.to_series().groupby(prices.index.to_period("M")):
        month_end = dates.iloc[-1]
        position = prices.index.get_indexer([month_end])[0] + shift_business_days
        if 0 <= position < len(prices.index):
            sampled_dates.append(prices.index[position])
    return pd.DatetimeIndex(sampled_dates).drop_duplicates()


def _recompute_decisions(input_data: ValidationInput, parameters: Mapping[str, Any] | None = None, rebalance_shift_business_days: int | None = None) -> pd.DataFrame:
    """Recompute a declared research variant from copied strategy state."""
    if input_data.strategy is None or input_data.signal_prices is None:
        raise ValueError("This validation input has no strategy recomputation adapter.")
    strategy = copy.copy(input_data.strategy)
    for key, value in (parameters or {}).items():
        if not any(item.key == key and value in item.candidate_values for item in input_data.profile.published_parameters):
            raise ValueError(f"{key}={value!r} is not a declared research candidate.")
        setattr(strategy, key, value)
    signal_prices = input_data.signal_prices
    if rebalance_shift_business_days is not None:
        if getattr(strategy, "uses_daily_signals", False):
            if input_data.daily_prices is None or not hasattr(strategy, "decisions_at_dates"):
                raise ValueError("Daily-signal strategies require a strategy-specific rebalance-date adapter.")
            dates = _shifted_month_end_dates(input_data.daily_prices, rebalance_shift_business_days)
            return strategy.decisions_at_dates(signal_prices, dates)
        if input_data.daily_prices is None:
            raise ValueError("Daily prices are required to recompute shifted month-end signals.")
        signal_prices = _shifted_monthly_signal_prices(input_data.daily_prices, rebalance_shift_business_days)
    return strategy.decisions(signal_prices)


def _perturb_signal_prices(prices: pd.DataFrame, basis_points: float) -> pd.DataFrame:
    """Apply deterministic, bounded input noise for signal-fragility research.

    Alternating signs by date and asset avoid a uniform rescaling that would
    leave relative and moving-average signals unchanged.  Execution prices are
    deliberately untouched: this tests decision sensitivity, not an invented
    market return path.
    """
    multiplier = float(basis_points) / 10_000
    signs = pd.DataFrame(
        [[1 if (row + column) % 2 == 0 else -1 for column in range(len(prices.columns))] for row in range(len(prices))],
        index=prices.index,
        columns=prices.columns,
    )
    return prices * (1 + multiplier * signs)


def _grade_delta(delta: float) -> tuple[str, int]:
    """Grade CAGR loss in percentage points using published, fixed bands."""
    if delta >= -0.02:
        return "Good", 3
    if delta >= -0.05:
        return "Moderate", 2
    return "Weak", 1


def robustness_scorecard(scenarios: pd.DataFrame, rolling_periods: pd.DataFrame, data_quality: pd.DataFrame, profile: ValidationProfile, monte_carlo: pd.DataFrame | None = None) -> pd.DataFrame:
    """Summarise evidence without selecting an optimised strategy setting."""
    baseline_rows = scenarios.loc[(scenarios.get("test") == "baseline") & (scenarios.get("status") == "complete")] if not scenarios.empty else pd.DataFrame()
    if baseline_rows.empty:
        return pd.DataFrame([{"Category": "Overall robustness", "Grade": "Not assessed", "Evidence": "No executable published baseline.", "Score": 0}])
    baseline_cagr = float(baseline_rows.iloc[0]["CAGR"])
    rows: list[dict[str, object]] = []

    def scenario_category(label: str, tests: tuple[str, ...]) -> None:
        relevant = scenarios.loc[scenarios["test"].isin(tests)]
        complete = relevant.loc[relevant["status"] == "complete"]
        if complete.empty:
            rows.append({"Category": label, "Grade": "Not assessed", "Evidence": "No executable declared scenario.", "Score": 0})
            return
        worst = float(complete["CAGR"].min())
        grade, score = _grade_delta(worst - baseline_cagr)
        rows.append({"Category": label, "Grade": grade, "Evidence": f"Worst completed CAGR {worst:.2%} versus published {baseline_cagr:.2%}.", "Score": score})

    scenario_category("Parameter stability", ("parameter_sweep",))
    scenario_category("Execution robustness", ("execution_delay", "rebalance_shift", "signal_perturbation"))
    scenario_category("Costs and tax resilience", ("transaction_cost", "israeli_tax"))
    scenario_category("Proxy robustness", ("proxy_substitution",))

    if monte_carlo is None or monte_carlo.empty or not (monte_carlo["status"] == "complete").any():
        rows.append({"Category": "Bootstrap downside resilience", "Grade": "Not assessed", "Evidence": "No completed block-bootstrap simulation.", "Score": 0})
    else:
        completed_bootstrap = monte_carlo.loc[monte_carlo["status"] == "complete"]
        worst_p10 = float(completed_bootstrap["CAGR p10"].min())
        grade, score = _grade_delta(worst_p10 - baseline_cagr)
        rows.append({"Category": "Bootstrap downside resilience", "Grade": grade, "Evidence": f"Worst horizon 10th-percentile simulated CAGR {worst_p10:.2%} versus published {baseline_cagr:.2%}.", "Score": score})

    complete_rolling = rolling_periods.loc[rolling_periods.get("status") == "complete"] if not rolling_periods.empty else pd.DataFrame()
    if complete_rolling.empty:
        rows.append({"Category": "Rolling-period resilience", "Grade": "Not assessed", "Evidence": "No completed rolling windows.", "Score": 0})
    else:
        worst = float(complete_rolling["CAGR"].min())
        grade, score = _grade_delta(worst - baseline_cagr)
        rows.append({"Category": "Rolling-period resilience", "Grade": grade, "Evidence": f"Worst rolling CAGR {worst:.2%} versus published {baseline_cagr:.2%}.", "Score": score})

    assets = data_quality.loc[data_quality.get("kind") == "asset"] if not data_quality.empty else pd.DataFrame()
    checks = data_quality.loc[data_quality.get("kind") == "check"] if not data_quality.empty else pd.DataFrame()
    raw_missing = int(assets["missing_observations"].sum()) if not assets.empty else 0
    non_positive = int(assets["non_positive_observations"].sum()) if not assets.empty else 0
    look_ahead = checks.loc[checks["check"] == "look_ahead", "status"] if not checks.empty else pd.Series(dtype="object")
    required_execution_data = checks.loc[checks["check"] == "required_execution_data", "status"] if not checks.empty else pd.Series(dtype="object")
    look_ahead_pass = "pass" in set(look_ahead)
    required_data_pass = "pass" in set(required_execution_data)
    if required_data_pass and look_ahead_pass and non_positive == 0:
        data_grade, data_score = ("Good", 3)
    elif required_data_pass and look_ahead_pass:
        data_grade, data_score = ("Moderate", 2)
    else:
        data_grade, data_score = ("Weak", 1)
    rows.append({"Category": "Data confidence", "Grade": data_grade, "Evidence": f"Profile confidence: {profile.data_confidence}; raw calendar/inception gaps: {raw_missing} (reported, not scored); non-positive observations: {non_positive}; execution-path data: {'pass' if required_data_pass else 'fail/not verified'}; look-ahead check: {'pass' if look_ahead_pass else 'not verified'}.", "Score": data_score})

    assessed = [int(row["Score"]) for row in rows if int(row["Score"]) > 0]
    average = sum(assessed) / len(assessed) if assessed else 0.0
    overall = "Not assessed" if len(assessed) < 4 else ("A" if average >= 2.75 else "B+" if average >= 2.4 else "B" if average >= 2 else "C" if average >= 1.5 else "D")
    rows.append({"Category": "Overall robustness", "Grade": overall, "Evidence": f"{len(assessed)} of 7 evidence categories assessed; fixed evidence bands use worst completed CAGR relative to published CAGR.", "Score": round(average, 2)})
    return pd.DataFrame(rows)


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
        input_data.strategy,
        input_data.signal_prices,
    )


def data_quality_report(input_data: ValidationInput, baseline: BacktestResult | None = None) -> pd.DataFrame:
    """Summarise raw coverage separately from executable-data integrity.

    Raw daily series legitimately differ by exchange holiday, publication
    schedule, and inception date.  Those gaps remain visible, but only data
    needed on an actual execution path can fail the integrity check used by
    the scorecard.
    """
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
        rows.append({"kind": "check", "check": "required_execution_data", "status": "unavailable", "detail": "No executable baseline result was available."})
    elif input_data.daily_prices is None:
        rows.append({"kind": "check", "check": "look_ahead", "status": "not_verifiable", "detail": "Daily execution prices were not supplied."})
        rows.append({"kind": "check", "check": "required_execution_data", "status": "not_verifiable", "detail": "Daily execution prices were not supplied."})
    else:
        audit = baseline.audit
        passed = bool((pd.to_datetime(audit["execution_date"]) > pd.to_datetime(audit.index)).all())
        rows.append({
            "kind": "check",
            "check": "look_ahead",
            "status": "pass" if passed else "fail",
            "detail": "Every execution date is strictly after its signal date." if passed else "At least one execution date is not after its signal date.",
        })
        missing_required: list[str] = []
        for signal_date, decision in audit.iterrows():
            weights = decision.get("target_weights")
            holdings = tuple(weights) if isinstance(weights, dict) else (str(decision["selected_asset"]),)
            required_assets = tuple(dict.fromkeys((*holdings, input_data.benchmark_asset)))
            for label, date in (("execution", pd.Timestamp(decision["execution_date"])), ("holding end", pd.Timestamp(decision["holding_end"]))):
                unavailable = [asset for asset in required_assets if asset not in prices.columns or date not in prices.index or pd.isna(prices.loc[date, asset])]
                if unavailable:
                    missing_required.append(f"{signal_date.date()} {label}: {', '.join(unavailable)}")
        rows.append({
            "kind": "check",
            "check": "required_execution_data",
            "status": "pass" if not missing_required else "fail",
            "detail": "Every held asset and benchmark has a price on its actual execution and holding-end dates." if not missing_required else f"Missing required prices on {len(missing_required)} execution-path date(s): {'; '.join(missing_required[:3])}",
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


def block_bootstrap_report(monthly_returns: pd.Series, spec: BootstrapSpec) -> pd.DataFrame:
    """Resample contiguous return blocks into reproducible future paths.

    Circular blocks preserve local serial dependence and volatility clustering
    present in the realised monthly history.  They are scenario analysis, not
    forecasts or confidence intervals.
    """
    returns = pd.to_numeric(monthly_returns, errors="coerce").dropna().to_numpy(dtype=float)
    if len(returns) < spec.block_months:
        return pd.DataFrame([
            {"status": "unavailable", "detail": f"Need at least {spec.block_months} realised monthly returns for a {spec.block_months}-month block."}
        ])
    rows: list[dict[str, object]] = []
    random = np.random.default_rng(spec.seed)
    for years in spec.horizons_years:
        months = years * 12
        blocks_needed = (months + spec.block_months - 1) // spec.block_months
        starts = random.integers(0, len(returns), size=(spec.simulations, blocks_needed))
        offsets = np.arange(spec.block_months)
        paths = returns[(starts[:, :, None] + offsets) % len(returns)].reshape(spec.simulations, -1)[:, :months]
        values = (1 + paths).cumprod(axis=1)
        cagr = values[:, -1] ** (12 / months) - 1
        drawdowns = values / np.maximum.accumulate(values, axis=1) - 1
        max_drawdown = drawdowns.min(axis=1)
        rows.append({
            "status": "complete",
            "horizon": f"{years}y",
            "simulations": spec.simulations,
            "block_months": spec.block_months,
            "seed": spec.seed,
            "CAGR p10": float(np.quantile(cagr, 0.10)),
            "CAGR median": float(np.quantile(cagr, 0.50)),
            "CAGR p90": float(np.quantile(cagr, 0.90)),
            "Final multiple p10": float(np.quantile(values[:, -1], 0.10)),
            "Final multiple median": float(np.quantile(values[:, -1], 0.50)),
            "Maximum drawdown p10": float(np.quantile(max_drawdown, 0.10)),
            "Maximum drawdown median": float(np.quantile(max_drawdown, 0.50)),
            "Worst simulated maximum drawdown": float(max_drawdown.min()),
            "detail": "Circular block bootstrap of realised monthly strategy returns; fixed seed for reproducibility.",
        })
    return pd.DataFrame(rows)


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
        quality = data_quality_report(input_data)
        scenarios = pd.DataFrame([unavailable])
        empty_bootstrap = pd.DataFrame()
        return ValidationReport(scenarios, pd.DataFrame(), pd.DataFrame(), quality, robustness_scorecard(scenarios, pd.DataFrame(), quality, input_data.profile, empty_bootstrap), empty_bootstrap)
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

    if "parameter_sweep" in profile.applicable_tests:
        candidates = [
            (parameter.key, value)
            for parameter in profile.published_parameters
            for value in parameter.candidate_values
        ]
        if not candidates:
            rows.append({"test": "parameter_sweep", "scenario": "declared candidates", "status": "unavailable", "detail": "No candidate values are declared by this profile."})
        for key, value in candidates:
            try:
                decisions = _recompute_decisions(input_data, {key: value})
                result = _run(_with_decisions(input_data, decisions), initial_investment)
                detail = "Published baseline" if value == next(item.published_value for item in profile.published_parameters if item.key == key) else "Research-only candidate"
                rows.append(_scenario_row("parameter_sweep", f"{key}={value}", result, initial_investment, detail=detail))
            except ValueError as exc:
                rows.append(_scenario_row("parameter_sweep", f"{key}={value}", None, initial_investment, detail=str(exc)))

    if "rebalance_shift" in profile.applicable_tests:
        for shift in profile.execution.rebalance_shifts_business_days:
            try:
                # The production baseline uses canonical calendar month-end
                # labels.  Preserve it exactly at zero; shifted variants use
                # their real sampled trading dates and recompute from there.
                decisions = input_data.decisions if shift == 0 else _recompute_decisions(input_data, rebalance_shift_business_days=shift)
                result = _run(_with_decisions(input_data, decisions), initial_investment)
                detail = "Published month-end sampling" if shift == 0 else "Research-only shifted signal sampling"
                rows.append(_scenario_row("rebalance_shift", f"{shift:+d} business day(s)", result, initial_investment, detail=detail))
            except ValueError as exc:
                rows.append(_scenario_row("rebalance_shift", f"{shift:+d} business day(s)", None, initial_investment, detail=str(exc)))

    if "signal_perturbation" in profile.applicable_tests:
        for basis_points in profile.signal_perturbation_bps:
            try:
                if input_data.strategy is None or input_data.signal_prices is None:
                    raise ValueError("This validation input has no strategy recomputation adapter.")
                perturbed = _perturb_signal_prices(input_data.signal_prices, basis_points)
                strategy = copy.copy(input_data.strategy)
                decisions = strategy.decisions(perturbed)
                result = _run(_with_decisions(input_data, decisions), initial_investment)
                rows.append(_scenario_row("signal_perturbation", f"±{basis_points:g} bps deterministic input noise", result, initial_investment, detail="Research-only alternating price perturbation; execution prices remain unmodified."))
            except ValueError as exc:
                rows.append(_scenario_row("signal_perturbation", f"±{basis_points:g} bps deterministic input noise", None, initial_investment, detail=str(exc)))

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
    scenarios = pd.DataFrame(rows)
    rolling_frame = pd.DataFrame(rolling)
    subperiod_frame = pd.DataFrame(subperiod_rows)
    quality = data_quality_report(input_data, baseline)
    monte_carlo = block_bootstrap_report(baseline.monthly["pre_tax_monthly_return"], profile.bootstrap) if "block_bootstrap" in profile.applicable_tests else pd.DataFrame()
    return ValidationReport(scenarios, rolling_frame, subperiod_frame, quality, robustness_scorecard(scenarios, rolling_frame, quality, profile, monte_carlo), monte_carlo)
