"""Daily TASE security books with next-session closing/NAV execution."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest_options import contribution_for, order_fee
from .engine import BacktestResult, _normalise_weights
from .market_sessions import validate_tase_sessions
from .tax import IsraeliTaxState


def run_tase_daily_backtest(decisions, daily_prices, initial_investment,
                           transaction_cost=0., tax_enabled=False, tax_rate=.25,
                           start=None, end=None, benchmark_asset="RVOL_SPY_IL",
                           execution_delay_business_days=0, monthly_contribution=0., fixed_fee=0.):
    if decisions.empty or decisions.index.has_duplicates:
        raise ValueError("Local daily decisions are empty or duplicated.")
    if not np.isfinite(initial_investment) or initial_investment <= 0 or not 0 <= transaction_cost < 1 or not 0 <= tax_rate <= 1:
        raise ValueError("Invalid local daily capital, fee or tax rate.")
    if execution_delay_business_days < 0:
        raise ValueError("Execution delay cannot be negative.")
    assets = {benchmark_asset}
    for weights in decisions.target_weights:
        assets.update(_normalise_weights(weights))
    if not assets.issubset(daily_prices.columns):
        raise ValueError("Required TASE execution and benchmark prices are unavailable.")
    prices = daily_prices.loc[:, sorted(assets)].sort_index().dropna(how="all")
    prices = prices.loc[:decisions.attrs.get("completed_through")]
    validate_tase_sessions(prices)
    # Price dates, not US business days, determine the execution session.
    schedule = {}
    for signal_date, decision in decisions.sort_index().iterrows():
        position = prices.index.searchsorted(signal_date, side="right") + execution_delay_business_days
        if position < len(prices):
            schedule[prices.index[position]] = (signal_date, decision)
    if not schedule:
        raise ValueError("No post-signal TASE execution session is available.")
    dates = prices.loc[min(schedule):].index
    if start is not None: dates = dates[dates >= pd.Timestamp(start)]
    if end is not None: dates = dates[dates <= pd.Timestamp(end)]
    if not len(dates):
        raise ValueError("No local daily execution sessions in the requested range.")
    values = prices.loc[dates]
    if not np.isfinite(values.to_numpy()).all() or (values <= 0).any().any():
        raise ValueError("Missing or invalid TASE daily prices; no fills or returns can be fabricated.")
    pre_positions, after_positions = {}, {}
    pre_cash = after_cash = float(initial_investment)
    tax = IsraeliTaxState(tax_rate=tax_rate)
    previous_date = None
    holding_state = None
    benchmark = float(initial_investment)
    events, audit, output = [], [], []
    for date in dates:
        if date not in schedule:
            raise ValueError(f"No local daily decision scheduled for {date.date()}.")
        prior_pre = sum(pre_positions.values()) + pre_cash
        prior_after = sum(after_positions.values()) + after_cash
        prior_benchmark = benchmark
        if previous_date is not None:
            for positions in (pre_positions, after_positions):
                for asset in positions:
                    positions[asset] *= prices.loc[date, asset] / prices.loc[previous_date, asset]
            benchmark *= prices.loc[date, benchmark_asset] / prices.loc[previous_date, benchmark_asset]
        contribution = contribution_for(date, None, previous_date, monthly_contribution)
        pre_cash += contribution; after_cash += contribution; benchmark += contribution
        signal_date, decision = schedule[date]
        state = decision.model_state
        state_change = holding_state is not None and state != holding_state
        annual_reset = previous_date is not None and date.year != previous_date.year and state == "QLD"
        rebalance = holding_state is None or state_change or annual_reset or contribution > 0
        details = []; purchase_notional = 0.
        if rebalance:
            target = _normalise_weights(decision.target_weights)
            for positions, after_book in ((pre_positions, False), (after_positions, True)):
                cash = after_cash if after_book else pre_cash
                total = sum(positions.values()) + cash
                desired = {asset: total * weight for asset, weight in target.items()}
                for asset, current in list(positions.items()):
                    sale = max(0., current - desired.get(asset, 0.))
                    if sale <= max(total, 1.) * 1e-12: continue
                    fee = order_fee(sale, transaction_cost, fixed_fee)
                    proceeds = sale - fee; levy = 0.
                    if after_book and tax_enabled:
                        basis = tax.cost_bases.get(asset, 0.) * sale / current
                        event = tax.sell(proceeds, asset=asset, cost_basis_sold=basis)
                        levy = event['tax_paid']; proceeds -= levy
                        events.append({'date': date, 'signal_date': signal_date, 'sold_asset': asset,
                                       'proceeds': sale - fee, 'annual_reset': annual_reset, **event})
                    positions[asset] -= sale; cash += proceeds
                    details.append({'book': 'after-tax' if after_book else 'pre-tax', 'asset': asset,
                                    'side': 'sell', 'notional': sale, 'fee': fee, 'tax_paid': levy})
                deficits = {asset: max(0., value - positions.get(asset, 0.)) for asset, value in desired.items()}
                needed = sum(deficits.values())
                if needed > max(total, 1.) * 1e-12:
                    active = {asset: deficit for asset, deficit in deficits.items() if deficit > max(total, 1.) * 1e-12}
                    budget = min(cash, needed * (1 + transaction_cost) + len(active) * fixed_fee)
                    if budget <= len(active) * fixed_fee:
                        raise ValueError("Fixed fees consume local purchase capital.")
                    net = (budget - len(active) * fixed_fee) / (1 + transaction_cost)
                    for asset, deficit in active.items():
                        purchase = net * deficit / needed
                        fee = purchase * transaction_cost + fixed_fee
                        positions[asset] = positions.get(asset, 0.) + purchase
                        if after_book and tax_enabled: tax.buy(asset, purchase + fee)
                        if not after_book: purchase_notional += purchase
                        details.append({'book': 'after-tax' if after_book else 'pre-tax', 'asset': asset,
                                        'side': 'buy', 'notional': purchase, 'fee': fee, 'tax_paid': 0.})
                    cash -= budget
                if after_book: after_cash = cash
                else: pre_cash = cash
        holding_state = state
        pre = sum(pre_positions.values()) + pre_cash
        after = sum(after_positions.values()) + after_cash
        row = {**decision.to_dict(), 'decision_date': signal_date, 'signal_date': signal_date,
               'execution_date': date, 'execution_timing': 'next-session-close',
               'annual_reset': annual_reset, 'allocation_change': state_change or annual_reset,
               'security_trades': details, 'target_weights': decision.target_weights,
               'actual_weights': {asset: value / pre for asset, value in pre_positions.items() if value > 1e-12},
               'holding_end': date, 'pre_tax_value': pre, 'after_tax_value': after,
               'benchmark_value': benchmark, 'contribution': contribution,
               'open_pre_tax_value': prior_pre, 'open_after_tax_value': prior_after,
               'purchase_notional': purchase_notional, 'turnover': purchase_notional / prior_pre,
               'pre_tax_monthly_return': (pre - contribution) / prior_pre - 1,
               'after_tax_monthly_return': (after - contribution) / prior_after - 1,
               'benchmark_monthly_return': (benchmark - contribution) / prior_benchmark - 1}
        output.append(row)
        if details: audit.append(row.copy())
        previous_date = date
    daily = pd.DataFrame(output).set_index('holding_end')
    from .mixed_portfolio import aggregate_months
    return BacktestResult(aggregate_months(daily), pd.DataFrame(audit), pd.DataFrame(events), daily)
