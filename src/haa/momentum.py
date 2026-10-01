"""Momentum calculations used by HAA strategies."""
from __future__ import annotations

import pandas as pd


def momentum_13612u(monthly_prices: pd.Series) -> pd.Series:
    """Return HAA's equal-weighted 13612U momentum without future prices.

    For a month-end t, this is:
    ((P[t]/P[t-1]-1) + (P[t]/P[t-3]-1)
     + (P[t]/P[t-6]-1) + (P[t]/P[t-12]-1)) / 4.

    A value at t therefore requires t and the prior 12 month-end observations;
    the first 12 rows are intentionally NaN.
    """
    prices = pd.to_numeric(monthly_prices, errors="coerce")
    r1 = prices.div(prices.shift(1)).sub(1)
    r3 = prices.div(prices.shift(3)).sub(1)
    r6 = prices.div(prices.shift(6)).sub(1)
    r12 = prices.div(prices.shift(12)).sub(1)
    return (r1 + r3 + r6 + r12) / 4


def momentum_13612w(monthly_prices: pd.Series) -> pd.Series:
    """Return VAA's fast, weighted 13612W momentum.

    The published weighted average annualizes each return horizon:
    ``(12*R1 + 4*R3 + 2*R6 + R12) / 4``.  Like 13612U it only uses
    completed historic month-ends and requires twelve earlier observations.
    """
    prices = pd.to_numeric(monthly_prices, errors="coerce")
    r1 = prices.div(prices.shift(1)).sub(1)
    r3 = prices.div(prices.shift(3)).sub(1)
    r6 = prices.div(prices.shift(6)).sub(1)
    r12 = prices.div(prices.shift(12)).sub(1)
    return (12 * r1 + 4 * r3 + 2 * r6 + r12) / 4


def momentum_sma12(monthly_prices: pd.Series) -> pd.Series:
    """Return BAA's published month-end relative-momentum score.

    Keller calls this SMA(12), but defines it as the current price divided by
    the mean of the current and prior twelve month-ends (thirteen prices).
    """
    prices = pd.to_numeric(monthly_prices, errors="coerce")
    return prices.div(prices.rolling(13, min_periods=13).mean()).sub(1)
