"""Monthly execution engine: decisions execute after their month-end signal."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .tax import IsraeliTaxState


@dataclass
class BacktestResult:
    monthly: pd.DataFrame
    audit: pd.DataFrame
    tax_events: pd.DataFrame
    daily: pd.DataFrame | None = None


def run_backtest(
    decisions: pd.DataFrame,
    monthly_prices: pd.DataFrame,
    initial_investment: float,
    transaction_cost: float = 0.0,
    tax_enabled: bool = False,
    tax_rate: float = 0.25,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    daily_prices: pd.DataFrame | None = None,
    benchmark_asset: str = "SPY",
    execution_delay_business_days: int = 0,
) -> BacktestResult:
    """Execute one allocation for the month following each signal.

    Each decision is made after the final trading-day close of its month. When
    daily prices are supplied, it enters at the next trading-day close and
    exits at the next month's corresponding execution close. The last decision
    has no future holding period and is excluded.
    """
    if tax_enabled and decisions.attrs.get("tax_supported") is False:
        raise ValueError("Tax modeling requires daily trade/security values; monthly returns cannot reconstruct daily realized gains.")
    if transaction_cost and decisions.attrs.get("trade_cost_supported") is False:
        raise ValueError("Additional trade-fee modeling requires daily trade values; the supplied monthly return stream is used unchanged.")
    if execution_delay_business_days < 0:
        raise ValueError("Execution delay must be zero or a positive number of business days.")
    if decisions.attrs.get("execution_frequency") == "daily":
        from .daily_engine import run_daily_backtest
        if daily_prices is None:
            raise ValueError("Daily execution requires daily prices, not month-end data.")
        return run_daily_backtest(decisions, daily_prices, initial_investment, transaction_cost,
                                  tax_enabled, tax_rate, start, end, benchmark_asset,
                                  execution_delay_business_days)
    if "target_weights" in decisions.columns:
        return _run_weighted_backtest(decisions, monthly_prices, initial_investment, transaction_cost, tax_enabled, tax_rate, start, end, daily_prices, benchmark_asset, execution_delay_business_days)
    if decisions.empty:
        raise ValueError("No valid signals: at least 13 complete month-end observations are required.")
    prices = monthly_prices.sort_index()
    execution_prices = daily_prices.sort_index() if daily_prices is not None else prices
    rows = []
    decision_dates = pd.DatetimeIndex(decisions.index)
    for position, (signal_date, decision) in enumerate(decisions.iterrows()):
        asset = decision["selected_asset"]
        if daily_prices is None:
            loc = prices.index.get_indexer([signal_date])[0]
            if loc < 0 or loc + 1 >= len(prices.index):
                continue
            execution_date, holding_end = signal_date, prices.index[loc + 1]
        else:
            if position + 1 >= len(decision_dates):
                continue
            next_signal_date = decision_dates[position + 1]
            required_assets = (asset, benchmark_asset)
            complete_days = execution_prices.loc[:, required_assets].notna().all(axis=1)
            execution_candidates = execution_prices.index[(execution_prices.index > signal_date) & complete_days]
            exit_candidates = execution_prices.index[(execution_prices.index > next_signal_date) & complete_days]
            if not len(execution_candidates) or not len(exit_candidates):
                continue
            if len(execution_candidates) <= execution_delay_business_days or len(exit_candidates) <= execution_delay_business_days:
                continue
            execution_date = execution_candidates[execution_delay_business_days]
            holding_end = exit_candidates[execution_delay_business_days]
        if start is not None and holding_end < pd.Timestamp(start):
            continue
        if end is not None and holding_end > pd.Timestamp(end):
            continue
        asset_return = execution_prices.loc[holding_end, asset] / execution_prices.loc[execution_date, asset] - 1
        spy_return = execution_prices.loc[holding_end, benchmark_asset] / execution_prices.loc[execution_date, benchmark_asset] - 1
        rows.append({**decision.to_dict(), "signal_date": signal_date, "execution_date": execution_date, "holding_end": holding_end, "holding_period_return": asset_return, "spy_return": spy_return})
    execution = pd.DataFrame(rows)
    if execution.empty:
        raise ValueError("No complete holding periods within the selected date range.")

    pre_value = initial_investment
    after_value = initial_investment
    benchmark_value = initial_investment
    tax_state = IsraeliTaxState(tax_rate=tax_rate)
    previous_asset: str | None = None
    tax_events: list[dict] = []
    output = []
    for _, row in execution.iterrows():
        asset = row.selected_asset
        changing = previous_asset is not None and asset != previous_asset
        entering = previous_asset is None or changing
        pre_tax_cost = transaction_cost if entering else 0.0
        prior_pre_value, prior_after_value, prior_benchmark_value = pre_value, after_value, benchmark_value
        pre_value *= 1 - pre_tax_cost
        if tax_enabled and changing:
            event = tax_state.sell(after_value)
            after_value -= event["tax_paid"]
            tax_events.append({"date": row.execution_date, "sold_asset": previous_asset, **event})
        if tax_enabled and entering:
            after_value *= 1 - transaction_cost
            tax_state.buy(asset, after_value)
        elif not tax_enabled:
            after_value *= 1 - pre_tax_cost
        pre_value *= 1 + row.holding_period_return
        after_value *= 1 + row.holding_period_return
        benchmark_value *= 1 + row.spy_return
        output.append({**row.to_dict(), "pre_tax_value": pre_value, "after_tax_value": after_value, "benchmark_value": benchmark_value, "pre_tax_monthly_return": pre_value / prior_pre_value - 1, "after_tax_monthly_return": after_value / prior_after_value - 1, "benchmark_monthly_return": benchmark_value / prior_benchmark_value - 1, "allocation_change": changing})
        previous_asset = asset
    result = pd.DataFrame(output).set_index("holding_end")
    audit = execution.set_index("signal_date")
    return BacktestResult(result, audit, pd.DataFrame(tax_events))


def _normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    clean = {asset: float(weight) for asset, weight in weights.items() if float(weight) > 0}
    if not clean or abs(sum(clean.values()) - 1.0) > 1e-9:
        raise ValueError("Each weighted strategy decision must contain positive target weights summing to 100%.")
    return clean


def _weight_turnover(previous: dict[str, float], target: dict[str, float]) -> float:
    """One-way turnover: the fraction of portfolio value purchased at a rebalance."""
    return sum(max(0.0, target.get(asset, 0.0) - previous.get(asset, 0.0)) for asset in set(previous) | set(target))


def _run_weighted_backtest(
    decisions: pd.DataFrame,
    monthly_prices: pd.DataFrame,
    initial_investment: float,
    transaction_cost: float,
    tax_enabled: bool,
    tax_rate: float,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
    daily_prices: pd.DataFrame | None,
    benchmark_asset: str,
    execution_delay_business_days: int,
) -> BacktestResult:
    """Execute target-weight portfolios while preserving single-asset engine behavior.

    Rebalances occur at each signal month-end; target weights earn only the
    subsequent month. Turnover is the one-way amount purchased, so a complete
    100% switch has turnover of 100%, while an unchanged basket has zero.
    """
    if decisions.empty:
        raise ValueError("No valid signals: at least 13 complete month-end observations are required.")
    prices = monthly_prices.sort_index()
    execution_prices = daily_prices.sort_index() if daily_prices is not None else prices
    rows: list[dict] = []
    decision_dates = pd.DatetimeIndex(decisions.index)
    for position, (signal_date, decision) in enumerate(decisions.iterrows()):
        weights = _normalise_weights(decision["target_weights"])
        if daily_prices is None:
            loc = prices.index.get_indexer([signal_date])[0]
            if loc < 0 or loc + 1 >= len(prices.index):
                continue
            execution_date, holding_end = signal_date, prices.index[loc + 1]
        else:
            if position + 1 >= len(decision_dates):
                continue
            next_signal_date = decision_dates[position + 1]
            required_assets = tuple(dict.fromkeys((*weights, benchmark_asset)))
            complete_days = execution_prices.loc[:, required_assets].notna().all(axis=1)
            execution_candidates = execution_prices.index[(execution_prices.index > signal_date) & complete_days]
            exit_candidates = execution_prices.index[(execution_prices.index > next_signal_date) & complete_days]
            if not len(execution_candidates) or not len(exit_candidates):
                continue
            if len(execution_candidates) <= execution_delay_business_days or len(exit_candidates) <= execution_delay_business_days:
                continue
            execution_date = execution_candidates[execution_delay_business_days]
            holding_end = exit_candidates[execution_delay_business_days]
        if start is not None and holding_end < pd.Timestamp(start):
            continue
        if end is not None and holding_end > pd.Timestamp(end):
            continue
        asset_returns = {asset: execution_prices.loc[holding_end, asset] / execution_prices.loc[execution_date, asset] - 1 for asset in weights}
        portfolio_return = sum(weights[asset] * asset_returns[asset] for asset in weights)
        spy_return = execution_prices.loc[holding_end, benchmark_asset] / execution_prices.loc[execution_date, benchmark_asset] - 1
        rows.append({**decision.to_dict(), "signal_date": signal_date, "execution_date": execution_date, "holding_end": holding_end, "holding_period_return": portfolio_return, "asset_returns": asset_returns, "spy_return": spy_return})
    execution = pd.DataFrame(rows)
    if execution.empty:
        raise ValueError("No complete holding periods within the selected date range.")

    pre_value = after_value = benchmark_value = initial_investment
    previous_weights: dict[str, float] = {}
    after_positions: dict[str, float] = {}
    tax_state = IsraeliTaxState(tax_rate=tax_rate)
    tax_events: list[dict] = []
    output: list[dict] = []
    for _, row in execution.iterrows():
        weights = _normalise_weights(row.target_weights)
        changing = bool(previous_weights) and weights != previous_weights
        turnover = _weight_turnover(previous_weights, weights)
        prior_pre_value, prior_after_value, prior_benchmark_value = pre_value, after_value, benchmark_value
        pre_value *= 1 - transaction_cost * turnover
        pre_value *= 1 + row.holding_period_return

        if not after_positions:
            after_value *= 1 - transaction_cost * turnover
            after_positions = {asset: after_value * weight for asset, weight in weights.items()}
            if tax_enabled:
                for asset, amount in after_positions.items():
                    tax_state.buy(asset, amount)
        else:
            current_total = sum(after_positions.values())
            desired_before_tax = {asset: current_total * weight for asset, weight in weights.items()}
            taxes = 0.0
            for asset, current in list(after_positions.items()):
                sale = max(0.0, current - desired_before_tax.get(asset, 0.0))
                if sale and tax_enabled:
                    basis = tax_state.cost_bases.get(asset, 0.0)
                    sold_basis = min(basis, basis * sale / current) if current else 0.0
                    event = tax_state.sell(sale, asset=asset, cost_basis_sold=sold_basis)
                    taxes += event["tax_paid"]
                    tax_events.append({"date": row.execution_date, "sold_asset": asset, "proceeds": sale, **event})
            trade_cost = current_total * transaction_cost * turnover
            after_value = max(0.0, current_total - taxes - trade_cost)
            target_positions = {asset: after_value * weight for asset, weight in weights.items()}
            if tax_enabled:
                for asset, target_value in target_positions.items():
                    retained = min(after_positions.get(asset, 0.0), target_value)
                    purchase = max(0.0, target_value - retained)
                    if purchase:
                        tax_state.buy(asset, purchase)
            after_positions = target_positions

        for asset, asset_return in row.asset_returns.items():
            after_positions[asset] *= 1 + asset_return
        after_value = sum(after_positions.values())
        benchmark_value *= 1 + row.spy_return
        output.append({**row.to_dict(), "pre_tax_value": pre_value, "after_tax_value": after_value, "benchmark_value": benchmark_value, "pre_tax_monthly_return": pre_value / prior_pre_value - 1, "after_tax_monthly_return": after_value / prior_after_value - 1, "benchmark_monthly_return": benchmark_value / prior_benchmark_value - 1, "allocation_change": changing, "turnover": turnover})
        previous_weights = weights
    result = pd.DataFrame(output).set_index("holding_end")
    audit = execution.set_index("signal_date")
    return BacktestResult(result, audit, pd.DataFrame(tax_events))
