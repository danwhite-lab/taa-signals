"""Century Momentum: SPMO absolute trend with configurable defensive sleeves."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from ..constants import (
    CENTURY_MOMENTUM_CASH_DATA_ASSETS,
    CENTURY_MOMENTUM_CASH_ISRAEL_DATA_ASSETS,
    CENTURY_MOMENTUM_DATA_ASSETS,
    CENTURY_MOMENTUM_ISRAEL_DATA_ASSETS,
)
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
        applicable_tests=frozenset({"parameter_sweep", "execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        data_confidence="moderate",
        notes="The live implementation uses SPMO's actual history only. The academic Fama-French extension is not spliced into investable ETF results.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.signal_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.signal_assets]
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
                **{f"{asset}_price": values[asset] for asset in self.signal_assets},
                f"{self.equity_asset}_10m_sma": float(sma),
                "trend_up": selected == self.equity_asset,
                "regime": "risk-on" if selected == self.equity_asset else "risk-off",
                "selected_asset": selected,
                "previous_asset": previous,
                "trade": previous is None or selected != previous,
            })
            previous = selected
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class CenturyMomentumMoveToCash(CenturyMomentum):
    """Century Momentum with BIL as the declared 1–3 month T-bill cash proxy."""

    name = "Century Momentum Move to Cash"
    data_assets = CENTURY_MOMENTUM_CASH_DATA_ASSETS
    defensive_asset = "BIL"
    validation_profile = replace(
        CenturyMomentum.validation_profile,
        profile_id="century-momentum-move-to-cash",
        notes="SPMO's actual history drives the signal. BIL is a 1–3 month U.S. Treasury-bill ETF used as a cash proxy; no pre-inception history is spliced.",
    )


class _CenturyMomentumIsraelExecution(CenturyMomentum):
    """Compute the published SPMO trend signal, then map it to TASE holdings."""

    signal_assets = ("SPMO",)
    execution_proxies: dict[str, str]

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        decisions = super().decisions(monthly_prices)
        if decisions.empty:
            return decisions
        mapped = decisions.copy()
        previous: str | None = None
        mapped["signal_selected_asset"] = mapped["selected_asset"]
        for date, row in mapped.iterrows():
            selected = self.execution_proxies[row["signal_selected_asset"]]
            mapped.at[date, "selected_asset"] = selected
            mapped.at[date, "previous_asset"] = previous
            mapped.at[date, "trade"] = previous is None or selected != previous
            previous = selected
        return mapped


class CenturyMomentumIsrael(_CenturyMomentumIsraelExecution):
    """Published SPMO signal executed through TASE-listed ILS funds."""

    name = "Century Momentum Israel"
    data_assets = CENTURY_MOMENTUM_ISRAEL_DATA_ASSETS
    market_data_assets = CENTURY_MOMENTUM_ISRAEL_DATA_ASSETS
    benchmark_asset = "SPMO_IL"
    execution_proxies = {"SPMO": "SPMO_IL", "IEF": "IEF_IL"}
    validation_profile = replace(
        CenturyMomentum.validation_profile,
        profile_id="century-momentum-standard-israel",
        notes="The signal is calculated from the original U.S. SPMO series. TASE 5140850 and 1159268 are execution holdings and price display only.",
    )


class CenturyMomentumMoveToCashIsrael(_CenturyMomentumIsraelExecution, CenturyMomentumMoveToCash):
    """Published SPMO signal with TASE momentum and near-cash execution funds."""

    name = "Century Momentum Move to Cash Israel"
    data_assets = CENTURY_MOMENTUM_CASH_ISRAEL_DATA_ASSETS
    market_data_assets = CENTURY_MOMENTUM_CASH_ISRAEL_DATA_ASSETS
    benchmark_asset = "SPMO_IL"
    defensive_asset = "BIL"
    execution_proxies = {"SPMO": "SPMO_IL", "BIL": "RVOL_CASH_IL"}
    validation_profile = replace(
        CenturyMomentumMoveToCash.validation_profile,
        profile_id="century-momentum-move-to-cash-israel",
        notes="The signal is calculated from the original U.S. SPMO series. Risk-on holds TASE 5140850; risk-off holds Ayalon Kaspit 5117700, a shekel money-market (kaspit) fund: a near-cash holding, not cash in a bank.",
    )
