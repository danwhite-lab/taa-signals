"""Health-only defensive reconstructions; never a trading/backtest data source."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .deep_history import (
    DEEP_HISTORY_DIR, DeepHistorySpec, _read_actual_etf_returns,
    _read_long_monthly_returns,
)


def replacement_returns(config):
    """Join explicitly labelled return segments, never unrelated price levels."""
    actual = _read_actual_etf_returns(DeepHistorySpec(
        key='health-only', label='Health defensive reference', signal_file='',
        returns_file=config['actual_file'], actual_etf_ticker=config['actual_ticker'],
        usable_through=config['actual_through'],
    ))
    if actual.index[0] != pd.Timestamp(config['actual_start']):
        raise ValueError('Health cash reference has an unexpected ETF start.')
    proxy = _read_long_monthly_returns(DEEP_HISTORY_DIR / config['proxy_file'])
    if (proxy.index[-1] + pd.offsets.MonthEnd(1) != actual.index[0]
            or not proxy.index.equals(pd.date_range(proxy.index[0], proxy.index[-1], freq='ME'))
            or not np.isfinite(proxy.to_numpy()).all() or proxy.le(-1).any()):
        raise ValueError('Health cash proxy must meet actual ETF returns without gaps or overlaps.')
    return pd.concat([proxy, actual])


def replace_defensive_returns(signals, returns, replacement, *, risk_asset, defensive_asset):
    """Keep the supplied decisions and risky returns; replace every defensive month.

    Signals apply to the FOLLOWING holding month. Missing cash observations,
    duplicate monthly signals and unexpected allocations fail closed; no bond
    return or forward fill is ever a substitute for a missing cash return.
    """
    months = signals.index.to_period('M') + 1
    if months.has_duplicates:
        raise ValueError('Health reference has duplicate monthly signals.')
    weights = pd.Series(signals.target_weights.to_list(), index=months)
    selected = weights.reindex(returns.index.to_period('M'))
    if (selected.isna().any() or
            any(w not in ({risk_asset: 1.}, {defensive_asset: 1.}) for w in selected)):
        raise ValueError('Health reference needs an unambiguous earlier signal for every month.')
    if replacement.index.has_duplicates:
        raise ValueError('Health reference has duplicate cash months.')
    result = returns.copy(deep=True)
    defensive = np.array([w == {defensive_asset: 1.} for w in selected])
    cash = replacement.reindex(result.index[defensive])
    if not np.isfinite(cash.to_numpy()).all() or cash.le(-1).any():
        raise ValueError('Health reference is missing valid cash returns for a defensive month.')
    result.loc[defensive] = cash.to_numpy()
    return result
