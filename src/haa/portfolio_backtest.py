"""Generic monthly-rebalanced backtests for portfolios of strategy sleeves."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from .comparison import ModelInput
from .engine import BacktestResult, run_backtest
from .tax import IsraeliTaxState


@dataclass(frozen=True)
class PortfolioBacktestResult:
    """A portfolio return stream plus its sleeve-level return history."""

    monthly: pd.DataFrame
    sleeve_returns: pd.DataFrame
    common_index: pd.DatetimeIndex
    tax_events: pd.DataFrame
    daily: pd.DataFrame | None = None
    sleeve_nav: pd.DataFrame | None = None
    audit: pd.DataFrame | None = None


def run_portfolio_backtest(
    sleeves: Mapping[str, tuple[float, ModelInput]],
    initial_investment: float,
    transaction_cost: float = 0.0,
    tax_enabled: bool = False,
    tax_rate: float = 0.25,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    monthly_contribution: float = 0.,
    fixed_fee: float = 0.,
    sleeve_rebalance_mode: str = "none",
    rebalance_sleeve: str | None = None,
    rebalance_cap: float = .15,
    rebalance_target: float = .10,
) -> PortfolioBacktestResult:
    """Backtest weighted sleeves, resetting sleeve weights each month-end.

    A sleeve's own engine remains responsible for tactical allocations and
    transaction costs and realized-gain tax. The portfolio then earns the
    weighted sum of each sleeve's monthly return and resets to target sleeve
    weights before the following holding period. Tax is charged on tactical
    sleeve sales and on profitable sleeve reductions at the monthly reset;
    the latter is an explicit portfolio-level approximation, not tax advice.
    This deliberately uses only the intersection of executable holding
    periods; no return series is padded or synthesized.
    """
    from .backtest_options import validate_options
    validate_options(monthly_contribution, fixed_fee)
    if not sleeves:
        raise ValueError("Add at least one portfolio sleeve.")
    if tax_enabled and any(model.decisions.attrs.get("tax_supported") is False for _, model in sleeves.values()):
        raise ValueError("Tax is unavailable: an imported sleeve lacks trade values.")
    if (transaction_cost or fixed_fee) and any(model.decisions.attrs.get("trade_cost_supported") is False for _, model in sleeves.values()):
        raise ValueError("Trading fees are unavailable: an imported sleeve lacks trade values.")
    if any(model.decisions.attrs.get("single_strategy_only") for _, model in sleeves.values()):
        raise ValueError("Daily supplied proxies are single-strategy only and cannot be portfolio sleeves.")
    if tax_enabled and any(model.decisions.attrs.get("synthetic_tax_proxy") for _, model in sleeves.values()):
        from .synthetic_tax import run_synthetic_tax_portfolio
        return run_synthetic_tax_portfolio(sleeves, initial_investment, tax_rate, start, end, monthly_contribution)
    if any(model.decisions.attrs.get("execution_frequency") == "daily" for _, model in sleeves.values()):
        from .mixed_portfolio import run_mixed_portfolio
        return run_mixed_portfolio(
            sleeves, initial_investment, transaction_cost, tax_enabled, tax_rate,
            start, end, monthly_contribution, fixed_fee, sleeve_rebalance_mode,
            rebalance_sleeve, rebalance_cap, rebalance_target,
        )
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
            transaction_cost=0. if (monthly_contribution or fixed_fee) else transaction_cost,
            tax_enabled=False if (monthly_contribution or fixed_fee) else tax_enabled,
            tax_rate=tax_rate,
            start=start,
            end=end,
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

    if monthly_contribution or fixed_fee:
        # Fund one security-level monthly book, rather than charging an
        # absolute fee to the old normalized one-unit sleeve simulations.
        from .engine import _simulate_weighted_execution
        rows = []
        for date in common:
            targets, asset_returns = {}, {}
            for name, result in sleeve_results.items():
                period = result.monthly.loc[date]
                target = period.get("target_weights", {period.get("selected_asset"): 1.})
                returns = period.get("asset_returns", {period.get("selected_asset"): period.holding_period_return})
                for asset, weight in target.items():
                    role = f"{name}::{asset}"
                    targets[role] = weights[name] * weight
                    asset_returns[role] = returns[asset]
            benchmark_return = next(iter(sleeve_results.values())).monthly.loc[date, "benchmark_monthly_return"]
            rows.append({"signal_date": date, "execution_date": date, "holding_end": date,
                "target_weights": targets, "asset_returns": asset_returns,
                "holding_period_return": sum(targets[a]*asset_returns[a] for a in targets), "spy_return": benchmark_return})
        funded = _simulate_weighted_execution(pd.DataFrame(rows), initial_investment, transaction_cost, tax_enabled, tax_rate, monthly_contribution, fixed_fee)
        sleeve_returns = pd.DataFrame({n:r.monthly.loc[common,"pre_tax_monthly_return"] for n,r in sleeve_results.items()})
        return PortfolioBacktestResult(funded.monthly, sleeve_returns, common, funded.tax_events, audit=funded.audit)

    returns = pd.DataFrame({
        name: result.monthly.loc[common, "pre_tax_monthly_return"]
        for name, result in sleeve_results.items()
    })
    benchmark_returns = pd.DataFrame({
        name: result.monthly.loc[common, "benchmark_monthly_return"]
        for name, result in sleeve_results.items()
    })
    portfolio_returns = returns.mul(pd.Series(weights), axis=1).sum(axis=1)
    after_returns = pd.DataFrame({
        name: result.monthly.loc[common, "after_tax_monthly_return"]
        for name, result in sleeve_results.items()
    })
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
    after_value = initial_investment
    positions: dict[str, float] = {}
    tax_state = IsraeliTaxState(tax_rate=tax_rate)
    tax_events: list[dict[str, object]] = []
    after_values: list[float] = []
    after_period_returns: list[float] = []
    for date, period_returns in after_returns.iterrows():
        prior_value = after_value
        tax_paid = 0.0
        if not positions:
            positions = {name: after_value * weight for name, weight in weights.items()}
            if tax_enabled:
                for name, amount in positions.items():
                    tax_state.buy(name, amount)
        else:
            total_before_reset = sum(positions.values())
            desired_before_tax = {name: total_before_reset * weight for name, weight in weights.items()}
            residual = positions.copy()
            if tax_enabled:
                for name, current in positions.items():
                    sale = max(0.0, current - desired_before_tax[name])
                    if sale:
                        basis = tax_state.cost_bases.get(name, 0.0)
                        sold_basis = min(basis, basis * sale / current) if current else 0.0
                        event = tax_state.sell(sale, asset=name, cost_basis_sold=sold_basis)
                        tax_paid += event["tax_paid"]
                        residual[name] -= sale
                        tax_events.append({"date": date, "tax_level": "portfolio reset", "sold_sleeve": name, "proceeds": sale, **event})
            after_value = max(0.0, total_before_reset - tax_paid)
            target_positions = {name: after_value * weight for name, weight in weights.items()}
            if tax_enabled:
                for name, target in target_positions.items():
                    if target > residual[name]:
                        tax_state.buy(name, target - residual[name])
                    elif residual[name] > target and residual[name] > 0:
                        # Tax payment reduces portfolio capital. It is not an
                        # extra strategy sale, so trim the remaining basis in
                        # proportion to the post-tax position.
                        tax_state.cost_bases[name] = tax_state.cost_bases.get(name, 0.0) * target / residual[name]
            positions = target_positions
        for name, sleeve_return in period_returns.items():
            positions[name] *= 1 + sleeve_return
        after_value = sum(positions.values())
        after_values.append(after_value)
        after_period_returns.append(after_value / prior_value - 1)
        monthly.loc[date, "portfolio_reset_tax"] = tax_paid

    monthly["after_tax_value"] = after_values
    monthly["after_tax_monthly_return"] = after_period_returns
    if tax_enabled:
        for name, result in sleeve_results.items():
            if not result.tax_events.empty:
                tax_events.extend({"date": row.get("date"), "tax_level": "strategy sleeve", "sold_sleeve": name, **row.to_dict()} for _, row in result.tax_events.iterrows())
    return PortfolioBacktestResult(monthly, returns, common, pd.DataFrame(tax_events))
