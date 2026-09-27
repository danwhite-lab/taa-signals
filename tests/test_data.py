import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from haa.data import download_latest_yahoo_close


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
