"""Explicit US signal sessions and TASE execution sessions, without price fills."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .market_sessions import (us_equity_sessions, tase_equity_sessions,
                             scheduled_us_tase_execution_dates, validate_tase_sessions)


def market_frame(prices, assets, market):
    missing = set(assets) - set(prices.columns)
    if missing:
        raise ValueError(f"Missing {market} assets: {sorted(missing)}")
    frame = prices.loc[:, list(assets)].sort_index()
    if frame.index.has_duplicates:
        raise ValueError("Duplicate source session dates.")
    observed = frame.dropna(how="all").index
    if not len(observed):
        raise ValueError(f"No observed {market} prices.")
    calendar = us_equity_sessions if market == "US" else tase_equity_sessions
    sessions = calendar(str(observed.min().date()), str(observed.max().date()))
    if len(observed.difference(sessions)):
        raise ValueError(f"Observed quotes on non-trading {market} dates.")
    # Reindex only within this market's observed bounds. Missing own sessions
    # remain NaN and fail validation; other-market holidays are not observations.
    return frame.reindex(sessions)


def tase_execution_schedule(decisions, sessions, delay=0):
    """Latest eligible US state on every TASE session, including US holidays."""
    if decisions.empty or not len(sessions):
        return {}
    eligible = scheduled_us_tase_execution_dates(decisions.index)
    # A missing trailing US observation is not a US holiday. Check every US
    # session whose signal would have become eligible inside this local book.
    expected_us = us_equity_sessions(str(decisions.index.min().date()), str(sessions.max().date()))
    expected_eligible = scheduled_us_tase_execution_dates(expected_us)
    if delay:
        extended = tase_equity_sessions(str(eligible.min().date()),
                                       str((max(eligible.max(), expected_eligible.max()) + pd.Timedelta(days=30 + 3*delay)).date()))
        positions = extended.searchsorted(eligible) + delay
        eligible = extended.take(positions)
        expected_positions = extended.searchsorted(expected_eligible) + delay
        in_bounds = expected_positions < len(extended)
        expected_us = expected_us[in_bounds]
        expected_eligible = extended.take(expected_positions[in_bounds])
    required = expected_us[expected_eligible <= sessions.max()]
    missing = required.difference(decisions.index)
    if len(missing):
        raise ValueError(f"Missing completed US decision sessions: {', '.join(str(d.date()) for d in missing[:8])}. No holiday carry may hide missing US data.")
    schedule = {}
    for date in sessions:
        positions = np.flatnonzero(eligible <= date)
        if len(positions):
            position = positions[-1]
            schedule[date] = (decisions.index[position], decisions.iloc[position].copy())
        elif decisions.attrs.get("cash_start_date") is not None and date >= pd.Timestamp(decisions.attrs["cash_start_date"]):
            schedule[date] = (pd.NaT, pd.Series({
                "model_state": "BIL", "selected_asset": "Ayalon Kaspit (5117700)",
                "target_weights": {"RVOL_CASH_IL": 1.}, "transition_reason": "Reference cash initialization",
                "trade": False, "regime": "defensive", "initial_cash_without_signal": True,
            }))
    return schedule


def complete_tase_prices(prices, assets, cutoff):
    frame = market_frame(prices, assets, "TASE").loc[:cutoff]
    if ((frame <= 0) & frame.notna()).any().any():
        raise ValueError("Non-positive actual TASE price.")
    valid = np.isfinite(frame.to_numpy()).all(axis=1) & (frame.to_numpy() > 0).all(axis=1)
    if not valid.any():
        raise ValueError("No common complete actual TASE execution history.")
    first, last = frame.index[valid][0], frame.index[valid][-1]
    pending = frame.index[frame.index > last]
    complete = frame.loc[first:last]
    validate_tase_sessions(complete)
    if not np.isfinite(complete.to_numpy()).all() or (complete <= 0).any().any():
        raise ValueError("Missing/invalid internal TASE prices; refusing filled execution gaps.")
    return complete, pending
