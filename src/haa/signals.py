"""Safely surface the latest completed-month strategy decision."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class SignalStatus:
    """The latest decision that is safe to present as an actionable signal."""

    decision: pd.Series | None
    reason: str | None
    completed_through: pd.Timestamp


@dataclass(frozen=True)
class PreviewStatus:
    """A non-actionable estimate of the next month-end decision."""

    decision: pd.Series | None
    reason: str | None
    price_as_of: pd.Timestamp | None


def last_completed_month_end(as_of: pd.Timestamp | None = None) -> pd.Timestamp:
    """Return the calendar month-end before ``as_of``'s current month."""
    timestamp = pd.Timestamp.now(tz="UTC").tz_localize(None) if as_of is None else pd.Timestamp(as_of).tz_localize(None)
    return (timestamp.to_period("M") - 1).to_timestamp("M")


def latest_actionable_signal(
    decisions: pd.DataFrame,
    monthly_prices: pd.DataFrame,
    required_assets: Iterable[str],
    as_of: pd.Timestamp | None = None,
) -> SignalStatus:
    """Return only a fully priced decision from the latest completed month.

    A current partial calendar month is never actionable, even when Yahoo has
    already returned one or more daily observations for it. A stale or missing
    completed month also blocks a signal instead of falling back to an older
    allocation silently.
    """
    completed_month_end = last_completed_month_end(as_of)
    if decisions.attrs.get("execution_frequency") == "daily":
        from .strategies.rvol_shifter import completed_daily_cutoff
        cutoff = completed_daily_cutoff(as_of)
        assets = tuple(required_assets)
        if decisions.empty or any(asset not in monthly_prices.columns for asset in assets):
            return SignalStatus(None, "Required daily data or warm-up history is unavailable.", cutoff)
        observed = monthly_prices.loc[monthly_prices.index <= cutoff, list(assets)].dropna(how="all")
        if observed.empty:
            return SignalStatus(None, "No completed daily price observation is available.", cutoff)
        latest = observed.index.max()
        if (cutoff - latest).days > 7:
            return SignalStatus(None, "Daily data is stale by more than seven calendar days.", latest)
        if observed.loc[latest, list(assets)].isna().any() or latest not in decisions.index:
            return SignalStatus(None, "Latest session has incomplete data or no valid daily decision.", latest)
        return SignalStatus(decisions.loc[latest].copy(), None, latest)
    completed_month = completed_month_end.to_period("M")
    assets = tuple(required_assets)
    if decisions.empty:
        return SignalStatus(None, "No strategy decisions exist yet; at least 12 prior monthly observations are required.", completed_month_end)
    if any(asset not in monthly_prices.columns for asset in assets):
        return SignalStatus(None, "Required asset data is unavailable.", completed_month_end)
    completed_dates = monthly_prices.index[monthly_prices.index.to_period("M") == completed_month]
    if len(completed_dates) != 1:
        return SignalStatus(None, f"No complete monthly price row is available for {completed_month_end.date()}.", completed_month_end)
    completed_through = completed_dates[0]
    missing = monthly_prices.loc[completed_through, list(assets)].isna()
    if missing.any():
        return SignalStatus(None, f"No actionable signal: missing completed-month price data for {', '.join(missing[missing].index)}.", completed_through)
    if completed_through not in decisions.index:
        return SignalStatus(None, f"No actionable signal: insufficient valid history to calculate {completed_through.date()}'s decision.", completed_through)
    return SignalStatus(decisions.loc[completed_through].copy(), None, completed_through)


def month_to_date_snapshot(
    completed_monthly_prices: pd.DataFrame,
    daily_prices: pd.DataFrame,
    required_assets: Iterable[str],
    as_of: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame | None, pd.Timestamp | None, str | None]:
    """Append the latest common in-progress-month close to monthly prices.

    The returned row retains its real trading date.  It is deliberately not
    assigned a synthetic calendar month-end, and callers must present any
    resulting decision as a preview rather than an executable signal.
    """
    timestamp = pd.Timestamp.now(tz="UTC").tz_localize(None) if as_of is None else pd.Timestamp(as_of).tz_localize(None)
    assets = tuple(required_assets)
    if any(asset not in daily_prices.columns for asset in assets):
        return None, None, "Required asset data is unavailable for the preview."
    prices = daily_prices.sort_index()
    eligible = prices.index[(prices.index <= timestamp) & (prices.index.to_period("M") == timestamp.to_period("M"))]
    eligible = eligible[prices.loc[eligible, list(assets)].notna().all(axis=1)]
    if len(eligible) == 0:
        return None, None, "No common current-month price row is available for the preview."
    price_as_of = eligible.max()
    snapshot = prices.loc[[price_as_of], completed_monthly_prices.columns]
    return pd.concat([completed_monthly_prices, snapshot]), price_as_of, None


def latest_preview_signal(
    decisions: pd.DataFrame,
    price_as_of: pd.Timestamp | None,
) -> PreviewStatus:
    """Return the latest provisional decision calculated from current prices."""
    if price_as_of is None:
        return PreviewStatus(None, "No current-month price is available for the preview.", None)
    if decisions.empty:
        return PreviewStatus(None, "No preview is available: insufficient valid history.", price_as_of)
    candidate_dates = decisions.index[(decisions.index <= price_as_of) & (decisions.index.to_period("M") == price_as_of.to_period("M"))]
    if len(candidate_dates) == 0:
        return PreviewStatus(None, "No preview is available from the current-month prices.", price_as_of)
    decision_date = candidate_dates.max()
    return PreviewStatus(decisions.loc[decision_date].copy(), None, decision_date)


def first_trading_day_after(daily_prices: pd.DataFrame, signal_date: pd.Timestamp, required_assets: Iterable[str] | None = None) -> pd.Timestamp | None:
    """Find the first post-signal date with usable prices for required assets."""
    eligible = pd.Series(True, index=daily_prices.index)
    if required_assets:
        eligible = daily_prices.loc[:, list(required_assets)].notna().all(axis=1)
    future = daily_prices.index[(daily_prices.index > pd.Timestamp(signal_date)) & eligible]
    return future.min() if len(future) else None
