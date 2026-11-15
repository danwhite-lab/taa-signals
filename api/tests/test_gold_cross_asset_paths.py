
import numpy as np
import pandas as pd
import pytest

from test_api import client
from haa.constants import TACHLIT_HEDGED_GOLD_ASSET
from haa.market_sessions import us_equity_sessions
from haa.model_catalog import definition_for_label
from server import private_api, signals, today


@pytest.fixture
def histories(monkeypatch):
    us = us_equity_sessions("2023-01-01", "2025-08-20")
    prices = pd.DataFrame({"GLD": 100. + np.arange(len(us)), "IEF": 100. + np.arange(len(us)),
                           "BIL": 100. + .02 * np.arange(len(us)), "SPY": 100. + np.arange(len(us))}, index=us)
    prices[TACHLIT_HEDGED_GOLD_ASSET] = np.nan
    prices["GOLD_CASH_IL"] = np.nan
    calls = []
    def yahoo(mapping, require_adjusted_assets=()):
        calls.append((mapping, set(require_adjusted_assets)))
        return prices.loc[:, list(mapping)].copy()

    monkeypatch.setattr(signals.data, "download_yahoo_prices", yahoo)
    monkeypatch.setattr(signals, "load_inputs", lambda definition, **kwargs: signals.live_inputs(definition, **kwargs))
    monkeypatch.setattr(signals.tase_data, "download_tase_israel_prices",
                        lambda *_a, **_k: (_ for _ in ()).throw(signals.tase_data.TaseDataError("Local history unavailable")))
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "fixture")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("MY_FUNDS_SIGNING_KEY", raising=False)
    monkeypatch.setattr(private_api.sync, "verified_session", lambda *_: {"user_id": "test"})
    return prices, calls


AUTH = {"Authorization": "Bearer fixture"}


def test_gold_rules_and_selectors(histories):
    for label, currency in [("Gold Cross-Asset", "USD"), ("Gold Cross-Asset Israel", "ILS")]:
        rules = client.get("/api/rules", params={"label": label}).json()["model"]
        assert rules["execution_currency"] == currency
        assert "Implementation interpretation - exact Laurent conventions unverified" in rules["markdown"]
        assert "GLD" in rules["plain_text"] and "IEF" in rules["plain_text"]
        for path in ("/api/backtest/models", "/api/backtest/config?mode=portfolio", "/api/compare/options?kind=models"):
            assert label in {model["label"] for model in client.get(path, headers=AUTH).json()["models"]}


@pytest.mark.parametrize("risk_off", [False, True])
def test_today_and_signals_keep_us_signal_if_tase_feed_fails(histories, monkeypatch, risk_off):
    prices, calls = histories
    if risk_off:
        prices["IEF"] = 100.
    label = "Gold Cross-Asset Israel"
    definition = definition_for_label(label)
    as_of = pd.Timestamp("2025-07-10", tz="UTC")
    monkeypatch.setattr(today, "utc_now", lambda: as_of)
    monkeypatch.setattr(private_api, "portfolios", lambda _: [{"is_default": True, "payload": {
        "name": "Fixture", "sleeves": [{"model": label, "weight": 100}]}}])
    monkeypatch.setattr(private_api, "workspace", lambda _: {"payload": {}})
    values = client.get("/api/today?preview=false", headers=AUTH).json()
    row = values["signals"][0]
    assert row["signal_details"]["Execution currency"] == "ILS"
    assert row["status_code"] == "check_data"
    assert row["holding_display"][0]["security_number"] == ("5140918" if risk_off else "5141627")
    payload = client.get("/api/signals", headers=AUTH, params={"label": label, "as_of": "2025-07-10"}).json()
    assert payload["current"]["available"] and payload["current"]["effective_start"] is None
    assert payload["current"]["decision"]["selected_asset"] == definition.model_class.execution_assets[1 if risk_off else 0]
    assert payload["current"]["decision"]["GLD_12m_return"] > 0
    assert (payload["current"]["decision"]["IEF_12m_return"] == 0 if risk_off
            else payload["current"]["decision"]["IEF_12m_return"] > 0)
    assert all(required == {"GLD", "IEF"} for _, required in calls)
    denied = client.get("/api/backtest/options", headers=AUTH, params={"label": label})
    assert denied.status_code == 400
    assert "actual fund" in denied.json()["detail"]


def test_gold_backtest_and_compare_use_actual_execution_and_declared_benchmark(histories):
    _, calls = histories
    label = "Gold Cross-Asset"
    options = client.get("/api/backtest/options", headers=AUTH, params={"label": label})
    assert options.status_code == 200, options.text
    result = client.post("/api/backtest", headers=AUTH, json={"label": label, "fees_enabled": False})
    assert result.status_code == 200, result.text
    assert "GLD buy-and-hold" in result.text and "IEF_12m_return" in result.text
    portfolio = client.post("/api/backtest", headers=AUTH, json={
        "mode": "portfolio", "fees_enabled": False, "sleeves": [
            {"id": 1, "model": label, "weight": 50}, {"id": 2, "model": "Buy and Hold SPY", "weight": 50}]})
    assert portfolio.status_code == 200, portfolio.text
    comparison = client.post("/api/compare", headers=AUTH, json={"models": [label, "Buy and Hold Gold GLD"]})
    assert comparison.status_code == 200, comparison.text
    assert "GLD" in comparison.json()["benchmark"]
    assert all(required == {"GLD", "IEF", "BIL"} for _, required in calls)


