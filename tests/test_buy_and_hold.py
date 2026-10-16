import pandas as pd
import pytest

from haa.constants import TA125_SMART_MOMENTUM_ASSET
from haa.strategies import BuyAndHoldQQQ, BuyAndHoldQQQIsrael, BuyAndHoldSPY, BuyAndHoldSPYIsrael, TA125SmartMomentum
from haa.engine import run_backtest
from haa.model_catalog import resolve
from haa.portfolio import execution_security_label
from haa.tase_data import TASE_ISRAEL_ASSET_IDS
from haa.strategies import BuyAndHoldGoldIsrael, BuyAndHoldHarelBondsIsrael
from haa.strategies import BuyAndHoldGLD, BuyAndHoldIEF


def test_gld_is_separate_usd_gold_implementation_with_actual_history():
    model = BuyAndHoldGLD()
    definition = resolve("Buy and Hold", "Gold", "GLD (USD)")
    assert definition.model_class is BuyAndHoldGLD
    assert definition.execution_currency == "USD"
    assert model.data_assets == ("GLD",)
    assert model.actual_history_only
    assert model.signal_assets == ()
    prices = pd.DataFrame({"GLD": [100., 110., 121.]},
                          index=pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]))
    decisions = model.decisions(prices)
    assert decisions.selected_asset.eq("GLD").all()
    assert decisions.trade.tolist() == [True, False, False]
    assert decisions.index.equals(prices.index)
    result = run_backtest(decisions, prices, 1000., tax_enabled=True, benchmark_asset=model.benchmark_asset)
    assert result.monthly.pre_tax_value.iloc[-1] == pytest.approx(1210.)
    assert result.tax_events.empty
    assert resolve("Buy and Hold", "Gold", "TASE 1147875").model_class is BuyAndHoldGoldIsrael


def test_ief_is_plain_usd_buy_and_hold_without_pre_etf_proxy():
    model = BuyAndHoldIEF()
    definition = resolve("Buy and Hold", "US Treasury Bonds", "IEF (USD)")
    assert definition.model_class is BuyAndHoldIEF
    assert definition.execution_currency == "USD"
    assert model.data_assets == ("IEF",) and model.signal_assets == ()
    assert model.actual_history_only
    prices = pd.DataFrame({"IEF": [100., 110., 121.]},
                          index=pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]))
    decisions = model.decisions(prices)
    assert decisions.selected_asset.eq("IEF").all()
    assert decisions.trade.tolist() == [True, False, False]
    assert decisions.index.equals(prices.index)
    result = run_backtest(decisions, prices, 1000., tax_enabled=True, benchmark_asset="IEF")
    assert result.monthly.pre_tax_value.iloc[-1] == pytest.approx(1210.)
    assert result.monthly.after_tax_value.equals(result.monthly.pre_tax_value)
    assert result.tax_events.empty


@pytest.mark.parametrize("cls,asset,security,variant,implementation", [
    (BuyAndHoldGoldIsrael, "GOLD_IL", "1147875", "Gold", "TASE 1147875"),
    (BuyAndHoldHarelBondsIsrael, "HAREL_GOV_BONDS_IL", "5131792", "Israeli Government Bonds", "Harel 5131792"),
])
def test_plain_local_holdings_have_no_signals_or_proxy_splice(cls, asset, security, variant, implementation):
    model = cls()
    prices = pd.DataFrame({asset: [100., 110., 121.]},
                          index=pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]))
    decisions = model.decisions(prices)
    assert decisions.selected_asset.eq(asset).all()
    assert decisions.trade.tolist() == [True, False, False]
    assert model.signal_assets == ()
    assert model.actual_history_only
    assert decisions.index.min() == prices.index.min()
    assert model.data_assets == (asset,)
    assert TASE_ISRAEL_ASSET_IDS[asset] == security
    definition = resolve("Buy and Hold", variant, implementation)
    assert definition.model_class is cls and definition.execution_currency == "ILS"
    assert security in execution_security_label(asset, "ILS")
    result = run_backtest(decisions, prices, 1000, tax_enabled=True, benchmark_asset=asset)
    assert result.monthly.pre_tax_value.iloc[-1] == pytest.approx(1210.)
    assert result.monthly.after_tax_value.equals(result.monthly.pre_tax_value)
    assert result.tax_events.empty


