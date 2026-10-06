"""Performance metrics computed from the exact monthly periods supplied."""
from __future__ import annotations

import numpy as np
import pandas as pd


def performance_metrics(values: pd.Series, initial_value: float, periods_per_year: int = 12) -> dict[str, float]:
    values = values.dropna()
    if len(values) == 0:
        return {}
    returns = pd.concat([pd.Series([initial_value]), values]).pct_change().dropna()
    total_return = values.iloc[-1] / initial_value - 1
    years = len(values) / periods_per_year
    cagr = (values.iloc[-1] / initial_value) ** (1 / years) - 1 if years and initial_value > 0 else 0.0
    vol = returns.std(ddof=1) * np.sqrt(periods_per_year) if len(returns) > 1 else 0.0
    downside = returns[returns < 0].std(ddof=1) * np.sqrt(periods_per_year) if (returns < 0).sum() > 1 else np.nan
    sharpe = (returns.mean() / returns.std(ddof=1) * np.sqrt(periods_per_year)) if len(returns) > 1 and returns.std(ddof=1) else np.nan
    sortino = (returns.mean() * periods_per_year / downside) if pd.notna(downside) and downside else np.nan
    drawdown = values / values.cummax() - 1
    max_dd = drawdown.min()
    return {"CAGR": cagr, "Total return": total_return, "Maximum drawdown": max_dd, "Annualized volatility": vol, "Sharpe": sharpe, "Sortino": sortino, "Calmar": cagr / abs(max_dd) if max_dd < 0 else np.nan, "Final value": values.iloc[-1], "Best month": returns.max() if not returns.empty else np.nan, "Worst month": returns.min() if not returns.empty else np.nan}


def annual_returns(monthly_returns: pd.Series) -> pd.Series:
    """Compound the exact holding-period returns in each calendar year."""
    return monthly_returns.resample("YE").apply(lambda returns: (1 + returns).prod() - 1).rename("return")


def rolling_annualized_returns(monthly_returns: pd.Series, years: int) -> pd.Series:
    """Return annualized compound returns for every complete rolling monthly window."""
    if years < 1:
        raise ValueError("Rolling-return window must be at least one year.")
    months = years * 12
    compounded = (1 + monthly_returns).rolling(months, min_periods=months).apply(np.prod, raw=True)
    return compounded.pow(1 / years).sub(1).rename(f"{years}-year rolling CAGR")


def worst_rolling_annualized_return(monthly_returns: pd.Series, years: int) -> float:
    """Return the worst completed rolling annualized return, or NaN if unavailable."""
    rolling = rolling_annualized_returns(monthly_returns, years).dropna()
    return float(rolling.min()) if not rolling.empty else np.nan
