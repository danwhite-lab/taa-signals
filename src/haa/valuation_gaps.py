"""Bounded, explicit valuation marks. Never a signal input or an execution quote."""
from dataclasses import replace

import numpy as np
import pandas as pd

from .portfolio import execution_security_label
from .tase_data import TASE_ISRAEL_ASSET_IDS

MAX_VALUATION_GAP_SESSIONS = 3


def fund_name(asset):
    identifier = str(TASE_ISRAEL_ASSET_IDS.get(asset, asset))
    label = execution_security_label(asset, "ILS" if asset in TASE_ISRAEL_ASSET_IDS else "USD")
    return f"{label} ({identifier})"


def require_execution_prices(prices, date, assets):
    """A carried valuation mark is never a usable execution price."""
    carried = set(prices.attrs.get("carried_price_dates", ()))
    for asset in sorted(assets):
        value = prices.at[date, asset] if date in prices.index and asset in prices else np.nan
        if (asset, str(pd.Timestamp(date).date())) in carried or not np.isfinite(value) or value <= 0:
            raise ValueError(f"{fund_name(asset)}: execution price unavailable on {date:%Y-%m-%d}.")


def valuation_prices(prices, sessions, assets, invalid_message=None, *, calendar=None):
    """Use only the last prior actual close for bounded, bracketed NaN runs.

    Later observations establish that a historical hole is bounded; their
    values never supply the mark. Source prices and decisions are not mutated.
    Missing first/trailing history, non-positive/infinite values and long gaps
    remain errors. The caller separately checks every actual execution date.
    """
    result = prices.reindex(prices.index.union(sessions)).copy()
    warnings = list(prices.attrs.get("valuation_warnings", ()))
    carried = set(prices.attrs.get("carried_price_dates", ()))
    def fail(asset, day):
        message = invalid_message or "{asset}: missing/invalid security price on {date}; refusing to bridge gaps."
        raise ValueError(message.format(asset=asset, date=str(day.date()), id=TASE_ISRAEL_ASSET_IDS.get(asset, asset)))
    for asset in sorted(assets):
        values = prices[asset].reindex(sessions)
        invalid = values.notna() & (~np.isfinite(values) | (values <= 0))
        if invalid.any():
            fail(asset, values.index[invalid][0])
        missing = values.isna()
        groups = missing.ne(missing.shift()).cumsum()
        for _, group in values[missing].groupby(groups[missing]):
            days = group.index
            real = prices[asset].dropna()
            before = real.loc[real.index < days[0]]
            after = real.loc[real.index > days[-1]]
            if len(days) > MAX_VALUATION_GAP_SESSIONS or before.empty or after.empty or not np.isfinite(before.iloc[-1]) or before.iloc[-1] <= 0 or not np.isfinite(after.iloc[0]) or after.iloc[0] <= 0:
                fail(asset, days[0])
            from .market_sessions import tase_equity_sessions, us_equity_sessions
            sessions_for = calendar or (tase_equity_sessions if asset in TASE_ISRAEL_ASSET_IDS else us_equity_sessions)
            entire_gap = sessions_for(str(before.index[-1].date()), str(after.index[0].date()))[1:-1]
            if len(entire_gap) > MAX_VALUATION_GAP_SESSIONS:
                fail(asset, days[0])
            result.loc[days, asset] = before.iloc[-1]
            carried.update((asset, str(day.date())) for day in days)
            warnings.append(f"{fund_name(asset)}: {', '.join(str(day.date()) for day in days)} — price carried forward for valuation only; last real price dated {before.index[-1]:%Y-%m-%d}.")
    if carried:
        result.attrs["carried_price_dates"] = tuple(sorted(carried))
        result.attrs["valuation_warnings"] = tuple(dict.fromkeys(warnings))
    return result, tuple(dict.fromkeys(warnings))


def with_price_warnings(result, warnings):
    warnings = tuple(dict.fromkeys((*getattr(result, "price_warnings", ()), *warnings)))
    return replace(result, price_warnings=warnings) if warnings else result


def collected_warnings(results):
    return tuple(dict.fromkeys(w for result in results for w in getattr(result, "price_warnings", ())))
