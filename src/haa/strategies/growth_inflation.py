"""Monthly Growth-Inflation Sector Timing strategy variants."""
from __future__ import annotations

import pandas as pd

from ..constants import GROWTH_INFLATION_ASSETS, GROWTH_INFLATION_ISRAEL_DATA_ASSETS
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile


def _validation_profile(profile_id: str, notes: str, data_confidence: str = "moderate") -> ValidationProfile:
    return ValidationProfile(
        profile_id=profile_id,
        published_parameters=(
            ParameterSpec("growth_sma_window", 200, (), "SPY absolute-trend moving-average window."),
            ParameterSpec("inflation_ratio_sma_window", 200, (), "Inflation-positive/negative sector-ratio moving-average window."),
        ),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the final NYSE signal date", (0, 1, 2), (-2, -1, 0, 1, 2)),
        # Daily-signal rebalance shifts require an explicit strategy adapter;
        # no approximate monthly substitute is declared here.
        applicable_tests=frozenset({"execution_delay", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        data_confidence=data_confidence,
        notes=notes,
    )


class GrowthInflationBase:
    """Classify completed month-ends by SPY trend and sector-ratio trend."""

    name = "Growth-Inflation Sector Timing"
    data_assets = GROWTH_INFLATION_ASSETS
    market_data_assets = GROWTH_INFLATION_ASSETS
    signal_assets = GROWTH_INFLATION_ASSETS
    benchmark_asset = "SPY"
    is_multi_asset = True
    uses_daily_signals = True
    sma_window = 200
    backtest_available = True
    positive_sectors = ("XLE", "XLB", "XLI", "XLF")
    negative_sectors = ("XLU", "XLV", "XLP", "XLY")
    allocations: dict[tuple[bool, bool], tuple[str, dict[str, float]]] = {}

    def decisions(self, daily_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.signal_assets) - set(daily_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        # Local-execution variants may carry extra TASE holdings in
        # ``data_assets``.  Their U.S. regime calculation remains identical.
        prices = daily_prices.loc[:, self.signal_assets].sort_index().dropna(how="any")
        positive_basket = prices.loc[:, self.positive_sectors].mean(axis=1)
        negative_basket = prices.loc[:, self.negative_sectors].mean(axis=1)
        inflation_ratio = positive_basket / negative_basket
        spy_sma = prices["SPY"].rolling(self.sma_window, min_periods=self.sma_window).mean()
        ratio_sma = inflation_ratio.rolling(self.sma_window, min_periods=self.sma_window).mean()
        completed_period = pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M") - 1
        eligible = prices.index[prices.index.to_period("M") <= completed_period]
        month_ends = eligible.to_series().groupby(eligible.to_period("M")).tail(1)
        rows: list[dict] = []
        previous_weights: dict[str, float] = {}
        for date in pd.DatetimeIndex(month_ends):
            if pd.isna(spy_sma.loc[date]) or pd.isna(ratio_sma.loc[date]):
                continue
            growth_up = bool(prices.loc[date, "SPY"] > spy_sma.loc[date])
            inflation_on = bool(inflation_ratio.loc[date] > ratio_sma.loc[date])
            regime, weights = self.allocations[(growth_up, inflation_on)]
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.signal_assets},
                "SPY_200d_sma": float(spy_sma.loc[date]),
                "positive_sector_basket": float(positive_basket.loc[date]),
                "negative_sector_basket": float(negative_basket.loc[date]),
                "inflation_ratio": float(inflation_ratio.loc[date]),
                "inflation_ratio_200d_sma": float(ratio_sma.loc[date]),
                "growth_up": growth_up,
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


class GrowthInflationConcentrated(GrowthInflationBase):
    """One fixed sector per growth/inflation quadrant."""

    name = "Growth-Inflation Concentrated"
    allocations = {
        (True, True): ("reflation", {"XLE": 1.0}),
        (True, False): ("goldilocks", {"XLK": 1.0}),
        (False, True): ("stagflation", {"XLV": 1.0}),
        (False, False): ("deflation", {"XLP": 1.0}),
    }
    validation_profile = _validation_profile("growth-inflation-concentrated", "The published 200-day signals and fixed quadrant allocations are immutable; this profile declares no parameter sweep.")


class GrowthInflationDiversified(GrowthInflationBase):
    """Fixed 50/50 pairs per quadrant; there is no dynamic sector ranking."""

    name = "Growth-Inflation Diversified"
    allocations = {
        (True, True): ("reflation", {"XLE": 0.5, "XLI": 0.5}),
        (True, False): ("goldilocks", {"XLK": 0.5, "XLY": 0.5}),
        (False, True): ("stagflation", {"XLE": 0.5, "XLB": 0.5}),
        (False, False): ("deflation", {"XLV": 0.5, "XLP": 0.5}),
    }
    validation_profile = _validation_profile("growth-inflation-diversified", "The published 200-day signals and fixed 50/50 quadrant pairs are immutable; this profile declares no parameter sweep.")


class GrowthInflationConcentratedIsrael(GrowthInflationConcentrated):
    """Original U.S. regime signals, executed through TASE-listed ETFs in ILS."""

    name = "Growth-Inflation Concentrated Israel"
    data_assets = GROWTH_INFLATION_ISRAEL_DATA_ASSETS
    # Keep local security series in backtests while deriving every regime from
    # the unchanged U.S. signal inputs.
    market_data_assets = GROWTH_INFLATION_ISRAEL_DATA_ASSETS
    allocations = {
        (True, True): ("reflation", {"XLE_IL": 1.0}),
        (True, False): ("goldilocks", {"XLK_IL": 1.0}),
        (False, True): ("stagflation", {"XLV_IL": 1.0}),
        (False, False): ("deflation", {"XLP_IL": 1.0}),
    }
    validation_profile = _validation_profile("growth-inflation-concentrated-israel", "The original U.S. 200-day signals are immutable; research tests the real TASE execution holdings without synthetic history.", "moderate")
