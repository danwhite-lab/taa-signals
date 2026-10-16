"""Reusable internally managed strategies held continuously by the investor."""
from __future__ import annotations

from dataclasses import replace

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
    holding_asset = "SPY"
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
                f"{self.holding_asset}_price": values[self.holding_asset],
                "regime": "buy-and-hold",
                "selected_asset": self.holding_asset,
                "previous_asset": self.holding_asset if rows else None,
                "trade": not rows,
            })
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class BuyAndHoldQQQ(BuyAndHoldSPY):
    """Continuous QQQ holding using actual ETF history, without a proxy splice."""

    name = "Buy and Hold QQQ"
    holding_asset = "QQQ"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-qqq",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold QQQ continuously in USD."),),
        execution=ExecutionSpec("continuous", "QQQ remains continuously invested", (0,), (0,)),
        notes="Uses actual QQQ ETF history. No pre-ETF proxy or splice is used.",
    )


class BuyAndHoldGLD(BuyAndHoldSPY):
    """Continuous actual GLD holding in USD, without pre-ETF proxies."""

    name = "Buy and Hold Gold GLD"
    holding_asset = "GLD"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    actual_history_only = True
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-gld",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold GLD continuously in USD."),),
        execution=ExecutionSpec("continuous", "GLD remains continuously invested", (0,), (0,)),
        notes="Uses actual GLD ETF history from Yahoo Finance only. No futures, pre-ETF history or TASE fund prices are spliced in. Fund expenses embedded in prices are not deducted again.",
    )


class BuyAndHoldIEF(BuyAndHoldSPY):
    """Continuous actual IEF holding in USD, without pre-ETF proxies."""

    name = "Buy and Hold IEF"
    holding_asset = "IEF"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    actual_history_only = True
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-ief",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold IEF continuously in USD."),),
        execution=ExecutionSpec("continuous", "IEF remains continuously invested", (0,), (0,)),
        notes="Uses actual IEF ETF adjusted-price history from Yahoo Finance. No pre-ETF bond-index proxy or local-fund history is spliced in. Expenses embedded in prices are not deducted again. Uploaded or selected-source replacements are explicitly flagged.",
    )


class BuyAndHoldQQQIsrael(BuyAndHoldQQQ):
    """Continuous Nasdaq-100 holding through the user's TASE implementation."""

    name = "Buy and Hold QQQ Israel"
    holding_asset = "QQQ_IL"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    validation_profile = replace(
        BuyAndHoldQQQ.validation_profile,
        profile_id="buy-and-hold-qqq-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold TASE security 1186063 continuously in ILS."),),
        execution=ExecutionSpec("continuous", "TASE security 1186063 remains continuously invested", (0,), (0,)),
        data_confidence="moderate",
        notes="Uses actual TASE/Maya history for security 1186063 in ILS, including currency exposure. No QQQ history is spliced into the local security history.",
    )


class BuyAndHoldSPYIsrael(BuyAndHoldSPY):
    """Continuous S&P 500 holding through TASE CSPX security 1159250."""

    name = "Buy and Hold SPY Israel"
    holding_asset = "CSPX_IL"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-spy-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold CSPX (1159250) continuously in ILS."),),
        execution=ExecutionSpec("continuous", "CSPX (1159250) remains continuously invested", (0,), (0,)),
        data_confidence="moderate",
        notes="Uses actual TASE/Maya CSPX history in ILS, including currency exposure. History begins with available local security prices.",
    )


class BuyAndHoldGlobalIsrael(BuyAndHoldSPY):
    """Continuous FTSE All-World holding through TASE security 1209220."""

    name = "Buy and Hold Global Israel"
    holding_asset = "FTSE_ALL_WORLD_IL"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-global-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold FTSE All-World security 1209220 continuously in ILS."),),
        execution=ExecutionSpec("continuous", "FTSE All-World (1209220) remains continuously invested", (0,), (0,)),
        data_confidence="moderate",
        notes="Uses actual TASE/Maya history for security 1209220 in ILS, including currency exposure. History begins with available local security prices.",
    )


class BuyAndHoldGoldIsrael(BuyAndHoldSPY):
    """Plain holding of gold security 1147875, not GLD/GLDM proxy returns."""

    name = "Buy and Hold Gold Israel"
    holding_asset = "GOLD_IL"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    actual_history_only = True
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-gold-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold gold security 1147875 continuously in ILS."),),
        execution=ExecutionSpec("continuous", "Gold security 1147875 remains continuously invested", (0,), (0,)),
        data_confidence="moderate",
        notes="Actual TASE security 1147875 history only. No GLD, GLDM, futures or pre-fund history is spliced in. Expenses embedded in fund prices are not deducted again. Uploaded replacement history is unverified and must be labelled separately.",
    )


class BuyAndHoldHarelBondsIsrael(BuyAndHoldSPY):
    """Plain holding of Harel government-bond fund 5131792."""

    name = "Buy and Hold Harel Government Bonds Israel"
    holding_asset = "HAREL_GOV_BONDS_IL"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    actual_history_only = True
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-harel-government-bonds-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold Harel government-bond fund 5131792 continuously in ILS."),),
        execution=ExecutionSpec("continuous", "Harel fund 5131792 remains continuously invested", (0,), (0,)),
        data_confidence="moderate",
        notes="Actual Maya redemption-price history for fund 5131792 only. No index 602 proxy or pre-fund history is spliced in. Fund expenses are already embedded; no extra 0.12% deduction. Uploaded replacement history is unverified and must be labelled separately.",
    )


class BuyAndHoldACWI:
    """Continuous iShares MSCI ACWI ETF holding."""

    name = "Buy and Hold ACWI"
    data_assets = ("ACWI",)
    market_data_assets = data_assets
    signal_assets: tuple[str, ...] = ()
    benchmark_asset = "ACWI"
    strategy_mode = "buy_and_hold"
    signal_mode = "internal"
    backtest_available = True
    validation_profile = ValidationProfile(
        profile_id="buy-and-hold-acwi",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "ACWI remains continuously invested; the app does not run a timing rule."),),
        execution=ExecutionSpec("continuous", "ACWI remains continuously invested", (0,), (0,)),
        applicable_tests=frozenset({"alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "block_bootstrap", "data_quality"}),
        data_confidence="established",
        notes="Research evaluates continuous ACWI holding using its available ETF history. No pre-ETF splice is used.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for date, values in monthly_prices.loc[:, self.data_assets].dropna(how="any").iterrows():
            rows.append({
                "signal_date": date,
                "ACWI_price": values["ACWI"],
                "regime": "buy-and-hold",
                "selected_asset": "ACWI",
                "previous_asset": "ACWI" if rows else None,
                "trade": not rows,
            })
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
