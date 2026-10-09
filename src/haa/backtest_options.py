"""Explicit cash flows and order fees, kept separate from investment returns."""
import math
import pandas as pd


def validate_options(monthly_contribution=0., fixed_fee=0.):
    if any(not math.isfinite(float(x)) or float(x) < 0 for x in (monthly_contribution, fixed_fee)):
        raise ValueError("Monthly contribution and fixed order fee must be finite and non-negative.")


def contribution_for(date, first, previous, amount):
    return float(amount) if previous is not None and pd.Timestamp(date).to_period("M") != pd.Timestamp(previous).to_period("M") else 0.


def order_fee(notional, percent, fixed):
    fee = notional * percent + fixed if notional > 0 else 0.
    if fee >= notional and notional > 0:
        raise ValueError("Trading fee consumes the order value; increase capital/contribution or reduce the fee.")
    return fee


def result_metrics(result, column, initial):
    from .metrics import performance_metrics
    from .daily_engine import daily_performance_metrics
    if result.daily is not None and "benchmark_value" in result.daily:
        return daily_performance_metrics(result, column, initial)
    monthly = result.monthly
    ret = {"pre_tax_value": "pre_tax_monthly_return", "after_tax_value": "after_tax_monthly_return", "benchmark_value": "benchmark_monthly_return"}[column]
    if "contribution" not in monthly or not monthly.contribution.any():
        return performance_metrics(monthly[column], initial)
    metrics = performance_metrics(initial * (1 + monthly[ret]).cumprod(), initial)
    metrics["Final value"] = monthly[column].iloc[-1]
    metrics["Total contributed"] = initial + monthly.contribution.sum()
    metrics["Investment gain"] = metrics["Final value"] - metrics["Total contributed"]
    return metrics


def unit_curves(result, mapping, initial):
    frame = result.daily if result.daily is not None and "pre_tax_monthly_return" in result.daily else result.monthly
    columns = {"pre_tax_value":"pre_tax_monthly_return", "after_tax_value":"after_tax_monthly_return", "benchmark_value":"benchmark_monthly_return"}
    return pd.DataFrame({label: initial*(1+frame[columns[column]]).cumprod() for label,column in mapping.items()})
