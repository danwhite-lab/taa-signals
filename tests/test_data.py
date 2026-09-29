import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from haa.data import download_latest_yahoo_close, download_yahoo_prices


def test_download_latest_yahoo_close_uses_most_recent_valid_close(monkeypatch):
    history = pd.DataFrame(
        {"Close": [3.68, None, 3.71]},
        index=pd.to_datetime(["2026-09-25 10:00Z", "2026-09-25 11:00Z", "2026-09-25 12:00Z"]),
    )
    fake_yfinance = SimpleNamespace(Ticker=lambda ticker: SimpleNamespace(history=lambda **kwargs: history))
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    rate, timestamp = download_latest_yahoo_close("USDILS=X")

    assert rate == 3.71
    assert timestamp == pd.Timestamp("2026-09-25 12:00")


def test_download_latest_yahoo_close_rejects_empty_history(monkeypatch):
    fake_yfinance = SimpleNamespace(Ticker=lambda ticker: SimpleNamespace(history=lambda **kwargs: pd.DataFrame()))
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    with pytest.raises(RuntimeError, match="no recent close"):
        download_latest_yahoo_close("USDILS=X")



def test_download_yahoo_prices_names_an_unavailable_ticker(monkeypatch):
    columns = pd.MultiIndex.from_product([["Adj Close"], ["SPY", "TIP", "IEF", "BIL"]])
    raw = pd.DataFrame(
        [[100.0, 90.0, 80.0, float("nan")]],
        columns=columns,
        index=pd.to_datetime(["2026-08-31"]),
    )
    fake_yfinance = SimpleNamespace(download=lambda *args, **kwargs: raw)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    with pytest.raises(RuntimeError, match="BIL"):
        download_yahoo_prices({"SPY": "SPY", "TIP": "TIP", "IEF": "IEF", "BIL": "BIL"})
