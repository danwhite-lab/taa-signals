"""Daily single-asset execution at the next available session close.

The old monthly engine is unchanged. Daily NAV retains every close; monthly
output is reporting aggregation only, never a monthly sampling of signals.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import BacktestResult
from .metrics import performance_metrics
from .tax import IsraeliTaxState
from .market_sessions import validate_us_equity_sessions


def run_daily_backtest(decisions, daily_prices, initial_investment, transaction_cost=0.0,
                       tax_enabled=False, tax_rate=0.25, start=None, end=None,
                       benchmark_asset="SPY", execution_delay_business_days=0):
    if decisions.empty or decisions.index.has_duplicates:
        raise ValueError("Daily signals are empty or duplicated.")
    if not 0 <= transaction_cost < 1 or not 0 <= tax_rate <= 1 or initial_investment <= 0:
        raise ValueError("Invalid daily-engine capital, fee or tax rate.")
    if execution_delay_business_days < 0:
        raise ValueError("Execution delay cannot be negative.")
    decisions = decisions.sort_index()
    assets = {benchmark_asset}
    for weights in decisions.target_weights:
        if len(weights) != 1 or abs(next(iter(weights.values())) - 1.0) > 1e-9:
            raise ValueError("Daily engine currently supports only 100% single-asset allocations.")
        assets.update(weights)
    if not assets.issubset(daily_prices.columns):
        raise ValueError("Required daily execution/benchmark prices are unavailable.")
    prices = daily_prices.loc[:, sorted(assets)].sort_index().dropna(how="all")
    if prices.index.has_duplicates:
        raise ValueError("Daily execution prices contain duplicate dates.")
    completed_through = decisions.attrs.get("completed_through")
    if completed_through is not None:
        prices = prices.loc[:completed_through]
    validate_us_equity_sessions(prices)
    # Signals must refer to observed sessions; never silently align to a
    # later usable date when a required price is missing.
    positions = prices.index.get_indexer(decisions.index)
    if (positions < 0).any():
        raise ValueError("Daily signal date has no matching price observation.")
    schedule = {}
    for position, (signal_date, decision) in zip(positions, decisions.iterrows()):
        execution_position = position + 1 + execution_delay_business_days
        if execution_position < len(prices):
            schedule[prices.index[execution_position]] = (signal_date, decision)
    if not schedule:
        raise ValueError("No post-signal execution session is available.")
    eligible = prices.loc[min(schedule):]
    if start is not None:
        eligible = eligible.loc[pd.Timestamp(start):]
    if end is not None:
        eligible = eligible.loc[:pd.Timestamp(end)]
    if eligible.empty:
        raise ValueError("No complete daily execution sessions within the selected date range.")
    if not np.isfinite(eligible.to_numpy()).all() or (eligible <= 0).any().any():
        raise ValueError("Missing or invalid daily execution prices; refusing to skip sessions.")
    pre = after = benchmark = float(initial_investment)
    holding = None
    prior_date = None
    tax = IsraeliTaxState(tax_rate=tax_rate)
    output, audit, events = [], [], []
    for date, row in eligible.iterrows():
        prior_pre, prior_after, prior_benchmark = pre, after, benchmark
        if prior_date is not None:
            growth = row[holding] / prices.loc[prior_date, holding]
            pre *= growth
            after *= growth
            benchmark *= row[benchmark_asset] / prices.loc[prior_date, benchmark_asset]
        if date not in schedule:
            raise ValueError(f"No daily decision scheduled for {date.date()}; missing signals cannot be forward-filled.")
        signal_date, decision = schedule[date]
        target = next(iter(decision.target_weights))
        changing = holding is not None and holding != target
        entering = holding is None or changing
        fee_pre = fee_after = 0.0
        if entering:
            if holding is not None:
                fee_pre = pre * transaction_cost
                fee_after = after * transaction_cost
                pre -= fee_pre
                after -= fee_after
                if tax_enabled:
                    event = tax.sell(after, asset=holding)
                    after -= event["tax_paid"]
                    events.append({"date": date, "signal_date": signal_date, "sold_asset": holding,
                                   "proceeds": after + event["tax_paid"], **event})
            buy_pre, buy_after = pre * transaction_cost, after * transaction_cost
            fee_pre += buy_pre
            fee_after += buy_after
            pre -= buy_pre
            after -= buy_after
            if tax_enabled:
                # Acquisition fee is included in cost basis under this fee
                # convention; sale fee reduces realized proceeds.
                tax.buy(target, after + buy_after)
        holding = target
        audit_row = {**decision.to_dict(), "signal_date": signal_date, "decision_date": signal_date, "execution_date": date,
                     "holding_end": date, "selected_asset": target, "allocation_change": changing,
                     "turnover": float(entering), "pre_tax_fee": fee_pre, "after_tax_fee": fee_after}
        audit.append(audit_row)
        output.append({**audit_row, "pre_tax_value": pre, "after_tax_value": after,
                       "benchmark_value": benchmark,
                       "pre_tax_monthly_return": pre / prior_pre - 1,
                       "after_tax_monthly_return": after / prior_after - 1,
                       "benchmark_monthly_return": benchmark / prior_benchmark - 1})
        prior_date = date
    daily = pd.DataFrame(output).set_index("holding_end")
    monthly_rows = []
    for _, group in daily.groupby(daily.index.to_period("M")):
        last = group.iloc[-1].to_dict()
        for column in ("pre_tax_monthly_return", "after_tax_monthly_return", "benchmark_monthly_return"):
            last[column] = (1 + group[column]).prod() - 1
        last["allocation_change"] = int(group.allocation_change.sum())
        last["turnover"] = group.turnover.sum()
        last["holding_end"] = group.index[-1]
        monthly_rows.append(last)
    monthly = pd.DataFrame(monthly_rows).set_index("holding_end")
    return BacktestResult(monthly, pd.DataFrame(audit).set_index("signal_date"), pd.DataFrame(events), daily)


def daily_performance_metrics(result: BacktestResult, column: str, initial: float) -> dict:
    """Daily risk metrics, calendar-time CAGR, monthly best/worst reports."""
    daily = result.daily
    metrics = performance_metrics(daily[column], initial, periods_per_year=252)
    years = max((daily.index[-1] - daily.index[0]).days, 1) / 365.25
    metrics["CAGR"] = (daily[column].iloc[-1] / initial) ** (1 / years) - 1
    values = np.r_[initial, daily[column].to_numpy()]
    metrics["Maximum drawdown"] = float((values / np.maximum.accumulate(values) - 1).min())
    dd = metrics["Maximum drawdown"]
    metrics["Calmar"] = metrics["CAGR"] / abs(dd) if dd < 0 else np.nan
    returns_column = {"pre_tax_value": "pre_tax_monthly_return", "after_tax_value": "after_tax_monthly_return", "benchmark_value": "benchmark_monthly_return"}[column]
    metrics["Best month"] = result.monthly[returns_column].max()
    metrics["Worst month"] = result.monthly[returns_column].min()
    return metrics
