"""Opt-in monthly execution on actual closes from the specified local market."""
import math

import pandas as pd

from .market_sessions import tase_equity_sessions, us_equity_sessions


def execution_dates(signal_dates, market, delay=0):
    if signal_dates.empty:
        return signal_dates
    month_ends = signal_dates.to_period("M").to_timestamp("M")
    calendar = tase_equity_sessions if market == "TASE" else us_equity_sessions
    sessions = calendar(str(month_ends.min().date()), str((month_ends.max() + pd.Timedelta(days=14 + 3 * delay)).date()))
    if market == "TASE":
        # After TASE moved to Mon–Fri, Tachlit 5141627 kept Mon–Thu dealing
        # (verified in docs/rebalance-holdings.md). Its NAV also values the
        # benchmark during defensive periods.
        sessions = sessions[~((sessions >= pd.Timestamp("2026-01-05")) & (sessions.dayofweek == 4))]
    return sessions.take(sessions.searchsorted(month_ends, side="right") + delay)


def observed_execution_date(prices, signal_date, assets, market):
    scheduled = execution_dates(pd.DatetimeIndex([signal_date]), market)[0]
    if scheduled not in prices.index or not set(assets).issubset(prices.columns):
        return None
    quotes = prices.loc[scheduled, list(assets)]
    return scheduled if (quotes.gt(0) & quotes.lt(float("inf"))).all() else None


def execution_schedule(decisions, prices, benchmark, start=None, end=None, delay=0):
    """Start after real fund inception, refuse internal holes and stop at pending data."""
    market = decisions.attrs["monthly_execution_market"]
    dates = pd.DatetimeIndex(decisions.index)
    if dates.empty:
        raise ValueError("No valid signals: 13 consecutive valid completed month-ends are required.")
    fills = execution_dates(dates, market, delay)
    if prices.empty or benchmark not in prices:
        raise ValueError("Actual daily execution or benchmark prices are unavailable.")

    quotes = prices.where(prices.gt(0) & prices.lt(float("inf")))
    bounds = {asset: (quotes[asset].first_valid_index(), quotes[asset].last_valid_index())
              for asset in quotes.columns}
    schedule = {}
    for pos, (signal, following) in enumerate(zip(dates[:-1], dates[1:])):
        entry, exit_date = fills[pos:pos + 2]
        if (start is not None and exit_date < pd.Timestamp(start)) or (end is not None and exit_date > pd.Timestamp(end)):
            continue
        if following.to_period("M") != signal.to_period("M") + 1:
            if schedule:
                raise ValueError(f"Missing monthly signal after {signal:%Y-%m-%d}. The backtest cannot bridge that gap.")
            continue
        assets = tuple(dict.fromkeys((*decisions.loc[signal, "target_weights"], benchmark)))
        coverage = [bounds.get(asset, (None, None)) for asset in assets]
        if any(first is None or first > entry for first, _ in coverage):
            if schedule:
                raise ValueError(f"No actual fund history for the scheduled execution on {entry:%Y-%m-%d}.")
            continue
        if any(last < exit_date for _, last in coverage):
            break
        for date in (entry, exit_date):
            for asset in assets:
                value = quotes.at[date, asset] if date in quotes.index else float("nan")
                if not math.isfinite(value):
                    raise ValueError(f"{asset}: missing actual daily price on scheduled execution date {date:%Y-%m-%d}.")
        schedule[signal] = entry, exit_date
    if not schedule:
        raise ValueError("No complete post-signal holding periods with actual fund and benchmark prices.")
    return schedule
