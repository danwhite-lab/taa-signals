"""API safeguards use frozen research files, never live prices or account writes."""
from unittest.mock import Mock
import pytest
from test_api import client
from test_private_api import signed_in, HEADERS
from server import backtest, cache
from haa import deep_history as deep

KEYS = ("research_ta125_x3_ils", "research_nasdaq100_x3_ils")


def body(key, **extra):
    return {"mode": "deep", "sleeves": [{"id": 1, "model": key, "weight": 100}],
            "benchmark": deep.ALL_DEEP_HISTORY_SPECS[key].benchmark_key, "initial": 1000.,
            "fees_enabled": False, "tax_enabled": True, **extra}


@pytest.fixture(autouse=True)
def no_storage(monkeypatch):
    monkeypatch.setattr(backtest, "RESULTS", cache.ResultCache())
    monkeypatch.setattr(cache, "cache_client", Mock(side_effect=RuntimeError("Offline test")))


@pytest.mark.parametrize("key", KEYS)
def test_ils_standalone_results_and_deposits_keep_banner_and_currency(signed_in, key):
    for deposit in (0, 100):
        response = client.post("/api/backtest", headers=HEADERS, json=body(key, monthly_contribution=deposit))
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["currency"] == "ILS" and value["monthly_rows"] == 273
        assert "RESEARCH ONLY" in value["label"]
        assert deep.ILS_RESEARCH_BANNER in value["warnings"]
        assert "RESEARCH ONLY" in value["warnings"]
        assert value["settings"]["monthly_contribution"] == deposit
    config = client.get("/api/backtest/config", params={"mode": "deep"}, headers=HEADERS).json()
    assert key in config["single_options"] and key not in config["blend_options"]


@pytest.mark.parametrize("key", KEYS)
def test_ils_usd_mixing_and_conversion_rejected(signed_in, key):
    bad = [
        body(key, benchmark="sp500"),
        body(key, sleeves=[{"id": 1, "model": key, "weight": 50}, {"id": 2, "model": "buy_and_hold_sp500", "weight": 50}]),
        body(key, fx_conversion=True), body(key, inflation_adjustment=True),
    ]
    for request in bad:
        response = client.post("/api/backtest", headers=HEADERS, json=request)
        assert response.status_code == 400, response.text
    response = client.post("/api/backtest/load", headers=HEADERS, json={"mode": "deep",
        "payload": {"version": 1, "total_ils": 3500, "ils_per_usd": 3.5, "sleeves": [{"model": key, "weight": 100}]}})
    assert response.status_code == 400
    assert "saved-FX conversion" in response.json()["detail"]
