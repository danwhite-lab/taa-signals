from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from test_api import client
from server import fund_registry, private_api, signals
from haa.my_funds import PREFIX


class Registry:
    def __init__(self, rows, user):
        self.rows, self.user = rows, user
        self.filters = {}
        self.change = None

    def select(self, _columns):
        return self

    def eq(self, field, value):
        self.filters[field] = value
        return self

    def insert(self, row):
        assert row["user_id"] == self.user
        self.rows.append({"archived": False, **deepcopy(row)})
        return self

    def update(self, fields):
        self.change = fields
        return self

    def execute(self):
        matches = [row for row in self.rows if row["user_id"] == self.user
                   and all(row[field] == value for field, value in self.filters.items())]
        if self.change:
            for row in matches:
                row.update(self.change)
        return SimpleNamespace(data=deepcopy(matches))


@pytest.fixture
def accounts(monkeypatch):
    rows, portfolios = [], {}
    fund = {"name": "Example fund", "market": "TASE", "identifier": "5139837", "kind": "mutual", "currency": "ILS"}
    quote = {"price": "2.55", "as_of": "2026-11-05", "source": "MAYA", "currency": "ILS", "fresh": True}
    monkeypatch.setenv("SUPABASE_URL", "https://test.invalid")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-public")
    monkeypatch.setenv("MY_FUNDS_SIGNING_KEY", "test-secret")
    monkeypatch.setattr(private_api.sync, "verified_session", lambda url, key, tokens: {
        **tokens, "user_id": tokens["access_token"]})
    monkeypatch.setattr(fund_registry, "_table", lambda session: Registry(rows, session["user_id"]))
    monkeypatch.setattr(fund_registry, "verify_fund", lambda market, identifier: (
        {**fund, "identifier": identifier, "name": fund["name"] if identifier == "5139837" else "Replacement fund"}, quote))
    monkeypatch.setattr(private_api.sync, "load_workspace", lambda *_: {"revision": 0, "payload": {}})
    monkeypatch.setattr(private_api.sync, "list_portfolios", lambda url, key, session: list(portfolios.get(session["user_id"], {}).values()))

    def save(url, key, session, payload, **kwargs):
        identifier = kwargs["existing_id"] or "10000000-0000-4000-8000-000000000001"
        record = {"id": identifier, "name": payload["name"], "payload": payload, "is_default": True}
        portfolios.setdefault(session["user_id"], {})[identifier] = record
        return record

    monkeypatch.setattr(private_api.sync, "save_portfolio", save)
    days = pd.bdate_range("2025-01-02", "2026-11-06")
    monkeypatch.setattr(signals, "history", lambda fund: (pd.Series(range(100, 100 + len(days)), index=days, name=fund["model"]), "Close"))
    import haa.my_funds
    monkeypatch.setattr(haa.my_funds, "quote", lambda _fund: quote)
    return [{"Authorization": f"Bearer {user}"} for user in ("account-a", "account-b")]


