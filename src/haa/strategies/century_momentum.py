"""Century Momentum: SPMO absolute trend with an IEF defensive sleeve."""
from __future__ import annotations

import pandas as pd

from ..constants import CENTURY_MOMENTUM_DATA_ASSETS, CENTURY_MOMENTUM_ISRAEL_DATA_ASSETS
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile


class CenturyMomentum:
    """Hold SPMO above its completed 10-month SMA, otherwise hold IEF."""

    name = "Century Momentum"
    data_assets = CENTURY_MOMENTUM_DATA_ASSETS
    signal_assets = ("SPMO",)
    benchmark_asset = "SPY"
    equity_asset = "SPMO"
    defensive_asset = "IEF"
    sma_months = 10
    backtest_available = True
    validation_profile = ValidationProfile(
        profile_id="century-momentum-standard",
        published_parameters=(
            ParameterSpec("sma_months", 10, (8, 9, 10, 11, 12), "Absolute trend moving-average window for SPMO.", "months"),
        ),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"parameter_sweep", "execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "data_quality"}),
        data_confidence="moderate",
        notes="The live implementation uses SPMO's actual history only. The academic Fama-French extension is not spliced into investable ETF results.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.data_assets]
        equity_sma = prices[self.equity_asset].rolling(self.sma_months, min_periods=self.sma_months).mean()
        rows: list[dict[str, object]] = []
        previous: str | None = None
        for date, values in prices.iterrows():
            sma = equity_sma.loc[date]
            if values.isna().any() or pd.isna(sma):
                continue
            # Equal means the trend filter is not satisfied and selects IEF.
            selected = self.equity_asset if values[self.equity_asset] > sma else self.defensive_asset
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": values[asset] for asset in self.data_assets},
                f"{self.equity_asset}_10m_sma": float(sma),
                "trend_up": selected == self.equity_asset,
                "regime": "risk-on" if selected == "SPMO" else "risk-off",
                "selected_asset": selected,
                "previous_asset": previous,
                "trade": previous is None or selected != previous,
            })
            previous = selected
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class CenturyMomentumIsrael(CenturyMomentum):
    """Century Momentum executed through its TASE-listed ILS funds."""

    name = "Century Momentum Israel"
    data_assets = CENTURY_MOMENTUM_ISRAEL_DATA_ASSETS
    signal_assets = ("SPMO_IL",)
    benchmark_asset = "SPMO_IL"
    equity_asset = "SPMO_IL"
    defensive_asset = "IEF_IL"
