"""Actual-fund monthly execution guard, opt-in for Israel Compass only."""
import math
import pandas as pd

from .market_sessions import tase_equity_sessions, us_equity_sessions
from .tase_data import TASE_ISRAEL_ASSET_IDS


def execution_schedule(decisions, prices, benchmark, start=None, end=None, delay=0):
    """Never carry a pre-inception signal forward into an unrelated month.

    Preserve the monthly engine's joint fund/benchmark close convention. The
    calendar supplies dates, never prices. Missing held-fund sessions fail
    closed, while pre-inception periods are skipped before the first entry.
    """
    if decisions.empty or prices.empty:
        raise ValueError("Insufficient US signal history for Inflation Compass Israel.")
    first, last = decisions.index.min(), prices.index.max()
    local = tase_equity_sessions(str(first.date()), str(last.date()))
    joint = local.intersection(us_equity_sessions(str(first.date()), str(last.date())))
    schedule, started, unavailable = {}, False, None
    dates = pd.DatetimeIndex(decisions.index)
    for signal, next_signal in zip(dates[:-1], dates[1:]):
        entries, exits = joint[joint > signal], joint[joint > next_signal]
        if len(entries) <= delay or len(exits) <= delay:
            continue
        entry, exit = entries[delay], exits[delay]
        if entry >= next_signal:
            continue
        if (start is not None and entry < pd.Timestamp(start)) or (end is not None and exit > pd.Timestamp(end)):
            continue
        weights = decisions.loc[signal, "target_weights"]
        before_inception = []
        for asset in weights:
            observations = prices[asset].dropna() if asset in prices else pd.Series(dtype=float)
            if observations.empty or observations.index.min() > entry:
                before_inception.append(asset)
        if before_inception:
            fund = before_inception[0]
            unavailable = f"{fund} ({TASE_ISRAEL_ASSET_IDS[fund]}): no actual fund price for execution on {entry:%Y-%m-%d}; no pre-fund extension."
            if started:
                raise ValueError(unavailable)
            continue
        for asset in weights:
            expected = local[(local >= entry) & (local <= exit)]
            values = prices[asset].reindex(expected)
            missing = values.isna() | ~values.map(lambda v: math.isfinite(v) and v > 0)
            if missing.any():
                date = expected[missing.to_numpy()][0]
                raise ValueError(f"{asset} ({TASE_ISRAEL_ASSET_IDS[asset]}): missing actual fund price on {date:%Y-%m-%d}; refusing to bridge the gap.")
        for date in (entry, exit):
            value = prices.at[date, benchmark] if date in prices.index and benchmark in prices else float("nan")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{benchmark}: missing benchmark price on {date:%Y-%m-%d}.")
        schedule[signal] = entry, exit
        started = True
    if not schedule:
        raise ValueError(unavailable or "No complete post-signal holding periods with actual Inflation Compass TASE fund prices.")
    return schedule