def test_private_fund_registration_to_saved_sleeve_quote_signal_backtest_and_archive(accounts):
    alice, bob = accounts
    listing = {"market": "TASE", "identifier": "5139837"}
    assert client.get("/api/my-funds").status_code == 401
    checked = client.post("/api/my-funds/check", headers=alice, json=listing)
    assert checked.json()["quote"]["as_of"] == "2026-11-05"
    assert client.get("/api/my-funds", headers=alice).json()["funds"] == []
    created = client.post("/api/my-funds", headers=alice, json={**listing, "name": checked.json()["fund"]["name"]})
    assert created.status_code == 200, created.text
    model = created.json()["model"]
    assert model.startswith(PREFIX)

    body = {"payload": {"version": 1, "name": "Example", "total_ils": 1000,
                        "sleeves": [{"model": model, "weight": 100}]}}
    for headers, status in ((alice, 200), (bob, 422)):
        response = client.post("/api/portfolios", headers=headers, json=body)
        assert response.status_code == status, response.text
    portfolio = client.get("/api/portfolios", headers=alice).json()[0]
    assert client.get("/api/my-funds", headers=bob).json()["funds"] == []
    assert model not in client.get("/api/backtest/models", headers=bob).text
    assert model not in client.get("/api/rebalance/instruments", headers=bob).text
    assert client.get("/api/signals", headers=bob, params={"label": model}).status_code == 400
    assert client.get("/api/backtest/options", headers=bob, params={"label": model}).status_code == 400
    assert client.post("/api/rebalance/editor", headers=bob, json={
        "cash": "0", "rows": [{"Security": model, "Currency": "ILS", "Enter as": "Units"}]}).status_code == 400

    def check_usage():
        rebalance = client.get("/api/rebalance", headers=alice)
        assert rebalance.status_code == 200, rebalance.text
        assert rebalance.json()["targets"] == {model: 1}
        assert rebalance.json()["quotes"][model]["price"] == "2.55"
        signal = client.get("/api/signals", headers=alice, params={"label": model, "as_of": "2026-11-06"})
        assert signal.json()["current"]["decision"]["selected_asset"] == model, signal.text
        today = client.get("/api/today?preview=false", headers=alice)
        assert today.status_code == 200, today.text
        assert "Example fund" in today.text

    check_usage()
    result = client.post("/api/backtest", headers=alice, json={"label": model})
    assert result.status_code == 200, result.text
    assert "2025-01-02" in result.text
    key = result.json()["cache"]["key"]
    assert client.get("/api/backtest/download", headers=bob, params={"key": key, "kind": "audit"}).status_code == 404
    assert client.get("/api/backtest/download", headers=alice, params={"key": key, "kind": "audit"}).status_code == 200

    archive = f"/api/my-funds/{model.removeprefix(PREFIX)}/archive"
    assert client.post(archive, headers=bob).status_code == 404
    assert client.post(archive, headers=alice).status_code == 200
    assert model not in client.get("/api/backtest/models", headers=alice).text
    assert client.post("/api/portfolios", headers=alice, json=body).status_code == 422
    check_usage()
    unchanged = client.get("/api/portfolios", headers=alice).json()[0]
    assert unchanged == portfolio

    replacement = client.post("/api/my-funds", headers=alice, json={
        "market": "TASE", "identifier": "5132972", "name": "Replacement fund"}).json()["model"]
    instrument = {"id": model, "identifier": listing["identifier"], "market": "TASE", "currency": "ILS",
                  "label": "Example fund", "units": "12.345"}
    from haa.rebalance_holdings import empty_account
    original_holdings = {**empty_account(), "positions": {model: instrument}}
    original_loader = private_api.sync.load_workspace
    try:
        private_api.sync.load_workspace = lambda *_: {"revision": 1, "payload": {"holdings_account": deepcopy(original_holdings)}}
        updated = client.post("/api/portfolios", headers=alice, json={
            "id": portfolio["id"], "expected_updated_at": "2026-11-09T11:00:00Z",
            "payload": {**body["payload"], "sleeves": [{"model": replacement, "weight": 100}]}})
        assert updated.status_code == 200, updated.text
        state = client.get("/api/rebalance", headers=alice).json()
        assert state["targets"] == {replacement: 1}
        assert state["account"] == original_holdings
        assert state["quotes"][model]["price"] == "2.55"
    finally:
        private_api.sync.load_workspace = original_loader


def test_registered_fractional_purchase_and_legacy_whole_units():
    from haa.my_funds import instrument, use_funds
    from haa.rebalance_holdings import apply_purchases, empty_account, make_buy_plan, validate_account

    fund = {"model": PREFIX + "fund", "name": "MAYA fund", "market": "TASE",
            "identifier": "5139837", "currency": "ILS", "kind": "mutual"}
    key = fund["model"]
    item = instrument(fund)
    account = empty_account()
    with use_funds([fund]):
        plan = make_buy_plan(account, {key: item}, {key: 1}, {key: {"price": "2.50"}},
                             "1", "100.50", {}, "proportional")
        assert float(plan["orders"][0]["units"]) == 40.2
        result = apply_purchases(account, plan, [{"id": key, "units": "40.2", "paid_ils": "100.50"}], {})
        assert result["positions"][key]["units"] == "40.2"
    with pytest.raises(ValueError):
        validate_account(result)
