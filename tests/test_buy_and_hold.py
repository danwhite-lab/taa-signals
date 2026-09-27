import pandas as pd

from haa.constants import TA125_SMART_MOMENTUM_ASSET
from haa.strategies import TA125SmartMomentum


def test_buy_and_hold_strategy_remains_invested_without_momentum_signal():
    dates = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-28"])
    prices = pd.DataFrame({TA125_SMART_MOMENTUM_ASSET: [100.0, 101.0, 102.0], "SPY": [500.0, 510.0, 520.0]}, index=dates)

    decisions = TA125SmartMomentum().decisions(prices)

    assert list(decisions["selected_asset"]) == [TA125_SMART_MOMENTUM_ASSET] * 3
    assert list(decisions["trade"]) == [True, False, False]
    assert decisions["regime"].eq("buy-and-hold").all()
