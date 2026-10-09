"""Read-only daily synthetic NAV: never fabricate security prices or tax lots."""
from pathlib import Path
import hashlib

import numpy as np
import pandas as pd

from .comparison import ModelInput
from .market_sessions import validate_us_equity_sessions

SOURCE_HASH = "4449127d40b730d384a58860972a37a2debcd712746604ba392901cc31555d5a"


def monthly_blend_input(model):
    """Use exact NAV month-end returns, not invented daily security prices.

    The daily standalone engine remains unchanged. The blend is a monthly
    strategy-NAV allocation; it cannot model internal trades or daily blend risk.
    """
    if not model.decisions.attrs.get("daily_nav_proxy"):
        return model
    decisions = model.decisions.copy(deep=True)
    decisions.attrs = {"tax_supported": False, "trade_cost_supported": False}
    return ModelInput(model.name, decisions, model.monthly_prices, None, model.benchmark_asset)


def load_synthetic_daily(path: Path) -> pd.DataFrame:
    if hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_HASH:
        raise ValueError("Synthetic A-RVol source hash differs from the reviewed v5 dataset.")
    daily = pd.read_csv(path, comment="#", index_col="date", parse_dates=True)
    validate_us_equity_sessions(daily)
    if not daily.index.is_monotonic_increasing:
        raise ValueError("Synthetic daily dates must be sorted.")
    if not np.isfinite(daily[["nav", "sleeve_return"]]).all().all() or (daily.nav <= 0).any():
        raise ValueError("Invalid synthetic daily NAV/returns.")
    return daily


def synthetic_model_input(label, path, benchmark_returns, benchmark_asset, usable_through):
    daily = load_synthetic_daily(path)
    ends = daily.groupby(daily.index.to_period("M")).nav.last()
    returns = ends.pct_change().iloc[1:]
    returns.index = returns.index.to_timestamp("M")
    months = returns.index.intersection(benchmark_returns.index)
    months = months[months <= pd.Timestamp(usable_through)]
    if len(months) < 2 or not months.equals(pd.date_range(months.min(), months.max(), freq="ME")):
        raise ValueError("Synthetic/benchmark complete-month coverage has gaps.")
    anchor = months[0] - pd.offsets.MonthEnd(1)
    prices = pd.DataFrame({"ARVOL_SYNTHETIC_NAV_PROXY": np.r_[100., 100. * (1 + returns.loc[months]).cumprod()],
                           benchmark_asset: np.r_[100., 100. * (1 + benchmark_returns.loc[months]).cumprod()]},
                          index=pd.DatetimeIndex([anchor]).append(months))
    decisions = pd.DataFrame({"selected_asset": "ARVOL_SYNTHETIC_NAV_PROXY"}, index=prices.index[:-1])
    decisions.attrs.update(single_strategy_only=True, tax_supported=False, trade_cost_supported=False,
                           daily_nav_proxy=True)
    return ModelInput(label, decisions, prices, daily, benchmark_asset)


def run_synthetic_nav_backtest(daily, prices, initial, start, end, benchmark_asset, monthly_contribution=0.):
    from .engine import BacktestResult
    if not np.isfinite(initial) or initial <= 0:
        raise ValueError("Initial capital must be positive and finite.")
    if daily is None:
        raise ValueError("Synthetic backtest requires its daily NAV source.")
    months = prices.index[1:]
    if start is not None:
        months = months[months >= pd.Timestamp(start)]
    if end is not None:
        months = months[months <= pd.Timestamp(end)]
    if not len(months):
        raise ValueError("No complete synthetic/benchmark months in the selected range.")
    anchor = months[0] - pd.offsets.MonthEnd(1)
    previous = daily.loc[daily.index <= anchor]
    if previous.empty:
        raise ValueError("Missing synthetic prior-month NAV anchor.")
    source = daily.loc[(daily.index > anchor) & (daily.index <= months[-1])].copy()
    daily_returns = source.nav / pd.concat([previous.nav.tail(1), source.nav]).shift(1).reindex(source.index) - 1
    contributions = pd.Series(0., index=source.index)
    month_starts = source.groupby(source.index.to_period("M")).head(1).index[1:]
    contributions.loc[month_starts] = monthly_contribution
    capital = initial
    funded = []
    for date, ret in daily_returns.items():
        capital = (capital + contributions[date]) * (1 + ret)
        funded.append(capital)
    values = pd.Series(funded, index=source.index)
    if not monthly_contribution:
        # Preserve the original exact NAV-ratio calculation when DCA is off.
        values = initial * source.nav / previous.nav.iloc[-1]
    observed = pd.DataFrame({"pre_tax_value": values, "after_tax_value": values,
                             "pre_tax_daily_return": daily_returns, "contribution": contributions}, index=source.index)
    monthly_values = values.groupby(values.index.to_period("M")).last()
    monthly_values.index = monthly_values.index.to_timestamp("M")
    strategy_returns = daily_returns.groupby(daily_returns.index.to_period("M")).apply(lambda r: (1+r).prod()-1)
    strategy_returns.index = strategy_returns.index.to_timestamp("M")
    benchmark_returns = prices[benchmark_asset].pct_change().loc[months]
    monthly_contributions = contributions.groupby(contributions.index.to_period("M")).sum()
    monthly_contributions.index = monthly_contributions.index.to_timestamp("M")
    benchmark_values = []
    capital = initial
    for date, ret in benchmark_returns.items():
        capital = (capital + monthly_contributions[date]) * (1+ret)
        benchmark_values.append(capital)
    monthly = pd.DataFrame({"pre_tax_value": monthly_values, "after_tax_value": monthly_values,
        "pre_tax_monthly_return": strategy_returns, "after_tax_monthly_return": strategy_returns,
        "benchmark_value": benchmark_values, "contribution": monthly_contributions,
        "benchmark_monthly_return": benchmark_returns}, index=months)
    return BacktestResult(monthly, source, pd.DataFrame(), observed)
