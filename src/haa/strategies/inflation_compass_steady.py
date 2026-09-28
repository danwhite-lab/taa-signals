"""Shared post-2003 T5YIE implementation for Inflation Compass variants."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..constants import INFLATION_COMPASS_DATA_ASSETS, INFLATION_COMPASS_MARKET_ASSETS
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile


class InflationCompassBase:
    """Monthly implementation of the post-2003 T5YIE Inflation Compass rules."""

    name = "Inflation Compass"
    data_assets = INFLATION_COMPASS_DATA_ASSETS
    market_data_assets = INFLATION_COMPASS_MARKET_ASSETS
    signal_assets = INFLATION_COMPASS_DATA_ASSETS
    benchmark_asset = "SPY"
    is_multi_asset = True
    uses_daily_signals = True
    risk_warning = "Concentrated sector allocation. T5YIE is a market-implied inflation measure and is read with a one-trading-day lag."
    momentum_window = 80
    sma_window = 200
    backtest_available = True

    positive_weights = {"XLE": 0.5, "XLI": 1 / 6, "XLF": 1 / 6, "XLB": 1 / 6}
    negative_weights = {"XLU": 1 / 3, "XLV": 1 / 3, "XLP": 1 / 3}

    def decisions(self, daily_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(daily_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = daily_prices.loc[:, self.data_assets].sort_index()
        # FRED has observations on some Federal business days when NYSE ETFs
        # do not trade. Build every market indicator on the shared ETF trading
        # calendar, rather than letting those macro-only rows break a 200-day
        # moving average or a daily sector return.
        market = prices.loc[:, list(self.market_data_assets)].dropna(how="any")
        market_returns = market.pct_change(fill_method=None)
        positive_returns = sum(market_returns[asset] * weight for asset, weight in self.positive_weights.items())
        negative_returns = sum(market_returns[asset] * weight for asset, weight in self.negative_weights.items())
        # The published indicator compounds daily rebalanced basket returns;
        # raw ETF price levels are never combined.
        positive_growth = (1 + positive_returns).cumprod()
        negative_growth = (1 + negative_returns).cumprod()
        inflation_indicator = positive_growth / negative_growth
        spy_sma = market["SPY"].rolling(self.sma_window, min_periods=self.sma_window).mean()
        fred = prices["T5YIE"].dropna()

        as_of = pd.Timestamp.now(tz="UTC").tz_localize(None)
        completed_period = as_of.to_period("M") - 1
        market_dates = market.index[market.index.to_period("M") <= completed_period]
        decision_dates = market_dates.to_series().groupby(market_dates.to_period("M")).tail(1)
        rows: list[dict] = []
        previous_weights: dict[str, float] = {}

        for date in pd.DatetimeIndex(decision_dates):
            # Strictly earlier means a live month-end decision never relies on
            # that day's potentially unpublished FRED observation.
            available_fred = fred.loc[fred.index < date]
            indicator_window = inflation_indicator.loc[:date].dropna().tail(self.momentum_window)
            if len(available_fred) < self.momentum_window + 1 or len(indicator_window) < self.momentum_window or pd.isna(spy_sma.loc[date]):
                continue
            t5yie_date = available_fred.index[-1]
            t5yie_value = float(available_fred.iloc[-1])
            t5yie_momentum_date = available_fred.index[-(self.momentum_window + 1)]
            t5yie_momentum_value = float(available_fred.iloc[-(self.momentum_window + 1)])
            slope = float(np.polyfit(np.arange(self.momentum_window), indicator_window.to_numpy(), 1)[0])
            growth_up = bool(market.loc[date, "SPY"] > spy_sma.loc[date])
            inflation_level = t5yie_value > 2.0
            breakeven_momentum = t5yie_value > t5yie_momentum_value
            asset_momentum = slope > 0
            inflation_on = inflation_level and (breakeven_momentum or asset_momentum)

            if growth_up and inflation_on:
                weights, regime = {"XLE": 1.0}, "inflationary-expansion"
            elif growth_up:
                weights, regime = {"XLK": 1.0}, "disinflationary-expansion"
            elif inflation_on:
                weights, regime = {"XLU": 1.0}, "stagflation"
            else:
                weights, regime = {"XLP": 0.5, "IEF": 0.5}, "disinflationary-slowdown"

            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.data_assets},
                "SPY_200d_sma": float(spy_sma.loc[date]),
                "t5yie_lag_date": t5yie_date,
                "t5yie_lagged": t5yie_value,
                "t5yie_momentum_date": t5yie_momentum_date,
                "t5yie_momentum_value": t5yie_momentum_value,
                "positive_basket_growth": float(positive_growth.loc[date]),
                "negative_basket_growth": float(negative_growth.loc[date]),
                "inflation_indicator": float(inflation_indicator.loc[date]),
                "indicator_momentum_slope": slope,
                f"t5yie_{self.momentum_window}d_date": t5yie_momentum_date,
                f"t5yie_{self.momentum_window}d": t5yie_momentum_value,
                f"indicator_{self.momentum_window}d_slope": slope,
                "growth_up": growth_up,
                "inflation_level": inflation_level,
                "breakeven_momentum": breakeven_momentum,
                "asset_momentum": asset_momentum,
                "inflation_on": inflation_on,
                "regime": regime,
                "selected_asset": ", ".join(weights),
                "selected_assets": ", ".join(weights),
                "target_weights": weights,
                "previous_weights": previous_weights.copy(),
                "previous_asset": ", ".join(previous_weights) if previous_weights else None,
                "trade": weights != previous_weights,
            })
            previous_weights = weights
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class InflationCompassSteady(InflationCompassBase):
    """The 80-trading-day Inflation Compass Steady variant."""

    name = "Inflation Compass Steady (80-day)"
    momentum_window = 80


class InflationCompassStandard(InflationCompassBase):
    """The published 60-trading-day Inflation Compass Standard variant."""

    name = "Inflation Compass Standard"
    momentum_window = 60
    validation_profile = ValidationProfile(
        profile_id="inflation-compass-standard",
        published_parameters=(
            ParameterSpec("momentum_window", 60, (40, 50, 60, 70, 80), "T5YIE and inflation-indicator confirmation window.", "trading days"),
            ParameterSpec("growth_sma_window", 200, (), "SPY trend moving-average window.", "trading days"),
        ),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the final NYSE trading-day signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"parameter_sweep", "execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "data_quality"}),
        notes="The 60-day published configuration remains the production baseline; all alternatives are research-only.",
    )


class InflationCompassFast(InflationCompassBase):
    """The 40-trading-day Inflation Compass Fast variant."""

    name = "Inflation Compass Fast (40-day)"
    momentum_window = 40


class InflationCompassSteadyIsrael(InflationCompassSteady):
    """Israel execution labels with the unchanged USD Compass signal inputs."""

    name = "Inflation Compass Steady (80-day) Israel"
    backtest_available = False


class InflationCompassStandardIsrael(InflationCompassStandard):
    """Israel execution labels with the unchanged USD Compass signal inputs."""

    name = "Inflation Compass Standard Israel"
    backtest_available = False


class InflationCompassFastIsrael(InflationCompassFast):
    """Israel execution labels with the unchanged USD Compass signal inputs."""

    name = "Inflation Compass Fast (40-day) Israel"
    backtest_available = False
