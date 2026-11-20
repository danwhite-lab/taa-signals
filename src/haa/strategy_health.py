"""Read-only diagnostics from completed, flow-free monthly engine returns."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .metrics import rolling_annualized_returns


def overall_status(statuses):
    """Use the worst available band, withholding a light for missing history."""
    for status in ("insufficient", "red", "yellow"):
        if status in statuses:
            return status
    return "green"


def band_metric(current, reference, minimum, *, warning_fraction=None, tail_percent=None):
    """Compare stress with earlier complete falls or disjoint return windows."""
    sample = np.asarray(reference, dtype=float)
    sample = sample[np.isfinite(sample)]
    available = current is not None and math.isfinite(current) and len(sample) >= minimum
    worst = float(sample.max()) if len(sample) else None
    yellow = None
    status = "insufficient"
    percentile = None
    if available:
        yellow = (float(np.quantile(sample, 1 - tail_percent / 100)) if tail_percent is not None
                  else worst * warning_fraction)
        percentile = 100 * (np.sum(sample < current) + .5 * np.sum(sample == current)) / len(sample)
        status = "red" if current > worst else "yellow" if current >= yellow else "green"
    return {"current": current, "percentile": percentile, "samples": len(sample), "minimum_samples": minimum,
            "status": status, "review_value": yellow, "structural_value": worst,
            "distribution": sorted(sample.tolist()) if available else []}


def drawdown_history(returns, initial_date):
    """Measure one continuous segment without joining unrelated NAV levels."""
    values = pd.concat([pd.Series([1.], index=[initial_date]), (1 + returns).cumprod()])
    losses = 1 - values / values.cummax()
    peak_index = 0
    completed_episodes = []
    underwater_started = False
    deepest_loss = 0.
    trough_date = None
    for index in range(1, len(values)):
        if losses.iloc[index] <= 1e-12:
            if underwater_started:
                completed_episodes.append({
                    "peak": values.index[peak_index].date().isoformat(),
                    "trough": trough_date.date().isoformat(),
                    "recovery": values.index[index].date().isoformat(),
                    "depth": float(deepest_loss),
                    "months": values.index[index].to_period("M").ordinal - values.index[peak_index].to_period("M").ordinal,
                })
            peak_index = index
            underwater_started = False
            deepest_loss = 0.
            trough_date = None
        else:
            underwater_started = True
            if losses.iloc[index] > deepest_loss:
                deepest_loss = losses.iloc[index]
                trough_date = values.index[index]
    peak_date = values.index[peak_index]
    duration = values.index[-1].to_period("M").ordinal - peak_date.to_period("M").ordinal
    return losses, peak_date, duration, completed_episodes


def analyze(monthly, initial_date, policy, reference_returns=None):
    """Measure the latest completed period against strictly earlier history.

    Inputs are existing engine returns, never account NAV or interpolated prices.
    Relative stress reverses the return spread so larger means more stress for
    all indicators. No current episode enters its own historical reference.
    """
    required = ["pre_tax_monthly_return", "benchmark_monthly_return"]
    if monthly.empty or not set(required).issubset(monthly):
        return {"status": "insufficient", "reason": "historyUnavailable", "metrics": {}}
    frame = monthly.loc[:, required].sort_index()
    periods = frame.index.to_period("M")
    if (frame.index.has_duplicates or periods.has_duplicates or not np.isfinite(frame.to_numpy()).all()
            or (frame <= -1).any().any()
            or not periods.equals(pd.period_range(periods[0], periods[-1], freq="M"))):
        return {"status": "insufficient", "reason": "gap", "metrics": {}}
    initial_date = pd.Timestamp(initial_date)
    if initial_date >= frame.index[0]:
        return {"status": "insufficient", "reason": "gap", "metrics": {}}
    losses, peak_date, duration, completed_episodes = drawdown_history(frame.pre_tax_monthly_return, initial_date)
    proxy_episodes = []
    reference_start = initial_date
    if reference_returns is not None and not reference_returns.empty:
        early = reference_returns.loc[reference_returns.index < initial_date]
        if (early.empty or early.index.has_duplicates or not early.index.is_monotonic_increasing
                or not early.index.to_period("M").equals(pd.period_range(early.index[0], early.index[-1], freq="M"))
                or not np.isfinite(early.to_numpy()).all() or early.le(-1).any()):
            raise ValueError("The earlier health reference must contain complete, finite monthly returns.")
        _, _, _, proxy_episodes = drawdown_history(early, early.index[0] - pd.offsets.MonthEnd(1))
        if proxy_episodes:
            reference_start = early.index[0]
    reference_episodes = proxy_episodes + completed_episodes
    # Each earlier recovered fall contributes exactly one deepest loss and one
    # recovery duration. Monthly levels would overweight long episodes and the
    # many observations near a peak. The current open fall is excluded.
    reference_loss = [episode["depth"] for episode in reference_episodes]
    completed_durations = [episode["months"] for episode in reference_episodes]
    relative = rolling_annualized_returns(frame.pre_tax_monthly_return, 3) - rolling_annualized_returns(frame.benchmark_monthly_return, 3)
    # Anchor backward from the current 36-month window. Every earlier window
    # is complete and disjoint from both the current window and every other
    # reference window. Residual months at inception are not a full window.
    window_ends = list(reversed(range(len(frame) - 37, 34, -36)))
    reference_relative = -relative.iloc[window_ends].dropna()
    latest_relative = float(relative.iloc[-1]) if pd.notna(relative.iloc[-1]) else None
    metrics = {
        "drawdown": band_metric(float(losses.iloc[-1]), reference_loss, policy["minimum_falls"], warning_fraction=policy["warning_fraction"]),
        "underwater": band_metric(float(duration), completed_durations, policy["minimum_falls"], warning_fraction=policy["warning_fraction"]),
        "relative": band_metric(-latest_relative if latest_relative is not None else None, reference_relative,
                                1, tail_percent=policy["gap_tail_percent"]),
    }
    statuses = [metric["status"] for metric in metrics.values()]
    # Individual breaches remain visible, but an incomplete comparison cannot
    # support an overall rating.
    status = overall_status(statuses)
    if not proxy_episodes and frame.index[-1] < initial_date + pd.DateOffset(years=policy.get("minimum_years", 20)):
        status = "short_history"
    return {"status": status, "reason": "shortSample" if "insufficient" in statuses else None,
            "as_of": frame.index[-1].date().isoformat(), "start": initial_date.date().isoformat(),
            "peak": peak_date.date().isoformat(), "metrics": metrics, "episodes": completed_episodes,
            "reference_start": reference_start.date().isoformat(),
            "minimum_years": policy.get("minimum_years", 20),
            "proxy_before": initial_date.date().isoformat() if proxy_episodes else None,
            "reference_episodes": reference_episodes,
            "reference_windows": [{"first_period": frame.index[end - 35].date().isoformat(),
                                   "last_period": frame.index[end].date().isoformat(),
                                   "gap": float(relative.iloc[end])} for end in window_ends],
            "rolling": [{"date": date.date().isoformat(), "relative": float(value)} for date, value in relative.dropna().items()]}
