"""Read-only diagnostics from completed, flow-free monthly engine returns."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .metrics import rolling_annualized_returns


def historical_metric(current, reference, minimum, review, structural):
    """Rank stress using earlier observations, with ties receiving a mid-rank."""
    sample = np.asarray(reference, dtype=float)
    sample = sample[np.isfinite(sample)]
    available = current is not None and math.isfinite(current) and len(sample) >= minimum
    percentile = (100 * (np.sum(sample < current) + .5 * np.sum(sample == current)) / len(sample)
                  if available else None)
    severity = "normal" if available else "insufficient"
    if available and percentile >= review:
        severity = "review"
        # Sparse tails cannot support a stronger label. This is a sample-size
        # guard, not a confidence interval for correlated historical windows.
        if len(sample) * (1 - structural / 100) >= 1 and percentile >= structural:
            severity = "structural"
    return {"current": current, "percentile": percentile, "samples": len(sample), "status": severity,
            "review_threshold": review, "structural_threshold": structural,
            "review_value": float(np.quantile(sample, review / 100)) if available else None,
            "structural_value": float(np.quantile(sample, structural / 100)) if available else None,
            "distribution": sorted(sample.tolist()) if available else []}


def analyze(monthly, initial_date, policy, minimums):
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
    values = pd.concat([pd.Series([1.], index=[initial_date]), (1 + frame.pre_tax_monthly_return).cumprod()])
    losses = 1 - values / values.cummax()
    peak_index = 0
    completed_durations = []
    underwater_started = False
    for index in range(1, len(values)):
        if losses.iloc[index] <= 1e-12:
            if underwater_started:
                completed_durations.append(values.index[index].to_period("M").ordinal - values.index[peak_index].to_period("M").ordinal)
            peak_index = index
            underwater_started = False
        else:
            underwater_started = True
    peak_date = values.index[peak_index]
    duration = values.index[-1].to_period("M").ordinal - peak_date.to_period("M").ordinal
    # For an active episode, retain only history ending at its previous peak.
    reference_loss = losses.iloc[1:peak_index + 1] if underwater_started else losses.iloc[1:-1]
    relative = rolling_annualized_returns(frame.pre_tax_monthly_return, 3) - rolling_annualized_returns(frame.benchmark_monthly_return, 3)
    # Earlier rolling windows cannot share any return with the current window.
    reference_relative = -relative.iloc[:-36].dropna()
    latest_relative = float(relative.iloc[-1]) if pd.notna(relative.iloc[-1]) else None
    metrics = {
        "drawdown": historical_metric(float(losses.iloc[-1]), reference_loss, minimums["drawdown"], **policy),
        "underwater": historical_metric(float(duration), completed_durations, minimums["underwater"], **policy),
        "relative": historical_metric(-latest_relative if latest_relative is not None else None, reference_relative,
                                      minimums["relative"], **policy),
    }
    statuses = [metric["status"] for metric in metrics.values()]
    # Individual breaches remain visible, but an incomplete comparison cannot
    # support an overall rating.
    status = next((candidate for candidate in ("insufficient", "structural", "review") if candidate in statuses), "normal")
    return {"status": status, "reason": "shortSample" if "insufficient" in statuses else None,
            "as_of": frame.index[-1].date().isoformat(), "start": initial_date.date().isoformat(),
            "peak": peak_date.date().isoformat(), "metrics": metrics,
            "rolling": [{"date": date.date().isoformat(), "relative": float(value)} for date, value in relative.dropna().items()]}
