import numpy as np
import pandas as pd

from haa.data import parse_ticker_map, to_month_end, upload_asset_from_filename
from haa.momentum import momentum_13612u


def test_13612u_matches_manual_example():
    # Month 12 price is 120 from historical prices: 100, then 110/105/102 at 1/3/6 months ago.
    prices = pd.Series([100, 101, 102, 103, 104, 105, 106, 102, 108, 110, 112, 110, 120], index=pd.date_range("2020-01-31", periods=13, freq="ME"))
    expected = ((120 / 110 - 1) + (120 / 110 - 1) + (120 / 106 - 1) + (120 / 100 - 1)) / 4
    assert momentum_13612u(prices).iloc[-1] == pytest_approx(expected)


def test_momentum_never_uses_future_prices():
    prices = pd.Series(np.arange(100, 116), index=pd.date_range("2020-01-31", periods=16, freq="ME"), dtype=float)
    baseline = momentum_13612u(prices).iloc[12]
    prices.iloc[13:] = 1_000_000
    assert momentum_13612u(prices).iloc[12] == baseline


def pytest_approx(value):
    import pytest
    return pytest.approx(value)


def test_yahoo_ticker_mapping_and_single_upload_file_names_are_explicit():
    assert parse_ticker_map("SPY=VOO\nTIP=TIP\nIEF=IEF\nBIL=BIL")["SPY"] == "VOO"
    assert upload_asset_from_filename("TIP_validation.csv") == "TIP"


def test_monthly_data_uses_actual_last_trading_date_and_excludes_partial_month():
    daily = pd.DataFrame({"SPY": [100.0, 101.0, 102.0]}, index=pd.to_datetime(["2026-08-31", "2026-09-01", "2026-09-22"]))
    monthly = to_month_end(daily, as_of=pd.Timestamp("2026-09-22"))
    assert monthly.index.equals(pd.DatetimeIndex([pd.Timestamp("2026-08-31")]))


def test_month_end_uses_each_market_last_close_when_us_and_tase_dates_differ():
    """TASE closed Thursday while the U.S. market traded Friday month-end."""
    daily = pd.DataFrame(
        {
            "US": [100.0, 101.0, 102.0],
            "TASE": [200.0, 201.0, np.nan],
        },
        index=pd.to_datetime(["2023-09-27", "2023-09-28", "2023-09-29"]),
    )

    monthly = to_month_end(daily, as_of=pd.Timestamp("2023-10-01"))

    assert monthly.index.equals(pd.DatetimeIndex([pd.Timestamp("2023-09-29")]))
    assert monthly.loc[pd.Timestamp("2023-09-29"), "US"] == 102.0
    # This is the actual Thursday close, not a synthetic Friday fill.
    assert monthly.loc[pd.Timestamp("2023-09-29"), "TASE"] == 201.0


def test_month_end_never_uses_tase_close_after_common_signal_date():
    daily = pd.DataFrame(
        {"US": [100.0, 101.0], "TASE": [200.0, 999.0]},
        # The Sunday row belongs to October and must not affect September.
        index=pd.to_datetime(["2023-09-29", "2023-10-01"]),
    )

    monthly = to_month_end(daily, as_of=pd.Timestamp("2023-10-02"))

    assert monthly.loc[pd.Timestamp("2023-09-29"), "TASE"] == 200.0
