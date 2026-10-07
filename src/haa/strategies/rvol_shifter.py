"""Documented interpretation of Wongkok's V3 three-state Cash-Only model."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..market_sessions import scheduled_execution_dates, validate_us_equity_sessions


def completed_daily_cutoff(as_of: pd.Timestamp | None = None) -> pd.Timestamp:
    """Conservatively wait until 17:00 New York before using today's close."""
    now = pd.Timestamp.now(tz="America/New_York") if as_of is None else pd.Timestamp(as_of)
    now = now.tz_localize("America/New_York") if now.tzinfo is None else now.tz_convert("America/New_York")
    date = now.tz_localize(None).normalize()
    return date if now.hour >= 17 else date - pd.Timedelta(days=1)


class RVolShifterCashOnly:
    name = "A-RVol Shifter V3 Cash-Only"
    data_assets = ("QQQ", "SPY", "HYG", "LQD", "TQQQ", "QLD", "BIL")
    market_data_assets = data_assets
    signal_assets = ("QQQ", "SPY", "HYG", "LQD")
    benchmark_asset = "SPY"
    uses_daily_signals = True
    execution_frequency = "daily"
    is_multi_asset = True
    backtest_available = True
    risk_warning = (
        "EXPERIMENTAL: checks using market prices reproduced the app's historical signals and returns. "
        "This is our interpretation of the published rules, with some calculation assumptions. "
        "Backtests trade at the next trading day's close, not the morning open. "
        "Leveraged ETFs can suffer large losses; past results do not guarantee future returns."
    )

    @staticmethod
    def transition(state: str, rvol: float, vr: float, trend: float, credit: float,
                   donchian: bool, recovery: float, defensive_age: int,
                   donchian_lock: bool) -> tuple[str, bool, str]:
        if state == "TQQQ":
            if rvol > 0.18 or vr > 1.25 or trend < -0.03:
                return "QLD", False, "Downshift: volatility, VR or trend"
        elif state == "QLD":
            if rvol > 0.36 or vr > 1.40 or trend < -0.03 or credit < -0.04:
                return "BIL", False, "Ordinary defensive exit"
            if donchian and rvol >= 0.20:
                return "BIL", True, "Donchian defensive exit"
            if rvol < 0.14 and vr < 0.90 and trend > 0.03:
                return "TQQQ", False, "Upgrade: all clear"
        else:
            if donchian_lock:
                if recovery >= 0.03 or defensive_age >= 20:
                    return "QLD", False, "Donchian recovery or timeout"
            elif rvol < 0.25 and vr < 1.10 and trend > -0.015:
                return "QLD", False, "Ordinary risk-on re-entry"
        return state, donchian_lock, "Hold"

    def indicators(self, daily_prices: pd.DataFrame) -> pd.DataFrame:
        market = daily_prices.loc[:, self.signal_assets].sort_index()
        validate_us_equity_sessions(market)
        # Do not bridge missing observed sessions with filled or dropped rows.
        rvol = np.log(market.QQQ / market.QQQ.shift(1)).rolling(15, min_periods=15).std(ddof=1) * np.sqrt(252)
        credit_ratio = market.HYG / market.LQD
        return pd.DataFrame({
            "rvol": rvol,
            "vr": rvol / rvol.rolling(252, min_periods=252).mean(),
            "trend": market.SPY / market.SPY.rolling(200, min_periods=200).mean() - 1,
            "credit": credit_ratio / credit_ratio.shift(20) - 1,
            "donchian": market.QQQ <= market.QQQ.rolling(40, min_periods=40).min(),
            "recovery": market.QQQ / market.QQQ.rolling(5, min_periods=5).min() - 1,
        }, index=market.index)

    def decisions(self, daily_prices: pd.DataFrame, include_current_month: bool = False,
                  as_of: pd.Timestamp | None = None) -> pd.DataFrame:
        missing = set(self.data_assets) - set(daily_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = daily_prices.loc[:, self.data_assets].sort_index().dropna(how="all")
        if prices.index.has_duplicates:
            raise ValueError("Daily prices contain duplicate dates.")
        prices = prices.loc[prices.index <= completed_daily_cutoff(as_of)]
        if ((prices <= 0) & prices.notna()).any().any():
            raise ValueError("Daily prices must be positive.")
        validate_us_equity_sessions(prices)
        indicators = self.indicators(prices)
        indicator_valid = np.isfinite(indicators.to_numpy(dtype=float)).all(axis=1)
        price_valid = np.isfinite(prices.to_numpy(dtype=float)).all(axis=1)
        valid = pd.Series(indicator_valid & price_valid, index=prices.index)
        state, lock, age = "BIL", False, 0
        rows = []
        started = False
        for date, values in indicators.iterrows():
            if not valid.loc[date]:
                if started:
                    raise ValueError(f"Missing/invalid daily data on {date.date()}; refusing to skip a state-machine session.")
                continue
            started = True
            previous = state
            if state == "BIL" and lock:
                age += 1
            state, lock, reason = self.transition(state, float(values.rvol), float(values.vr),
                float(values.trend), float(values.credit), bool(values.donchian), float(values.recovery), age, lock)
            if state != "BIL" or previous != "BIL":
                age = 0
            rows.append({"signal_date": date, **values.to_dict(), "selected_asset": state,
                "target_weights": {state: 1.0}, "previous_asset": previous,
                "previous_weights": {previous: 1.0}, "trade": state != previous,
                "regime": "defensive" if state == "BIL" else "risk-on",
                "transition_reason": reason, "donchian_lock": lock, "defensive_age": age})
        result = pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
        if not result.empty:
            result["decision_date"] = result.index
            result["scheduled_execution_date"] = scheduled_execution_dates(result.index)
        result.attrs.update(execution_frequency="daily", completed_through=prices.index.max() if len(prices) else None)
        return result