def test_israel_backtest_uses_only_actual_local_fund_history(histories, monkeypatch):
    from haa.market_sessions import tase_equity_sessions

    label = "Gold Cross-Asset Israel"
    sessions = tase_equity_sessions("2025-02-01", "2025-08-26")

    def tase(assets, **kwargs):
        assert set(assets) == {TACHLIT_HEDGED_GOLD_ASSET, "GOLD_CASH_IL"}
        history = pd.DataFrame({asset: 100. + np.arange(len(sessions)) for asset in assets}, index=sessions)
        metadata = pd.DataFrame({"source": "MAYA", "identifier": [
            signals.tase_data.TASE_ISRAEL_ASSET_IDS[asset] for asset in assets],
            "price_field": "MAYA published redemption price"}, index=pd.Index(assets, name="asset"))
        return history, metadata

    monkeypatch.setattr(signals.tase_data, "download_tase_israel_prices", tase)
    result = client.post("/api/backtest", headers=AUTH, json={"label": label, "fees_enabled": False})
    assert result.status_code == 200, result.text
    assert result.json()["actual_execution_start"].startswith("2025-02-02")
    assert "5141627" in result.text and "buy-and-hold" in result.text
    assert "1147875" not in result.text


@pytest.fixture
def late_cash_history(histories):
    prices, _ = histories
    prices.loc[:"2024-06-19", "BIL"] = np.nan
    prices.loc["2024-04-30", "IEF"] = 95.  # A risk-off month before cash history exists.
    return prices


def test_usd_default_window_and_early_start_validation(late_cash_history):
    label = "Gold Cross-Asset"
    options = client.get("/api/backtest/options", headers=AUTH, params={"label": label})
    assert options.status_code == 200, options.text
    assert options.json()["bounds"]["start_min"] == "2024-08-01"
    result = client.post("/api/backtest", headers=AUTH, json={"label": label})
    assert result.status_code == 200, result.text
    assert result.json()["actual_execution_start"][:10] == "2024-07-01"
    assert result.json()["first_date"][:10] == "2024-08-01"
    early = client.post("/api/backtest", headers=AUTH, json={"label": label, "start": "2024-06-01"})
    assert early.status_code == 400
    assert early.json()["detail"] == "Start date is outside the available data range."


def test_explicit_window_ignores_earlier_gap_but_rejects_gap_inside(late_cash_history):
    # The gold holding already exists. An isolated missing fill is not inception.
    late_cash_history.loc["2024-09-03", "GLD"] = np.nan
    label = "Gold Cross-Asset"
    supported = {"start": "2025-01-01", "end": "2025-05-01"}
    for payload in ({"label": label}, {"mode": "portfolio", "fees_enabled": False, "sleeves": [
        {"id": 1, "model": label, "weight": 50}, {"id": 2, "model": "Buy and Hold SPY", "weight": 50},
    ]}):
        result = client.post("/api/backtest", headers=AUTH, json={**payload, **supported})
        assert result.status_code == 200, result.text
        chart = result.json()["value_chart"]
        assert chart["start"][:10] >= supported["start"] and chart["end"][:10] <= supported["end"]
    compared = client.post("/api/compare", headers=AUTH, json={
        "models": [label, "Buy and Hold Gold GLD"], **supported})
    assert compared.status_code == 200, compared.text
    assert compared.json()["bounds"]["start"] == "2024-08-01"
    assert compared.json()["window"]["start"] >= supported["start"]
    assert compared.json()["window"]["end"] <= supported["end"]

    rejected = client.post("/api/backtest", headers=AUTH, json={"label": label})
    assert rejected.status_code == 400
    assert "missing actual daily price on scheduled execution date 2024-09-03" in rejected.json()["detail"]


@pytest.mark.parametrize("gap", ["missing signal", "early cash end"])
def test_full_coverage_window_refuses_later_data_loss(late_cash_history, gap):
    if gap == "missing signal":
        late_cash_history.loc["2024-09-30", "IEF"] = np.nan
        expected = "Missing monthly signal"
    else:
        late_cash_history.loc["2025-01-01":, "BIL"] = np.nan
        expected = "BIL: missing actual daily price"
    rejected = client.post("/api/backtest", headers=AUTH, json={"label": "Gold Cross-Asset"})
    assert rejected.status_code == 400
    assert expected in rejected.json()["detail"]
