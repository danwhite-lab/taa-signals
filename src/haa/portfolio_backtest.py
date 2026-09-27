"""Generic monthly-rebalanced backtests for portfolios of strategy sleeves."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from .comparison import ModelInput
from .engine import BacktestResult, run_backtest


@dataclass(frozen=True)
class PortfolioBacktestResult:
    """A portfolio return stream plus its sleeve-level return history."""

    monthly: pd.DataFrame
    sleeve_returns: pd.DataFrame
    common_index: pd.DatetimeIndex


def run_portfolio_backtest(
    sleeves: Mapping[str, tuple[float, ModelInput]],
    initial_investment: float,
    transaction_cost: float = 0.0,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> PortfolioBacktestResult:
    """Backtest weighted sleeves, resetting sleeve weights each month-end.

    A sleeve's own engine remains responsible for tactical allocations and
    transaction costs.  The portfolio then earns the weighted sum of each
    sleeve's monthly return and resets to target sleeve weights before the
    following holding period.  This deliberately uses only the intersection
    of executable holding periods; no return series is padded or synthesized.
    """
    if not sleeves:
        raise ValueError("Add at least one portfolio sleeve.")
    weights = {name: float(weight) for name, (weight, _) in sleeves.items()}
    if any(weight <= 0 for weight in weights.values()) or abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("Portfolio sleeve weights must be positive and total exactly 100%.")

    sleeve_results: dict[str, BacktestResult] = {}
    common: pd.DatetimeIndex | None = None
    for name, (_, model) in sleeves.items():
        result = run_backtest(
            model.decisions,
            model.monthly_prices,
            1.0,
            transaction_cost=transaction_cost,
            daily_prices=model.daily_prices,
            benchmark_asset=model.benchmark_asset,
        )
        sleeve_results[name] = result
        common = result.monthly.index if common is None else common.intersection(result.monthly.index)
    common = pd.DatetimeIndex(common).sort_values()
    if start is not None:
        common = common[common >= pd.Timestamp(start)]
    if end is not None:
        common = common[common <= pd.Timestamp(end)]
    if common.empty:
        raise ValueError("The selected sleeves have no common executable holding periods in the requested date range.")

    returns = pd.DataFrame({
        name: result.monthly.loc[common, "pre_tax_monthly_return"]
        for name, result in sleeve_results.items()
    })
    benchmark_returns = pd.DataFrame({
        name: result.monthly.loc[common, "benchmark_monthly_return"]
        for name, result in sleeve_results.items()
    })
    portfolio_returns = returns.mul(pd.Series(weights), axis=1).sum(axis=1)
    # Inputs share the app-wide benchmark (SPY); taking the first column keeps
    # this helper usable for any future uniformly configured benchmark.
    benchmark_return = benchmark_returns.iloc[:, 0]
    monthly = pd.DataFrame({
        "pre_tax_monthly_return": portfolio_returns,
        "benchmark_monthly_return": benchmark_return,
    }, index=common)
    monthly["pre_tax_value"] = initial_investment * (1 + portfolio_returns).cumprod()
    monthly["benchmark_value"] = initial_investment * (1 + benchmark_return).cumprod()
    monthly["allocation_change"] = False
    monthly["turnover"] = 0.0
    return PortfolioBacktestResult(monthly, returns, common)
