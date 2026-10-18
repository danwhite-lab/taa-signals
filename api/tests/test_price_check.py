import logging
from types import SimpleNamespace
import warnings

import pandas as pd
import pytest

from test_api import client, module


def stub_operations(monkeypatch):
    def price(identifier, row):
        row.update(price=123.5, price_date="2026-10-15T00:00:00", source="Synthetic test fixture")
    monkeypatch.setattr(module, "_us_price", price)
    monkeypatch.setattr(module, "_tase_price", price)
    monkeypatch.setattr(module, "_arvol_backtest", lambda row: row.update(engine_seconds=.01, phase="completed"))


def test_diagnostics_checks_exact_universe_and_is_not_cached(monkeypatch):
    stub_operations(monkeypatch)
    response = client.get("/api/price-check")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert [row["identifier"] for row in body["prices"]] == ["SPY", "QQQ", "VXUS", "1159250", "1187079", "5134713"]
    assert all(row["success"] and row["price"] == 123.5 and row["seconds"] >= 0 for row in body["prices"])
    assert body["backtest"]["success"] and body["total_seconds"] >= 0


def test_failure_is_verbatim_retains_cause_logs_warnings_and_does_not_skip_remaining_checks(monkeypatch):
    stub_operations(monkeypatch)
    def failure(identifier, row):
        if identifier != "SPY":
            row.update(price=10, price_date="2026-10-15")
            return
        logging.getLogger("yfinance").error("Exact provider 403 detail")
        warnings.warn("Exact provider warning", UserWarning)
        try:
            raise ValueError("Original upstream cause")
        except ValueError as exc:
            raise RuntimeError("Provider failed\nsecond line") from exc
    monkeypatch.setattr(module, "_us_price", failure)
    body = client.get("/api/price-check").json()
    first = body["prices"][0]
    assert not first["success"] and first["price"] is None
    assert first["error"] == "Provider failed\nsecond line"
    assert first["error_type"] == "RuntimeError"
    assert "Original upstream cause" in first["traceback"]
    assert any("Exact provider 403 detail" in item for item in first["provider_messages"])
    assert any("Exact provider warning" in item for item in first["provider_messages"])
    assert all(row["success"] for row in body["prices"][1:]) and body["backtest"]["success"]


def test_price_operations_delegate_to_existing_history_loaders(monkeypatch):
    index = pd.to_datetime(["2026-10-14", "2026-10-15"])
    calls = []
    def yahoo(mapping):
        calls.append(mapping)
        return pd.DataFrame({"SPY": [9., 10.]}, index=index)
    monkeypatch.setattr(module.engine_data, "download_yahoo_prices", yahoo)
    row = {}
    module._us_price("SPY", row)
    assert calls == [{"SPY": "SPY"}] and row["price"] == 10
    def fetch(self, asset):
        calls.append(asset)
        return SimpleNamespace(source="Existing test route", field="Published ETF NAV", prices=pd.Series([8., 11.], index=index))
    monkeypatch.setattr(module.engine_tase.TasePriceSource, "fetch_asset", fetch)
    module._tase_price("RVOL_3X_IL", row)
    assert calls[-1] == "RVOL_3X_IL" and row["price"] == 11
    assert row["price_field"] == "Published ETF NAV"


def test_backtest_uses_adjusted_opens_original_signals_and_existing_engine(monkeypatch):
    closes, opens, monthly = object(), object(), object()
    strategy = SimpleNamespace(name="Original V3", data_assets=("QQQ", "SPY"), benchmark_asset="SPY")
    decision_frame = pd.DataFrame(index=pd.to_datetime(["2026-10-14"]))
    strategy.decisions = lambda data: decision_frame if data is closes else pytest.fail("Wrong signal data")
    monkeypatch.setattr(module, "RVolShifterCashOnly", lambda: strategy)
    monkeypatch.setattr(module.engine_data, "download_yahoo_daily_bars", lambda mapping: (closes, opens))
    monkeypatch.setattr(module.engine_data, "to_month_end", lambda data: monthly)
    calls = []
    def engine(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(daily=pd.DataFrame(index=pd.to_datetime(["2026-10-15", "2026-10-16"])))
    monkeypatch.setattr(module, "run_backtest", engine)
    row = {}
    module._arvol_backtest(row)
    assert calls[0][0][0] is decision_frame and calls[0][0][1] is monthly
    assert calls[0][1]["daily_prices"] is closes and calls[0][1]["daily_open_prices"] is opens
    assert calls[0][1]["tax_enabled"] is True and row["daily_rows"] == 2
    assert all(row[field] >= 0 for field in ("data_seconds", "signal_seconds", "engine_seconds"))


def test_backtest_download_failure_never_claims_an_engine_run(monkeypatch):
    def failed(mapping):
        raise RuntimeError("Exact missing adjusted opens error")
    monkeypatch.setattr(module.engine_data, "download_yahoo_daily_bars", failed)
    row = module._timed_check("A-RVol", module._arvol_backtest)
    assert not row["success"] and row["error"] == "Exact missing adjusted opens error"
    assert row["phase"] == "download adjusted closes and opens"
    assert row["engine_seconds"] is None and row["data_seconds"] >= 0
