from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from test_api import client
from server import private_api as private
from haa.rebalance_holdings import empty_account

ID = "00000000-0000-4000-8000-000000000001"
HEADERS = {"Authorization": "Bearer mock-token"}


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://mock.invalid")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "mock-public")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "must-never-be-used")
    def verify(url, key, tokens):
        assert key == "mock-public" and tokens == {"access_token": "mock-token"}
        return {**tokens, "user_id": "mock-user", "email": "test@example.invalid"}
    monkeypatch.setattr(private.sync, "verified_session", verify)


@pytest.mark.parametrize("path,method,body", [
    ("/api/me", "get", None), ("/api/workspace", "get", None),
    ("/api/workspace", "put", {"revision": 0, "payload": {}}),
    ("/api/portfolios", "get", None), ("/api/portfolios", "post", {"payload": {}}),
    (f"/api/portfolios/{ID}?expected_updated_at=mock", "delete", None),
])
def test_missing_auth_never_touches_user_data(path, method, body):
    kwargs = {"json": body} if body is not None else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_get_user_not_unverified_browser_claims(signed_in, monkeypatch):
    assert client.get("/api/me", headers=HEADERS).json()["user_id"] == "mock-user"
    monkeypatch.setattr(private.sync, "verified_session", lambda *a: (_ for _ in ()).throw(ValueError("mock-token private-data")))
    result = client.get("/api/me", headers=HEADERS)
    assert result.status_code == 401 and "mock-token" not in result.text


def test_workspace_cas_preserves_unmigrated_settings_and_has_no_store(signed_in, monkeypatch):
    remote = {"revision": 3, "payload": {"portfolio_name": "Fake", "tax_enabled": True}}
    monkeypatch.setattr(private.sync, "load_workspace", lambda *a: deepcopy(remote))
    save = MagicMock(return_value=4)
    monkeypatch.setattr(private.sync, "save_workspace", save)
    response = client.put("/api/workspace", headers=HEADERS, json={"revision": 3, "payload": {"portfolio_name": "New fake"}})
    assert response.status_code == 200 and response.json()["payload"]["tax_enabled"]
    assert response.headers["cache-control"] == "no-store, private"
    assert save.call_args.args[-2] == {"portfolio_name": "New fake", "tax_enabled": True}
    response = client.put("/api/workspace", headers=HEADERS, json={"revision": 2, "payload": {"portfolio_name": "Old fake"}})
    assert response.status_code == 409 and save.call_count == 1


def test_cas_race_returns_conflict(signed_in, monkeypatch):
    monkeypatch.setattr(private.sync, "load_workspace", lambda *a: {"revision": 1, "payload": {}})
    monkeypatch.setattr(private.sync, "save_workspace", lambda *a: None)
    assert client.put("/api/workspace", headers=HEADERS, json={"revision": 1, "payload": {"portfolio_name": "Fake"}}).status_code == 409


def test_allocation_preference_patch_uses_existing_cas_without_reservations(signed_in,monkeypatch):
    remote={"revision":3,"payload":{"rebalance_portfolio_id":"fake","holdings_account":empty_account()}}
    monkeypatch.setattr(private.sync,"load_workspace",lambda *a:deepcopy(remote))
    save=MagicMock(return_value=4)
    monkeypatch.setattr(private.sync,"save_workspace",save)
    response=client.put("/api/workspace",headers=HEADERS,json={"revision":3,"payload":{"rebalance_allocation_mode":"proportional"}})
    assert response.status_code==200
    assert save.call_args.args[-2]=={**remote["payload"],"rebalance_allocation_mode":"proportional"}
    assert client.put("/api/workspace",headers=HEADERS,json={"revision":3,"payload":{"unspent_by_fund":{"fake":"10"}}}).status_code==422
    assert save.call_count==1


def test_holdings_lost_response_and_retry_do_not_apply_twice(signed_in, monkeypatch):
    remote = {"revision": 1, "payload": {"portfolio_name": "Fake"}}
    account = empty_account()
    account.update(revision=1, cash_ils="100", last_operation_id="fake-operation")
    writes = []
    monkeypatch.setattr(private.sync, "load_workspace", lambda *a: deepcopy(remote))
    def save(*args):
        writes.append(1)
        remote.update(revision=2, payload=deepcopy(args[-2]))
        raise TimeoutError("Response lost")
    monkeypatch.setattr(private.sync, "save_workspace", save)
    body = {"revision": 1, "payload": {"holdings_account": account}}
    first = client.put("/api/workspace", headers=HEADERS, json=body)
    assert first.status_code == 200 and first.json() == remote
    assert client.put("/api/workspace", headers=HEADERS, json=body).json() == remote
    assert len(writes) == 1
    body["payload"]["holdings_account"]["cash_ils"] = "200"
    assert client.put("/api/workspace", headers=HEADERS, json=body).status_code == 409
    assert len(writes) == 1


def portfolio():
    return {"name": "Fake portfolio", "version": 1, "sleeves": [{"id": 1, "weight": 100, "model": "Buy and Hold SPY"}], "total_ils": 100, "ils_per_usd": 4}


