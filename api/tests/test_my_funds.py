from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from test_api import client
from server import fund_registry, private_api, rebalance_quotes, signals
from haa.fund_verification import WORDS
from server.compare import WORDS as COMPARE_WORDS
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
        if any(saved["user_id"] == self.user and saved["listing_key"] == row["listing_key"] for saved in self.rows):
            error = ValueError("private database body")
            error.code = "23505"
            raise error
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
    monkeypatch.setattr(signals, "load_inputs", lambda definition, **kwargs: signals.live_inputs(definition, daily_bars=kwargs.get("daily_bars", False)))
    monkeypatch.setattr(signals.data, "download_yahoo_prices", lambda mapping, **kwargs: pd.DataFrame({
        asset: range(200, 200 + len(days)) for asset in mapping}, index=days))
    monkeypatch.setattr(rebalance_quotes, "load_portfolio_signals", lambda *_: (
        [{"name": "Buy and Hold SPY", "currency": "USD", "target_weights": {"SPY": 1.0}}], []))
    monkeypatch.setattr(rebalance_quotes, "fx_quote", lambda _: {"price": "3.5", "fresh": True})
    monkeypatch.setattr(rebalance_quotes, "fetch_unit_quote", lambda _: quote)
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


def register(headers, identifier="5139837", name="Example fund", market="TASE"):
    return client.post("/api/my-funds", headers=headers, json={
        "market": market, "identifier": identifier, "name": name})


def save_portfolio(headers, *models):
    return client.post("/api/portfolios", headers=headers, json={"payload": {
        "version": 1, "name": "Portfolio", "sleeves": [
            {"model": model, "weight": 100 / len(models)} for model in models]}})


def test_mixed_registered_fund_portfolio_uses_own_currency_returns(accounts):
    alice, _ = accounts
    model = register(alice).json()["model"]
    models = ["Buy and Hold SPY", model]
    result = client.post("/api/backtest", headers=alice, json={
        "mode": "portfolio", "fees_enabled": False, "sleeves": [
            {"id": i, "model": label, "weight": 50} for i, label in enumerate(models, 1)]})
    assert result.status_code == 200, result.text
    assert WORDS["mixedReturnCaption"] in result.json()["captions"]
    saved = save_portfolio(alice, *models)
    assert saved.status_code == 200, saved.text
    compared = client.post("/api/compare", headers=alice, json={
        "mode": "portfolios", "portfolio_ids": [saved.json()["id"]]})
    assert compared.status_code == 400 and compared.json()["detail"] == COMPARE_WORDS["portfolioCurrency"]


def test_fees_refused_for_registered_eur_fund(accounts, monkeypatch):
    alice, _ = accounts
    monkeypatch.setattr(fund_registry, "verify_fund", lambda *_: (
        {"name": "EUR fund", "market": "Global", "identifier": "IWDA.AS", "kind": "etf",
         "currency": "EUR", "exchange": "AMS"}, {}))
    model = register(alice, "IWDA.AS", "EUR fund", "Global").json()["model"]
    for body in (
        {"label": model, "fees_enabled": True},
        {"mode": "portfolio", "fees_enabled": True, "sleeves": [
            {"id": 1, "model": "Buy and Hold SPY", "weight": 50}, {"id": 2, "model": model, "weight": 50}]},
    ):
        result = client.post("/api/backtest", headers=alice, json=body)
        assert result.status_code == 400 and result.json()["detail"] == WORDS["feeCurrency"]


