import pandas as pd

from haa.constants import TA125_SMART_MOMENTUM_ASSET
from haa.strategies import BuyAndHoldQQQ, BuyAndHoldQQQIsrael, BuyAndHoldSPY, BuyAndHoldSPYIsrael, TA125SmartMomentum
from haa.engine import run_backtest
from haa.model_catalog import resolve
from haa.portfolio import execution_security_label
from haa.tase_data import TASE_ISRAEL_ASSET_IDS


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
