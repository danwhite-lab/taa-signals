"""Actual-fund monthly execution guard, opt-in for Israel Compass only."""
import math
import pandas as pd

from .market_sessions import tase_equity_sessions, us_equity_sessions
from .tase_data import TASE_ISRAEL_ASSET_IDS
from .valuation_gaps import valuation_prices, require_execution_prices


def execution_schedule(decisions, prices, benchmark, start=None, end=None, delay=0, *, price_warnings=None):
    """Never carry a pre-inception signal forward into an unrelated month.

    Preserve the monthly engine's joint fund/benchmark close convention. The
    calendar supplies dates. Bounded valuation holes are flagged; execution
    still requires actual quotes. Pre-inception periods precede the first entry.
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
            for date in (entry, exit):
                require_execution_prices(prices, date, (asset,))
            _, warnings = valuation_prices(prices, expected, (asset,),
                "{asset} ({id}): missing actual fund price on {date}; refusing to bridge the gap.")
            if price_warnings is not None:
                price_warnings.extend(w for w in warnings if w not in price_warnings)
        for date in (entry, exit):
            value = prices.at[date, benchmark] if date in prices.index and benchmark in prices else float("nan")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{benchmark}: missing benchmark price on {date:%Y-%m-%d}.")
        schedule[signal] = entry, exit
        started = True
    if not schedule:
        raise ValueError(unavailable or "No complete post-signal holding periods with actual Inflation Compass TASE fund prices.")
    return schedule
