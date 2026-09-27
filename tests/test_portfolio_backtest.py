import pandas as pd
import pytest

from haa.comparison import ModelInput
from haa.portfolio_backtest import run_portfolio_backtest


def decisions(index, asset):
    return pd.DataFrame({"selected_asset": asset, "regime": "test"}, index=pd.to_datetime(index))


def model(index, values, asset):
    prices = pd.DataFrame({asset: values, "SPY": values}, index=pd.to_datetime(index))
    return ModelInput(asset, decisions(index, asset), prices, None, "SPY")


def test_blends_monthly_sleeve_returns_and_resets_weights():
    dates = ["2024-01-31", "2024-02-29", "2024-03-31"]
    result = run_portfolio_backtest({
        "growth": (0.6, model(dates, [100, 110, 121], "A")),
        "defensive": (0.4, model(dates, [100, 100, 100], "B")),
    }, 100)
    assert result.monthly["pre_tax_monthly_return"].tolist() == pytest.approx([0.06, 0.06])
    assert result.monthly["pre_tax_value"].iloc[-1] == pytest.approx(112.36)


def test_uses_only_common_executable_history():
    first = model(["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"], [100, 101, 102, 103], "A")
    second = model(["2024-02-29", "2024-03-31", "2024-04-30", "2024-05-31"], [100, 101, 102, 103], "B")
    result = run_portfolio_backtest({"A": (0.5, first), "B": (0.5, second)}, 100)
    assert result.common_index.min() == pd.Timestamp("2024-03-31")
    assert result.common_index.max() == pd.Timestamp("2024-04-30")


def test_rejects_invalid_sleeve_weights():
    source = model(["2024-01-31", "2024-02-29"], [100, 101], "A")
    with pytest.raises(ValueError, match="total exactly 100%"):
        run_portfolio_backtest({"A": (0.9, source)}, 100)