def test_portfolio_save_uses_existing_rpc_and_conflict_timestamp(signed_in, monkeypatch):
    save = MagicMock(return_value={"id": ID, "payload": portfolio()})
    monkeypatch.setattr(private.sync, "save_portfolio", save)
    body = {"id": ID, "expected_updated_at": "2026-01-01T00:00:00Z", "is_default": True, "payload": portfolio()}
    assert client.post("/api/portfolios", headers=HEADERS, json=body).status_code == 200
    assert save.call_args.kwargs["is_default"] is True
    assert save.call_args.kwargs["existing_id"] == ID
    save.side_effect = RuntimeError("Portfolio changed on another device")
    assert client.post("/api/portfolios", headers=HEADERS, json=body).status_code == 409
    body.pop("expected_updated_at")
    assert client.post("/api/portfolios", headers=HEADERS, json=body).status_code == 422


def test_portfolio_confirmed_non_100_draft_uses_same_private_save_unchanged(signed_in, monkeypatch):
    value=portfolio(); value['sleeves'][0]['weight']=90
    save=MagicMock(return_value={'id':ID,'payload':value})
    monkeypatch.setattr(private.sync,'save_portfolio',save)
    body={'id':ID,'expected_updated_at':'mock-date','is_default':True,'payload':value}
    assert client.post('/api/portfolios',headers=HEADERS,json=body).status_code==422
    save.assert_not_called()
    response=client.post('/api/portfolios',headers=HEADERS,json={**body,'allow_non_100_weights':True})
    assert response.status_code==200
    assert save.call_args.args[2]['user_id']=='mock-user'
    assert save.call_args.args[3]==value
    assert save.call_args.kwargs=={'is_default':True,'existing_id':ID,'expected_updated_at':'mock-date'}
    assert 'allow_non_100_weights' not in save.call_args.args[3]
    save.side_effect=RuntimeError('Portfolio changed on another device')
    assert client.post('/api/portfolios',headers=HEADERS,json={**body,'allow_non_100_weights':True}).status_code==409


@pytest.mark.parametrize('patch',[{'payload':{**portfolio(),'total_ils':0}}, {'payload':{**portfolio(),'sleeves':[]}}, {'expected_updated_at':None}])
def test_portfolio_draft_confirmation_keeps_other_save_checks(signed_in,monkeypatch,patch):
    save=MagicMock();monkeypatch.setattr(private.sync,'save_portfolio',save)
    body={'id':ID,'expected_updated_at':'mock-date','payload':portfolio(),'allow_non_100_weights':True,**patch}
    assert client.post('/api/portfolios',headers=HEADERS,json=body).status_code==422
    save.assert_not_called()


@pytest.mark.parametrize('rule',[None,{'mode':'unknown'},{'mode':'rvol_cap','sleeve_model':'Missing RVol','cap_percent':15,'target_percent':10}])
def test_portfolio_save_rejects_invalid_transfer_rule_without_writing(signed_in,monkeypatch,rule):
    save=MagicMock();monkeypatch.setattr(private.sync,'save_portfolio',save)
    response=client.post('/api/portfolios',headers=HEADERS,json={'payload':{**portfolio(),'transfer_rule':rule}})
    assert response.status_code==422
    save.assert_not_called()


def test_delete_is_user_and_timestamp_filtered(signed_in, monkeypatch):
    query = MagicMock()
    query.table.return_value = query.delete.return_value = query.eq.return_value = query
    query.execute.return_value = SimpleNamespace(data=[{"id": ID}])
    monkeypatch.setattr(private.sync, "_client", lambda *a: query)
    path = f"/api/portfolios/{ID}?expected_updated_at=mock-date"
    assert client.delete(path, headers=HEADERS).status_code == 200
    assert ("user_id", "mock-user") in [call.args for call in query.eq.call_args_list]
    assert ("updated_at", "mock-date") in [call.args for call in query.eq.call_args_list]
    query.execute.return_value.data = []
    assert client.delete(path, headers=HEADERS).status_code == 409


def test_private_errors_never_echo_submitted_values(signed_in, monkeypatch):
    result = client.put("/api/workspace", headers=HEADERS, json={"revision": "fake-private-value", "payload": {}})
    assert result.status_code == 422 and "fake-private-value" not in result.text
    monkeypatch.setattr(private.sync, "list_portfolios", lambda *a: (_ for _ in ()).throw(ValueError("fake-private-value")))
    result = client.get("/api/portfolios", headers=HEADERS)
    assert result.status_code == 502 and "fake-private-value" not in result.text


def test_actual_auth_helper_uses_get_user_and_user_token_not_metadata(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://mock.invalid")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "mock-public")
    sdk = MagicMock()
    sdk.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id="verified-mock-id", email="test@example.invalid"))
    create = MagicMock(return_value=sdk)
    monkeypatch.setattr(private.sync, "create_client", create)
    response = client.get("/api/me", headers=HEADERS)
    assert response.json()["user_id"] == "verified-mock-id"
    create.assert_called_once_with("https://mock.invalid", "mock-public")
    sdk.auth.get_user.assert_called_once_with("mock-token")
