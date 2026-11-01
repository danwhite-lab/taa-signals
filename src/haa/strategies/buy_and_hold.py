"""Reusable internally managed strategies held continuously by the investor."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from ..buy_and_hold_funds import fund
from ..constants import TA125_SMART_MOMENTUM_ASSET
from ..trading_fees import TradingFees
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


class BuyAndHoldNasdaq3xMonthlyIsrael(BuyAndHoldSPY):
    """Continuous holding of MTF Nasdaq-100 x3 Monthly, TASE ETF 1187079."""

    name = "Buy and Hold Nasdaq-100 x3 Monthly Israel"
    holding_asset = "NASDAQ_X3_MONTHLY_IL"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    actual_history_only = True
    risk_warning = "3x leveraged fund with a monthly leverage reset: held continuously through all falls; it can lose most or all of its value."
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-nasdaq-x3-monthly-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold MTF Nasdaq-100 x3 Monthly 1187079 continuously in ILS; USD exposure from the underlying."),),
        execution=ExecutionSpec("continuous", "MTF 1187079 remains continuously invested", (0,), (0,)),
        data_confidence="limited",
        notes="Actual TASE/Maya history of MTF 1187079 only. No QQQ, TQQQ, TA-125 index or any other proxy history is spliced in; no pre-fund extension or forward fill. Fund management expenses are embedded in prices and not deducted again. History starts at whatever the public endpoint actually returns.",
    )


class BuyAndHoldTA125x3Israel(BuyAndHoldSPY):
    """Continuous holding of Ayalon Extreme TA-125 x3, Maya fund 5117684."""

    name = "Buy and Hold TA-125 x3 Israel"
    holding_asset = "TA125_X3_IL"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    actual_history_only = True
    risk_warning = "3x leveraged fund: held continuously through all falls; it can lose most or all of its value. Its purchase entry fee (about 0.4% as of October 2026) is not reflected in the price series or modeled here, so real results with repeated purchases would be modestly worse than shown."
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-ta125-x3-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold Ayalon Extreme TA-125 x3 fund 5117684 continuously in ILS."),),
        execution=ExecutionSpec("continuous", "Ayalon 5117684 remains continuously invested", (0,), (0,)),
        data_confidence="limited",
        notes="Actual TASE/Maya redemption-price history of Ayalon 5117684 only. No QQQ, TQQQ, TA-125 index or any other proxy history is spliced in; no pre-fund extension or forward fill. Fund management expenses are embedded in prices and not deducted again. History starts at whatever the public endpoint actually returns. The purchase entry fee is not modeled; see the risk warning.",
    )


class BuyAndHoldSP500x3Israel(BuyAndHoldSPY):
    """Continuous holding of ILS-hedged Ayalon Extreme S&P 500 x3, Maya fund 5117759."""

    name = "Buy and Hold S&P 500 x3 Israel"
    holding_asset = "SP500_X3_IL"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    actual_history_only = True
    risk_warning = "3x leveraged fund: held continuously through all falls; it can lose most or all of its value. Its purchase entry fee (about 0.4% as of October 2026) is not reflected in the price series or modeled here, so real results with repeated purchases would be modestly worse than shown."
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-sp500-x3-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold Ayalon Extreme S&P 500 x3 fund 5117759 continuously in ILS; dollar/shekel exposure is hedged."),),
        execution=ExecutionSpec("continuous", "Ayalon 5117759 remains continuously invested", (0,), (0,)),
        data_confidence="limited",
        notes="Actual Maya redemption-price history of Ayalon 5117759 only. ILS-hedged: S&P 500 moves x3, largely without USD/ILS moves. No SPY, SSO, UPRO or any other proxy, pre-fund extension or forward fill. Management fees of 1.85% and trustee fees of 0.04% are embedded in redemption prices and not deducted again. History starts at whatever the public endpoint actually returns within the existing five-year request window, not necessarily the fund's 2013 launch. The purchase entry fee is not modeled; see the risk warning.",
    )


class BuyAndHoldDAX3xMonthlyIsrael(BuyAndHoldSPY):
    """Continuous holding of KSM DAX x3 Monthly, unhedged TASE ETF 1146984."""

    name = "Buy and Hold DAX x3 Monthly Israel"
    holding_asset = "DAX_X3_MONTHLY_IL"
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    actual_history_only = True
    risk_warning = "3x leveraged fund with a monthly leverage reset: held continuously through all falls; it can lose most or all of its value."
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-dax-x3-monthly-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold KSM DAX x3 Monthly ETF 1146984 continuously in ILS; EUR exposure from the underlying. Leverage resets monthly."),),
        execution=ExecutionSpec("continuous", "KSM 1146984 remains continuously invested", (0,), (0,)),
        data_confidence="limited",
        notes="Actual TASE history of KSM 1146984 only. Unhedged, with EUR exposure from the underlying. Leverage resets monthly. No DAX-index or any other proxy, pre-fund extension or forward fill. Management fees of 2.75% and trustee fees of 0.03% are embedded in prices and not deducted again. Exchange-traded: no purchase addition; ordinary broker commission applies. History starts at whatever the public endpoint actually returns within the existing five-year request window.",
    )


class _ConfiguredBuyAndHold(BuyAndHoldSPY):
    """A continuous holding whose instrument details live in the fund data file."""

    fund_key: str
    actual_history_only = True
    declared_proxy = False
    price_only = False
    default_trading_fees: TradingFees | None = None


_SEMICONDUCTORS_US = fund("semiconductors_us")
_SEMICONDUCTORS_ISRAEL = fund("semiconductors_israel")
_JAPAN_US = fund("japan_us")
_JAPAN_ISRAEL = fund("japan_israel")
_WORLD_VALUE_ISRAEL = fund("world_value_israel")


class BuyAndHoldSemiconductors(_ConfiguredBuyAndHold):
    """Declared SOXX proxy for MVIS US Listed Semiconductor 25 Total Return."""

    fund_key = _SEMICONDUCTORS_US.key
    name = _SEMICONDUCTORS_US.name
    holding_asset = _SEMICONDUCTORS_US.holding_asset
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    declared_proxy = True
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-semiconductors-us",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold the declared SOXX proxy continuously in USD."),),
        execution=ExecutionSpec("continuous", "SOXX remains continuously invested", (0,), (0,)),
        data_confidence="limited",
        notes=_SEMICONDUCTORS_US.source_note,
    )


class BuyAndHoldSemiconductorsIsrael(_ConfiguredBuyAndHold):
    """Continuous holding of the actual Kesem MVSMHTR fund in ILS."""

    fund_key = _SEMICONDUCTORS_ISRAEL.key
    name = _SEMICONDUCTORS_ISRAEL.name
    holding_asset = _SEMICONDUCTORS_ISRAEL.holding_asset
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-semiconductors-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold Kesem MVSMHTR 5132972 continuously in ILS."),),
        execution=ExecutionSpec("continuous", "Kesem MVSMHTR 5132972 remains continuously invested", (0,), (0,)),
        data_confidence="moderate",
        notes=_SEMICONDUCTORS_ISRAEL.source_note,
    )


class BuyAndHoldJapan(_ConfiguredBuyAndHold):
    """Continuous Nikkei 225 price-index holding; no total-return claim."""

    fund_key = _JAPAN_US.key
    name = _JAPAN_US.name
    holding_asset = _JAPAN_US.holding_asset
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    price_only = True
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-japan-us",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold the Nikkei 225 price index continuously; total return is not available in this app."),),
        execution=ExecutionSpec("continuous", "Nikkei 225 price index remains continuously invested", (0,), (0,)),
        data_confidence="limited",
        notes=_JAPAN_US.source_note,
    )


class BuyAndHoldJapanIsrael(_ConfiguredBuyAndHold):
    """Continuous holding of the actual currency-hedged MTF Nikkei 225 ETF."""

    fund_key = _JAPAN_ISRAEL.key
    name = _JAPAN_ISRAEL.name
    holding_asset = _JAPAN_ISRAEL.holding_asset
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    default_trading_fees = TradingFees("ILS", **_JAPAN_ISRAEL.fee_options)
    validation_profile = replace(
        BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-japan-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold currency-hedged MTF Nikkei 225 ETF 1150531 continuously in ILS."),),
        execution=ExecutionSpec("continuous", "MTF Nikkei 225 1150531 remains continuously invested", (0,), (0,)),
        data_confidence="moderate",
        notes=_JAPAN_ISRAEL.source_note,
    )


class BuyAndHoldWorldValueIsrael(_ConfiguredBuyAndHold):
    """Continuous holding of the actual USD-hedged Tachlit World Value ETF."""
    fund_key = _WORLD_VALUE_ISRAEL.key
    name = _WORLD_VALUE_ISRAEL.name
    holding_asset = _WORLD_VALUE_ISRAEL.holding_asset
    data_assets = (holding_asset,)
    market_data_assets = data_assets
    benchmark_asset = holding_asset
    default_trading_fees = TradingFees("ILS", **_WORLD_VALUE_ISRAEL.fee_options)
    validation_profile = replace(BuyAndHoldSPY.validation_profile,
        profile_id="buy-and-hold-world-value-israel",
        published_parameters=(ParameterSpec("implementation", "continuous holding", (), "Hold Tachlit World Value USD-hedged ETF 1189596 continuously in ILS."),),
        execution=ExecutionSpec("continuous", "Tachlit World Value 1189596 remains continuously invested", (0,), (0,)),
        data_confidence="moderate", notes=_WORLD_VALUE_ISRAEL.source_note)


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
