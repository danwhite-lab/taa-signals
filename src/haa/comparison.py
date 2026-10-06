"""Run existing HAA models over an identical, completed set of holding periods."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from .engine import BacktestResult, run_backtest


@dataclass(frozen=True)
class ModelInput:
    """An already-instantiated strategy and its model-specific source prices."""

    name: str
    decisions: pd.DataFrame
    monthly_prices: pd.DataFrame
    daily_prices: pd.DataFrame | None = None
    benchmark_asset: str = "SPY"


@dataclass(frozen=True)
class ComparisonResult:
    results: Mapping[str, BacktestResult]
    common_index: pd.DatetimeIndex
    available_periods: pd.DataFrame


def compare_models(
    models: Mapping[str, ModelInput],
    initial_investment: float,
    transaction_cost: float = 0.0,
    tax_enabled: bool = False,
    tax_rate: float = 0.25,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    completed_through: pd.Timestamp | None = None,
) -> ComparisonResult:
    """Backtest models independently, then restart each over their exact overlap.

    Each model gets an independent engine invocation and therefore independent
    costs and tax state. The final rerun is important: it rebases every model
    to the same initial investment at the first shared holding period.
    """
    if len(models) < 2:
        raise ValueError("Select at least two models to compare.")
    if any(model.decisions.attrs.get("execution_frequency") == "daily" for model in models.values()):
        raise ValueError("Daily-execution models currently support single-strategy Backtest only; monthly Compare periods are not equivalent.")
    # Strategies already contain completed-month signals only; execution dates
    # can legitimately fall in the next calendar month.
    requested_end = pd.Timestamp(end) if end is not None else completed_through
    preliminary: dict[str, BacktestResult] = {}
    availability: list[dict[str, object]] = []
    for name, model in models.items():
        result = run_backtest(
            model.decisions,
            model.monthly_prices,
            initial_investment,
            transaction_cost,
            tax_enabled,
            tax_rate,
            start,
            requested_end,
            daily_prices=model.daily_prices,
            benchmark_asset=model.benchmark_asset,
        )
        preliminary[name] = result
        availability.append({
            "model": name,
            "first_holding_period": result.monthly.index.min(),
            "last_holding_period": result.monthly.index.max(),
            "holding_periods": len(result.monthly),
        })
    common = None
    for result in preliminary.values():
        common = result.monthly.index if common is None else common.intersection(result.monthly.index)
    common = pd.DatetimeIndex(common).sort_values()
    if common.empty:
        raise ValueError("The selected models have no common executable holding periods.")

    rebased: dict[str, BacktestResult] = {}
    for name, model in models.items():
        rebased[name] = run_backtest(
            model.decisions,
            model.monthly_prices,
            initial_investment,
            transaction_cost,
            tax_enabled,
            tax_rate,
            common.min(),
            common.max(),
            daily_prices=model.daily_prices,
            benchmark_asset=model.benchmark_asset,
        )
    final_common = None
    for result in rebased.values():
        final_common = result.monthly.index if final_common is None else final_common.intersection(result.monthly.index)
    final_common = pd.DatetimeIndex(final_common).sort_values()
    if not final_common.equals(common):
        # A gap is not expected with monthly source data, but never compare
        # unequal periods if a model has one.
        common = final_common
        rebased = {
            name: BacktestResult(
                result.monthly.loc[common],
                result.audit[result.audit["holding_end"].isin(common)],
                result.tax_events,
            )
            for name, result in rebased.items()
        }
    return ComparisonResult(rebased, common, pd.DataFrame(availability).set_index("model"))
