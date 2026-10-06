"""Reusable internally managed strategies held continuously by the investor."""
from __future__ import annotations

import pandas as pd

from ..constants import TA125_SMART_MOMENTUM_ASSET
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile


class TA125SmartMomentum:
    """A fund-held implementation; momentum selection happens inside its index."""

    name = "TA-125 Smart Momentum"
    data_assets = (TA125_SMART_MOMENTUM_ASSET, "SPY")
    market_data_assets = data_assets
    signal_assets: tuple[str, ...] = ()
    benchmark_asset = "SPY"
    strategy_mode = "buy_and_hold"
    signal_mode = "internal"
    backtest_available = True
    validation_profile = ValidationProfile(
        profile_id="ta125-smart-momentum-buy-and-hold",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "The fund's underlying index manages momentum internally; the investor does not run a timing rule."),),
        execution=ExecutionSpec("continuous", "Fund remains continuously invested", (0,), (0,)),
        applicable_tests=frozenset({"alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "block_bootstrap", "data_quality"}),
        data_confidence="limited",
        notes="There is no investor-level signal, parameter, or rebalance-date test. Research evaluates the real fund history and continuous-holding implementation only.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        """Remain fully invested whenever fund and benchmark prices are available."""
        prices = monthly_prices.loc[:, self.data_assets]
        rows: list[dict[str, object]] = []
        for date, values in prices.dropna(how="any").iterrows():
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": values[asset] for asset in self.data_assets},
                "regime": "buy-and-hold",
                "selected_asset": TA125_SMART_MOMENTUM_ASSET,
                "previous_asset": TA125_SMART_MOMENTUM_ASSET if rows else None,
                "trade": not rows,
            })
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class BuyAndHoldSPY:
    """Continuous SPY holding using the actual ETF price history available to the app."""

    name = "Buy and Hold SPY"
    data_assets = ("SPY",)
    market_data_assets = data_assets
    signal_assets: tuple[str, ...] = ()
    benchmark_asset = "SPY"
    strategy_mode = "buy_and_hold"
    signal_mode = "internal"
    backtest_available = True
    validation_profile = ValidationProfile(
        profile_id="buy-and-hold-spy",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "SPY remains continuously invested; the app does not run a timing rule."),),
        execution=ExecutionSpec("continuous", "SPY remains continuously invested", (0,), (0,)),
        applicable_tests=frozenset({"alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "block_bootstrap", "data_quality"}),
        data_confidence="established",
        notes="Research evaluates continuous SPY holding using its available ETF history. No pre-ETF proxy or splice is used.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        """Remain fully invested in SPY whenever its month-end price is available."""
        rows: list[dict[str, object]] = []
        for date, values in monthly_prices.loc[:, self.data_assets].dropna(how="any").iterrows():
            rows.append({
                "signal_date": date,
                "SPY_price": values["SPY"],
                "regime": "buy-and-hold",
                "selected_asset": "SPY",
                "previous_asset": "SPY" if rows else None,
                "trade": not rows,
            })
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class BuyAndHoldVT:
    """Continuous Vanguard Total World Stock ETF holding."""

    name = "Buy and Hold VT"
    data_assets = ("VT",)
    market_data_assets = data_assets
    signal_assets: tuple[str, ...] = ()
    benchmark_asset = "VT"
    strategy_mode = "buy_and_hold"
    signal_mode = "internal"
    backtest_available = True
    validation_profile = ValidationProfile(
        profile_id="buy-and-hold-vt",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "VT remains continuously invested; the app does not run a timing rule."),),
        execution=ExecutionSpec("continuous", "VT remains continuously invested", (0,), (0,)),
        applicable_tests=frozenset({"alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "block_bootstrap", "data_quality"}),
        data_confidence="established",
        notes="Research evaluates continuous VT holding using its available ETF history. No pre-ETF splice is used.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for date, values in monthly_prices.loc[:, self.data_assets].dropna(how="any").iterrows():
            rows.append({
                "signal_date": date,
                "VT_price": values["VT"],
                "regime": "buy-and-hold",
                "selected_asset": "VT",
                "previous_asset": "VT" if rows else None,
                "trade": not rows,
            })
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
