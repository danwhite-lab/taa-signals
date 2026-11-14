from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from haa.constants import TACHLIT_HEDGED_GOLD_ASSET
from haa.engine import run_backtest
from haa.market_sessions import us_equity_sessions
from haa.monthly_execution import execution_dates
from haa.signals import latest_actionable_signal
from haa.strategies import GoldCrossAsset, GoldCrossAssetIsrael
from haa.tase_data import TASE_EXECUTION_ASSET_IDS, TASE_ISRAEL_ASSET_IDS, TasePriceSource
from haa.trading_fees import TradingFees


AS_OF = pd.Timestamp("2025-07-10")


@pytest.fixture
def month_ends():
    sessions = us_equity_sessions("2024-01-01", "2025-07-10")
    return pd.DatetimeIndex(sessions.to_series().groupby(sessions.to_period("M")).last())


@pytest.mark.parametrize(("gold", "treasuries", "holds_gold"), [
    (120, 110, True), (120, 90, False), (90, 110, False), (90, 90, False),
    (100, 110, False), (120, 100, False),
])
def test_both_returns_must_be_positive(month_ends, gold, treasuries, holds_gold):
    prices = pd.DataFrame(100., index=month_ends[:13], columns=["GLD", "IEF"])
    prices.iloc[-1] = [gold, treasuries]
    for model in (GoldCrossAsset(), GoldCrossAssetIsrael()):
        decision = model.decisions(prices, as_of=AS_OF).iloc[0]
        assert decision["GLD_12m_return"] == pytest.approx((gold - 100) / 100)
        assert decision["IEF_12m_return"] == pytest.approx((treasuries - 100) / 100)
        assert decision["both_positive"] == holds_gold
        assert decision["selected_asset"] == model.execution_assets[0 if holds_gold else 1]


@pytest.mark.parametrize("invalid", [None, np.nan, np.inf, -10, 0])
def test_warmup_missing_month_and_invalid_prices(month_ends, invalid):
    model = GoldCrossAsset()
    prices = pd.DataFrame(100., index=month_ends, columns=["GLD", "IEF"])
    assert model.decisions(prices.iloc[:12], as_of=AS_OF).empty
    assert model.decisions(prices, as_of=AS_OF).index.max() == month_ends[-2]
    changed = prices.drop(index=month_ends[7]) if invalid is None else prices.copy()
    if invalid is not None:
        changed.loc[month_ends[7], "GLD"] = invalid
    assert model.decisions(changed, as_of=AS_OF).empty

    # A current-month observation or a quote before the required US close
    # cannot make a stale monthly decision actionable.
    stale = prices.drop(index=month_ends[-2])
    earlier = month_ends[-2] - pd.Timedelta(days=3)
    stale.loc[earlier] = [105., 105.]
    decisions = model.decisions(stale, as_of=AS_OF)
    assert decisions.index.max() == month_ends[-3]
    assert latest_actionable_signal(decisions, stale.sort_index(), model.signal_assets, AS_OF).decision is None


def test_us_signal_is_independent_of_local_history_and_legacy_gold(month_ends):
    prices = pd.DataFrame({"GLD": np.arange(len(month_ends)) + 100.,
                           "IEF": np.arange(len(month_ends)) + 100.}, index=month_ends)
    original = GoldCrossAsset().decisions(prices, as_of=AS_OF)
    for local in (prices, prices.assign(**{TACHLIT_HEDGED_GOLD_ASSET: 2., "RVOL_CASH_IL": np.nan})):
        israeli = GoldCrossAssetIsrael().decisions(local, as_of=AS_OF)
        for field in ("GLD_12m_return", "IEF_12m_return", "regime"):
            pd.testing.assert_series_equal(original[field], israeli[field])
    assert TASE_ISRAEL_ASSET_IDS["GOLD_IL"] == "1147875"
    assert TASE_EXECUTION_ASSET_IDS["GOLD_IL"] == "5141627"
    assert TASE_ISRAEL_ASSET_IDS["RVOL_CASH_IL"] == "5117700"
    requested = []
    def security(number):
        requested.append(number)
        return SimpleNamespace(history=lambda **_: pd.DataFrame({"Close": [105.]}, index=month_ends[:1]))
    history = TasePriceSource(security).fetch_asset(TACHLIT_HEDGED_GOLD_ASSET)
    assert requested == ["5141627"]
    assert "redemption" in history.field


def test_monthly_execution_uses_actual_cash_fund_returns_and_realized_switches(month_ends):
    model = GoldCrossAsset()
    prices = pd.DataFrame(100., index=month_ends, columns=["GLD", "IEF", "BIL"])
    prices.loc[month_ends[12:15], "IEF"] = [110, 90, 90]
    prices.loc[month_ends[15:], "IEF"] = 110
    prices.loc[month_ends[12:], "GLD"] = 120
    decisions = model.decisions(prices, as_of=AS_OF).iloc[:5]
    fills = execution_dates(decisions.index, "US")
    assert fills[0] > decisions.index[0]
    for day, gold, cash in zip(fills, [200, 220, 220, 230, 240], [100, 102, 104, 106, 108]):
        prices.loc[day] = [gold, 300, cash]
    result = run_backtest(decisions, prices, 1000, tax_enabled=True, daily_prices=prices,
                          benchmark_asset="GLD", trading_fees=TradingFees("USD", usd_flat=1))
    assert list(result.audit.execution_date) == list(fills[:-1])
    assert list(result.audit.holding_period_return) == pytest.approx([.10, 104/102-1, 106/104-1, 240/230-1])
    assert list(result.monthly.pre_tax_fee) == pytest.approx([1, 2, 0, 2])
    assert list(result.tax_events.sold_asset) == ["GLD", "BIL"]
    assert result.tax_events.tax_paid.iloc[0] > 0
    with pytest.raises(ValueError, match="actual daily execution"):
        run_backtest(decisions, prices, 1000, benchmark_asset="GLD")
    with pytest.raises(ValueError, match="scheduled execution"):
        run_backtest(decisions, prices, 1000, daily_prices=prices.drop(index=fills[1]), benchmark_asset="GLD")


def test_tase_executes_after_calendar_month_end_even_if_us_closed_earlier():
    source = pd.DatetimeIndex(["2024-03-28", "2024-08-30"])
    assert list(execution_dates(source, "TASE")) == [pd.Timestamp("2024-04-01"), pd.Timestamp("2024-09-01")]
    assert list(execution_dates(source, "US")) == [pd.Timestamp("2024-04-01"), pd.Timestamp("2024-09-03")]


def test_tachlit_uses_its_dealing_days_after_the_tase_week_changed():
    source = pd.DatetimeIndex(["2026-04-30"])
    assert execution_dates(source, "TASE")[0] == pd.Timestamp("2026-05-04")
    assert execution_dates(source, "US")[0] == pd.Timestamp("2026-05-01")