def test_buy_and_hold_strategy_remains_invested_without_momentum_signal():
    dates = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-28"])
    prices = pd.DataFrame({TA125_SMART_MOMENTUM_ASSET: [100.0, 101.0, 102.0], "SPY": [500.0, 510.0, 520.0]}, index=dates)

    decisions = TA125SmartMomentum().decisions(prices)

    assert list(decisions["selected_asset"]) == [TA125_SMART_MOMENTUM_ASSET] * 3
    assert list(decisions["trade"]) == [True, False, False]
    assert decisions["regime"].eq("buy-and-hold").all()


def test_buy_and_hold_spy_remains_invested():
    dates = pd.to_datetime(["2024-01-31", "2024-02-29"])
    decisions = BuyAndHoldSPY().decisions(pd.DataFrame({"SPY": [500.0, 510.0]}, index=dates))

    assert list(decisions["selected_asset"]) == ["SPY", "SPY"]
    assert list(decisions["trade"]) == [True, False]


def test_israel_spy_buy_and_hold_uses_actual_cspx_prices_and_ils_mapping():
    strategy = BuyAndHoldSPYIsrael()
    dates = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"])
    prices = pd.DataFrame({"CSPX_IL": [100., 110., 121.]}, index=dates)
    decisions = strategy.decisions(prices)
    assert decisions["selected_asset"].eq("CSPX_IL").all()
    assert decisions["trade"].tolist() == [True, False, False]
    result = run_backtest(decisions, prices, 1000, tax_enabled=True, benchmark_asset=strategy.benchmark_asset)
    assert abs(result.monthly["pre_tax_value"].iloc[-1] - 1210) < 1e-9
    assert result.monthly["pre_tax_value"].equals(result.monthly["benchmark_value"])
    assert result.tax_events.empty
    definition = resolve("Buy and Hold", "S&P 500", "Israel")
    assert definition.model_class is BuyAndHoldSPYIsrael
    assert definition.execution_currency == "ILS"
    assert TASE_ISRAEL_ASSET_IDS["CSPX_IL"] == "1159250"
    assert execution_security_label("CSPX_IL", "ILS") == "CSPX — 1159250"


def test_qqq_buy_and_hold_implementations_remain_invested_and_use_separate_histories():
    dates = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"])
    for implementation, cls, asset, currency in (
        ("QQQ", BuyAndHoldQQQ, "QQQ", "USD"),
        ("Israel", BuyAndHoldQQQIsrael, "QQQ_IL", "ILS"),
    ):
        definition = resolve("Buy and Hold", "QQQ", implementation)
        assert definition.model_class is cls
        assert definition.execution_currency == currency
        strategy = cls()
        assert strategy.data_assets == (asset,)
        prices = pd.DataFrame({asset: [100., 110., 121.]}, index=dates)
        decisions = strategy.decisions(prices)
        assert decisions["selected_asset"].eq(asset).all()
        assert decisions["trade"].tolist() == [True, False, False]
        result = run_backtest(decisions, prices, 1000, tax_enabled=True, benchmark_asset=strategy.benchmark_asset)
        assert abs(result.monthly["pre_tax_value"].iloc[-1] - 1210) < 1e-9
        assert result.monthly["pre_tax_value"].equals(result.monthly["benchmark_value"])
        assert result.tax_events.empty
    assert TASE_ISRAEL_ASSET_IDS["QQQ_IL"] == "1186063"
    assert execution_security_label("QQQ_IL", "ILS") == "Nasdaq-100 — 1186063"