@pytest.mark.parametrize("fault", ["changed_key", "unavailable"])
def test_registry_faults_keep_legacy_working_and_explain_missing_references(accounts, monkeypatch, fault):
    alice, _ = accounts
    model = register(alice).json()["model"]
    saved = save_portfolio(alice, model).json()
    if fault == "changed_key":
        monkeypatch.setenv("MY_FUNDS_SIGNING_KEY", "replacement-test-key")
        valid = register(alice, "5132972", "Replacement fund").json()["model"]
        listing = client.get("/api/my-funds", headers=alice)
        assert listing.status_code == 200
        assert listing.json() == {"configured": True, "rejected": 1, "status": "rejected_rows", "funds": [
            {"name": "Replacement fund", "market": "TASE", "identifier": "5132972", "kind": "mutual",
             "currency": "ILS", "model": valid, "archived": False}]}
        assert client.get("/api/backtest/options", headers=alice, params={"label": valid}).status_code == 200
        duplicate = register(alice)
        assert duplicate.status_code == 409 and duplicate.json()["detail"] == WORDS["duplicateRejected"]
        assert register(alice, "5132972", "Replacement fund").json()["detail"] == WORDS["duplicate"]
        expected = WORDS["rejectedRows"]
    else:
        def failed(_):
            raise ValueError("private provider body")
        monkeypatch.setattr(fund_registry, "_table", failed)
        listing = client.get("/api/my-funds", headers=alice)
        expected = WORDS["registryUnavailable"]
        assert listing.status_code == 503 and listing.json()["detail"] == expected

    responses = [
        save_portfolio(alice, model),
        client.get("/api/today?preview=false", headers=alice),
        client.get("/api/rebalance", headers=alice),
        client.get("/api/signals", headers=alice, params={"label": model}),
        client.get("/api/backtest/options", headers=alice, params={"label": model}),
        client.post("/api/backtest", headers=alice, json={"label": model}),
        client.post("/api/backtest/load", headers=alice, json={"mode": "portfolio", "portfolio_id": saved["id"]}),
        client.post("/api/compare", headers=alice, json={"models": ["Buy and Hold SPY", model]}),
        client.post("/api/compare", headers=alice, json={"mode": "portfolios", "portfolio_ids": [saved["id"]]}),
    ]
    assert all(r.status_code == 503 and r.json()["detail"] == expected for r in responses), [
        (r.status_code, r.text) for r in responses if r.status_code != 503 or r.json()["detail"] != expected]
    assert save_portfolio(alice, "Buy and Hold SPY").status_code == 200
    for response in (
        client.get("/api/today?preview=false", headers=alice),
        client.get("/api/rebalance", headers=alice),
        client.post("/api/backtest", headers=alice, json={"label": "Buy and Hold SPY"}),
    ):
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("key", [None, ""], ids=["absent", "empty"])
def test_unconfigured_registry_explains_saved_fund_and_restores_same_id(accounts, monkeypatch, key):
    alice, _ = accounts
    created = register(alice)
    assert created.status_code == 200, created.text
    model = created.json()["model"]
    assert save_portfolio(alice, model).status_code == 200

    with monkeypatch.context() as missing:
        if key is None:
            missing.delenv("MY_FUNDS_SIGNING_KEY")
        else:
            missing.setenv("MY_FUNDS_SIGNING_KEY", key)

        reads = []

        def unexpected_read(_):
            reads.append(True)
            raise AssertionError("Registry storage should not be queried without a key")

        missing.setattr(fund_registry, "_table", unexpected_read)
        listing = client.get("/api/my-funds", headers=alice)
        assert listing.status_code == 200
        assert listing.json() == {"configured": False, "funds": [], "rejected": 0, "status": "ok"}

        response = client.get("/api/signals", headers=alice, params={"label": model})
        assert response.status_code == 503
        assert response.json() == {"detail": WORDS["registryUnconfigured"]}
        assert client.get("/api/signals", headers=alice, params={"label": "Buy and Hold SPY"}).status_code == 200
        assert reads == []

    restored = client.get("/api/signals", headers=alice, params={"label": model, "as_of": "2026-11-06"})
    assert restored.status_code == 200
    assert restored.json()["current"]["decision"]["selected_asset"] == model
    assert [fund["model"] for fund in client.get("/api/my-funds", headers=alice).json()["funds"]] == [model]
