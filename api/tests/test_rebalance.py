"""Frozen fake accounts only; exact Decimal comparisons and no network."""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4
import pytest

from test_api import client
from test_private_api import signed_in, HEADERS
from server import rebalance as page, private_api as private
from haa.rebalance_holdings import (empty_account, security, make_buy_plan,
    compare_holdings, apply_purchases, fingerprint, rebalance_targets)


@pytest.mark.parametrize('mode',['proportional','biggest_gap_first'])
def test_companion_value_folds_into_anchor_and_only_anchor_is_bought(book,mode):
    remote,instruments,targets,quotes,fx=book
    account=remote['payload']['holdings_account'];anchor=next(iter(targets));legacy='US:GLD'
    targets.clear();targets[anchor]=1.
    account['positions'][legacy]={**instruments[legacy],'units':'20','companion_of':anchor,'minimum_ils':'999999'}
    remote['payload']['rebalance_allocation_mode']=mode
    state=client.get('/api/rebalance',headers=HEADERS).json()
    anchor_row=next(r for r in state['comparison'] if r['id']==anchor)
    legacy_row=next(r for r in state['comparison'] if r['id']==legacy)
    assert anchor_row['Actual %']==1.
    assert legacy_row['Value (₪)']==350 and legacy_row['Target %'] is None
    assert legacy_row['Status']=='Companion' and legacy_row['companion_of']==anchor
    assert state['total_ils']==state['full_total_ils']=='350.0'
    value=post('plan',request(remote,new_money='100')).json()
    assert [(r['id'],r['units']) for r in value['plan']['orders']]==[(anchor,10)]
    quotes[legacy]['fresh']=False
    assert post('plan',request(remote)).status_code==400
    quotes[legacy]={'error':'Missing','fresh':False}
    assert post('plan',request(remote)).status_code==400


@pytest.mark.parametrize('change',['outside','self','chain','target','invalid'])
def test_invalid_companion_configurations_are_rejected(book,change):
    remote,instruments,targets,_,_=book
    account=remote['payload']['holdings_account'];anchor=next(iter(targets));legacy='US:GLD'
    account['positions'][legacy]={**instruments[legacy],'units':'1','companion_of':anchor}
    if change=='outside':account['positions'][legacy]['outside_rebalance']=True
    if change=='self':account['positions'][legacy]['companion_of']=legacy
    if change=='chain':account['positions'][anchor]['companion_of']=next(k for k in targets if k!=anchor)
    if change=='target':targets[legacy]=.1
    if change=='invalid':account['positions'][legacy]['companion_of']='not-a-security'
    assert post('plan',request(remote)).status_code==400


def test_companion_editor_round_trip_uses_existing_workspace_save(book,monkeypatch):
    remote,instruments,targets,_,_=book
    anchor=next(iter(targets));legacy='US:GLD'
    remote['payload']['holdings_account']['positions'][legacy]={**instruments[legacy],'units':'2'}
    state=client.get('/api/rebalance',headers=HEADERS).json()
    next(row for row in state['rows'] if row['Security']==legacy)['Companion of']=anchor
    response=post('editor',request(remote,rows=state['rows'],cash='0',manual_fx=''))
    assert response.status_code==200,response.text
    candidate=response.json()['account']
    assert candidate['positions'][legacy]['companion_of']==anchor
    writes=[]
    monkeypatch.setattr(private.sync,'save_workspace',lambda *args:(writes.append(deepcopy(args[-2])) or 2))
    result=client.put('/api/workspace',headers=HEADERS,json={'revision':1,'payload':{'holdings_account':candidate}})
    assert result.status_code==200,result.text
    assert writes[0]['holdings_account']['positions'][legacy]['companion_of']==anchor


@pytest.mark.parametrize('mode',['proportional','biggest_gap_first'])
@pytest.mark.parametrize('quote_state',['current','stale','missing'])
def test_unmatched_companion_is_exactly_outside_and_reactivates(book,mode,quote_state):
    remote,instruments,targets,quotes,fx=book
    account=remote['payload']['holdings_account'];legacy='US:GLD';anchor=next(iter(targets))
    account['positions'][legacy]={**instruments[legacy],'units':'20','companion_of':anchor}
    remote['payload']['rebalance_allocation_mode']=mode
    targets.pop(anchor) # Simulate selecting a portfolio without its anchor.
    if quote_state=='stale':quotes[legacy]['fresh']=False
    if quote_state=='missing':quotes[legacy]={'error':'Missing','fresh':False}
    response=post('plan',request(remote,new_money='100'))
    assert response.status_code==200,response.text
    value=response.json();state=value['state']
    row=next(r for r in state['comparison'] if r['id']==legacy)
    assert row['Status']=='Outside the rebalance' and row['Target %'] is row['Actual %'] is None
    assert legacy not in state['held_blocked'] and state['total_ils']=='0'
    removed=deepcopy(account);removed['positions'].pop(legacy)
    expected=make_buy_plan(removed,instruments,targets,quotes,1,'100',{},allocation_mode=mode)
    for field in ('orders','leftover_ils','available_ils','instruments'):
        assert value['plan'][field]==expected[field]
    if quote_state!='missing':assert Decimal(state['full_total_ils'])==350
    else:assert state['full_total_ils'] is None
    assert account['positions'][legacy]['companion_of']==anchor
    targets[anchor]=.6
    active=client.get('/api/rebalance',headers=HEADERS).json()
    assert next(r for r in active['comparison'] if r['id']==legacy)['Status']=='Companion'
    if quote_state!='current':assert legacy in active['held_blocked']


def test_unpriced_unheld_anchor_does_not_exclude_its_active_companion_from_partial_plan(book):
    remote,instruments,targets,quotes,fx=book
    account=remote['payload']['holdings_account'];anchor,other=list(targets);legacy='US:GLD'
    account['positions'][legacy]={**instruments[legacy],'units':'20','companion_of':anchor}
    quotes[anchor]={'error':'Missing','fresh':False}
    response=post('plan',request(remote,new_money='100'))
    assert response.status_code==200,response.text
    value=response.json()
    assert Decimal(value['state']['total_ils'])==350
    assert next(r for r in value['state']['comparison'] if r['id']==legacy)['Status']=='Companion'
    assert [(r['id'],r['units']) for r in value['plan']['orders']]==[(other,5)]


@pytest.fixture
def book(monkeypatch, signed_in):
    items = [security("1149038", "TASE"), security("1187079", "TASE"), security("GLD", "US")]
    instruments = {i["id"]: i for i in items}
    account = empty_account()
    account["positions"] = {i["id"]: {**i, "units": "0"} for i in items[:2]}
    remote = {"revision": 1, "payload": {"holdings_account": account, "portfolio_name": "Fake", "rebalance_allocation_mode": "biggest_gap_first"}}
    portfolios = [{"id": "fake-portfolio", "name": "Fake", "payload": {"sleeves": [{"model": "Fake", "weight": 100}]}}]
    targets = {items[0]["id"]: .6, items[1]["id"]: .4}
    quotes = {i["id"]: {"price": p, "fresh": True, "as_of": "2026-10-15", "source": "Mock raw", "field": "Unadjusted close", "fetched_at": "frozen"}
              for i, p in zip(items, ("10", "20", "5"))}
    fx = {"price": "3.5", "fresh": True, "as_of": "2026-10-15"}
    monkeypatch.setattr(private.sync, "load_workspace", lambda *a: deepcopy(remote))
    monkeypatch.setattr(private.sync, "list_portfolios", lambda *a: deepcopy(portfolios))
    monkeypatch.setattr(page, "known_instruments", lambda: (deepcopy(instruments), ("GLD",)))
    monkeypatch.setattr(page.market, "unit_quote", lambda instrument, position: deepcopy(quotes.get(instrument["id"], {"error": "Missing", "fresh": False})))
    monkeypatch.setattr(page.market, "fx_quote", lambda account: deepcopy(fx))
    def targets_for(workspace, rows, portfolio_id, current):
        return portfolios[0], instruments, [], targets, [], "Mock source settings"
    monkeypatch.setattr(page, "targets_for", targets_for)
    return remote, instruments, targets, quotes, fx


def post(path, body):
    return client.post("/api/rebalance/"+path, headers=HEADERS, json=body)


def request(remote, **kwargs):
    return {"portfolio_id": "fake-portfolio", "account_hash": fingerprint(remote["payload"]["holdings_account"]), "new_money": "100", **kwargs}


@pytest.mark.parametrize("scenario", ["empty", "overweight", "small", "minimum", "decimal", "usd", "outside", "default-off", "skipped"])
def test_plan_decimal_exact_against_direct_allocator(book, scenario):
    remote, instruments, targets, quotes, fx = book
    account = remote["payload"]["holdings_account"]
    first, second = list(targets)
    deposit = "1000"
    if scenario == "overweight": account["positions"][first]["units"] = "100"
    if scenario == "small":
        account["positions"][first]["units"] = "7"
        deposit = "11"
    if scenario == "minimum":
        account["positions"][first]["minimum_ils"] = "300"
        deposit = "25"
    if scenario == "decimal":
        quotes[first]["price"], quotes[second]["price"] = "1.123456", "2.765432"
        deposit = "12.34"
    if scenario == "usd":
        targets.clear(); targets["US:GLD"] = 1.
    if scenario == "outside":
        account["positions"][first].update(units="999", outside_rebalance=True)
    if scenario == "default-off":
        for p in account["positions"].values(): p["outside_rebalance"] = False
    if scenario == "skipped":
        quotes[second].update(fresh=False)
    result = post("plan", request(remote, new_money=deposit))
    assert result.status_code == 200, result.text
    body = result.json(); state, actual = body["state"], body["plan"]
    expected_targets = {k: w for k, w in rebalance_targets(account, targets).items() if quotes[k].get("fresh")}
    direct = make_buy_plan(account, instruments, expected_targets, quotes, state["rebalance_fx"]["price"], deposit, state["context"], allocation_mode="biggest_gap_first")
    for key in ("orders", "leftover_ils", "available_ils", "account_hash", "context_hash", "instruments"):
        assert actual[key] == direct[key]
    rows, _, total = compare_holdings(account, instruments, targets, quotes, state["rebalance_fx"]["price"])
    assert Decimal(state["total_ils"]) == total
    assert [(r["id"], r["Status"]) for r in rows] == [(r["id"], r["Status"]) for r in state["comparison"]]
    assert result.headers["cache-control"] == "no-store, private"
    if scenario == "skipped":
        assert state["partial"] and state["eligible"][first] == .6


def test_outside_removal_rescaling_and_missing_outside_fx(book):
    remote, instruments, targets, quotes, fx = book
    account = remote["payload"]["holdings_account"]
    account["positions"]["US:GLD"] = {**instruments["US:GLD"], "units": "90", "outside_rebalance": True}
    targets.update({k: v/2 for k, v in targets.items()}); targets["US:GLD"] = .5
    quotes["US:GLD"] = {"error": "Missing", "fresh": False}; fx.update(error="Missing", fresh=False)
    result = post("plan", request(remote)).json()
    assert result["state"]["full_total_ils"] is None
    assert result["state"]["ready"]
    assert next(r for r in result["state"]["comparison"] if r["id"] == "US:GLD")["Status"] == "Outside the rebalance"
    removed = deepcopy(account); del removed["positions"]["US:GLD"]
    direct = make_buy_plan(removed, instruments, rebalance_targets(account, targets), quotes, 1, "100", {}, allocation_mode="biggest_gap_first")
    assert result["plan"]["orders"] == direct["orders"]
    assert result["plan"]["leftover_ils"] == direct["leftover_ils"]


@pytest.mark.parametrize("missing", [False, True])
def test_held_stale_or_missing_blocks_but_outside_does_not(book, missing):
    remote, _, _, quotes, _ = book
    key = next(iter(remote["payload"]["holdings_account"]["positions"]))
    remote["payload"]["holdings_account"]["positions"][key]["units"] = "1"
    quotes[key] = {"error": "Missing", "fresh": False} if missing else {"price": "10", "fresh": False}
    assert post("plan", request(remote)).status_code == 400
    remote["payload"]["holdings_account"]["positions"][key]["outside_rebalance"] = True
    assert post("plan", request(remote)).status_code == 200


def test_all_outside_no_orders_and_zero_legacy_equivalence(book):
    remote, instruments, targets, quotes, _ = book
    account = remote["payload"]["holdings_account"]
    for p in account["positions"].values(): p["outside_rebalance"] = True
    state = client.get("/api/rebalance", headers=HEADERS).json()
    assert not state["ready"] and not state["targets"]
    assert make_buy_plan(account, instruments, targets, quotes, 1, "100", {}, allocation_mode="biggest_gap_first")["orders"] == []


def test_record_exact_actual_paid_idempotence_and_no_write(book, monkeypatch):
    remote, _, _, _, _ = book
    write = lambda *a: pytest.fail("Recording endpoint must not write")
    monkeypatch.setattr(private.sync, "save_workspace", write)
    result = post("plan", request(remote)).json()
    plan = result["plan"]
    confirmations = [{"id": plan["orders"][0]["id"], "units": "2", "paid_ils": "23.5"}]
    expected = apply_purchases(remote["payload"]["holdings_account"], plan, confirmations, result["state"]["context"])
    body = request(remote, plan=plan, confirmations=confirmations, acknowledge=True)
    actual = post("record", body)
    assert actual.status_code == 200, actual.text
    candidate = actual.json()["account"]; candidate.pop("updated_at")
    assert candidate == expected
    remote["payload"]["holdings_account"] = deepcopy(expected)
    assert post("record", body).json()["account"] == expected


@pytest.mark.parametrize("bad", ["duplicate", "overspend", "too-many", "fractional", "stale", "changed-quote", "forged", "no-ack"])
def test_reject_bad_or_stale_confirmations(book, bad):
    remote, _, _, quotes, _ = book
    result = post("plan", request(remote)).json(); plan = result["plan"]
    row = {"id": plan["orders"][0]["id"], "units": "1", "paid_ils": "10"}
    confirmations = [row]
    if bad == "duplicate": confirmations.append(row)
    if bad == "overspend": row["paid_ils"] = "1000"
    if bad == "too-many": row["units"] = "9999"
    if bad == "fractional": row["units"] = "0.5"
    if bad == "stale": remote["payload"]["holdings_account"]["cash_ils"] = "1"
    if bad == "changed-quote": quotes[row["id"]]["price"] = "11"
    if bad == "forged": plan["orders"][0]["units"] = 999
    assert post("record", request(remote, plan=plan, confirmations=confirmations, acknowledge=bad != "no-ack")).status_code in (400, 409)


def test_editor_conversion_whole_units_manual_date_cash_and_precision(book, monkeypatch):
    remote, _, _, _, _ = book
    state = client.get("/api/rebalance", headers=HEADERS).json()
    body = request(remote, rows=state["rows"], cash="0", manual_fx="", manual_fx_date=None)
    body["rows"][0].update({"Enter as": "Value", "Value (₪ / $)": "25.99", "Outside the rebalance": True})
    result = post("editor", body)
    assert result.status_code == 200, result.text
    candidate = result.json()["account"]
    assert candidate["positions"][body["rows"][0]["Security"]]["units"] == "2"
    assert candidate["positions"][body["rows"][0]["Security"]]["outside_rebalance"] is True
    assert result.json()["preview"][0]["Units to save"] == "2.00"
    assert candidate["cash_ils"] == "0"  # No value-to-unit remainder credited.
    body["cash"] = ""
    assert "enter 0" in post("editor", body).json()["detail"]
    body["cash"] = "0"; body["rows"][0]["Manual price per unit"] = "1"
    assert "date" in post("editor", body).json()["errors"][0]
    body["rows"][0].update({"Manual price per unit": None, "Enter as": "Units", "Units": "1.5", "Units edited": True})
    assert "whole" in post("editor", body).json()["errors"][0]


def test_editor_noop_returns_exact_saved_account(book):
    remote, _, _, _, _ = book
    account = remote["payload"]["holdings_account"]
    account["last_operation_id"] = str(uuid4())
    rows = client.get("/api/rebalance", headers=HEADERS).json()["rows"]
    result = post("editor", request(remote, rows=rows, cash="0"))
    assert result.json()["account"] == account


@pytest.mark.parametrize("path,method,body", [
    ("", "get", None), ("/refresh", "post", {}), ("/security", "post", {}),
    ("/editor", "post", {"rows": [], "cash": "0"}), ("/plan", "post", {}),
    ("/record", "post", {"plan": {}, "confirmations": []}),
])
@pytest.mark.parametrize("bad_token", [False, True])
def test_every_route_auth(book, monkeypatch, path, method, body, bad_token):
    if bad_token:
        monkeypatch.setattr(private.sync, "verified_session", lambda *a: (_ for _ in ()).throw(ValueError("bad")))
    response = getattr(client, method)("/api/rebalance"+path, headers=HEADERS if bad_token else {}, **({"json": body} if body is not None else {}))
    assert response.status_code == 401


def test_workspace_revision_operation_whitelist_and_lost_response(book, monkeypatch):
    remote, _, _, _, _ = book
    account = deepcopy(remote["payload"]["holdings_account"])
    account.update(revision=1, last_operation_id=str(uuid4()), cash_ils="123")
    writes = []
    def save(*args):
        writes.append(1); remote.update(revision=remote["revision"]+1, payload=deepcopy(args[-2]))
        raise TimeoutError("Lost response")
    monkeypatch.setattr(private.sync, "save_workspace", save)
    body = {"revision": remote["revision"], "payload": {"holdings_account": account}}
    response = client.put("/api/workspace", headers=HEADERS, json=body)
    assert response.status_code == 200
    assert client.put("/api/workspace", headers=HEADERS, json=body).json() == remote
    assert len(writes) == 1
    body["payload"]["holdings_account"]["cash_ils"] = "124"
    assert client.put("/api/workspace", headers=HEADERS, json=body).status_code == 409
    body["payload"]["holdings_account"].update(revision=3, last_operation_id=str(uuid4()))
    assert client.put("/api/workspace", headers=HEADERS, json=body).status_code == 409
    body["payload"]["holdings_account"].update(revision=2, prices={"fake": 999})
    assert client.put("/api/workspace", headers=HEADERS, json=body).status_code == 422
    del body["payload"]["holdings_account"]["prices"]
    assert client.put("/api/workspace", headers=HEADERS, json=body).status_code == 409  # stale workspace revision
    assert len(writes) == 1


def test_actions_accept_no_user_id_and_do_not_echo_amounts(book):
    for path in ("refresh", "plan", "security"):
        assert post(path, {"user_id": "other", "new_money": "1234567"}).status_code == 400
    response = post("plan", request(book[0], new_money="-1234567"))
    assert response.status_code == 400 and "1234567" not in response.text


def test_exact_stored_fractional_us_units_survive_two_decimal_display(book):
    remote, instruments, targets, _, _ = book
    account = remote["payload"]["holdings_account"]
    account["positions"]["US:GLD"] = {**instruments["US:GLD"], "units": "1.123456789"}
    account["last_operation_id"] = str(uuid4())
    state = client.get("/api/rebalance", headers=HEADERS).json()
    assert next(r for r in state["rows"] if r["Security"] == "US:GLD")["Units"] == "1.12"
    result = post("editor", request(remote, rows=state["rows"], cash=account["cash_ils"]))
    assert result.json()["account"] == account


def test_fx_freshness_blocks_us_sizing(book):
    remote, _, targets, _, fx = book
    targets.clear(); targets["US:GLD"] = 1.
    fx["fresh"] = False
    assert post("plan", request(remote)).status_code == 400


def test_editor_unique_rows_limit_remove_and_failed_save_keeps_remote(book):
    remote, _, _, _, _ = book
    rows = client.get("/api/rebalance", headers=HEADERS).json()["rows"]
    original = deepcopy(remote)
    assert post("editor", request(remote, rows=rows+rows, cash="0")).status_code == 400
    assert post("editor", request(remote, rows=rows*101, cash="0")).status_code == 400
    rows[0]["Remove"] = True
    result = post("editor", request(remote, rows=rows, cash="0")).json()
    assert rows[0]["Security"] not in result["account"]["positions"]
    assert remote == original  # Preparation cannot save, even when valid.


def test_workspace_source_settings_or_explicit_defaults_without_silent_fallback(monkeypatch):
    instruments, yahoo = page.known_instruments()
    account = empty_account()
    portfolios = [{"id": "fake", "name": "Fake", "payload": {"sleeves": [{"model": "Buy and Hold Gold GLD", "weight": 100}]}}]
    calls = []
    def signals(labels, tickers, replacements):
        calls.append(dict(tickers)); assert replacements == {}
        return ([{"name": labels[0], "currency": "USD", "target_weights": {"GLD": 1.}, "signal_date": "2026-09-30", "source_notes": []}], [])
    monkeypatch.setattr(page.market, "load_portfolio_signals", signals)
    workspace = {"payload": {}}
    result = page.targets_for(workspace, portfolios, "fake", account)
    assert result[3] == {"US:GLD": 1.} and "Default ticker" in result[5]
    mapping = page.data.default_ticker_map(yahoo); mapping["GLD"] = "MOCK-PROXY"
    workspace["payload"]["ticker_text"] = "\n".join(f"{a}={b}" for a, b in mapping.items())
    result = page.targets_for(workspace, portfolios, "fake", account)
    assert not result[4] and calls[-1]["GLD"] == "MOCK-PROXY" and "Workspace ticker" in result[5]
    workspace["payload"]["ticker_text"] = "bad"
    result = page.targets_for(workspace, portfolios, "fake", account)
    assert result[4] and not result[3] and len(calls) == 2


def test_absent_allocation_mode_defaults_proportional(book):
    remote,*_=book
    del remote["payload"]["rebalance_allocation_mode"]
    state=client.get("/api/rebalance",headers=HEADERS).json()
    assert state["allocation_mode"]=="proportional"
    assert state["context"]["allocation_mode"]=="proportional"
    assert "rebalance_allocation_mode" not in remote["payload"]
    result=post("plan",request(remote)).json()
    assert result["plan"]["unspent_by_fund"]


@pytest.mark.parametrize("invalid",["invalid",None,False,[],{}])
def test_allocation_mode_rejected_on_save_and_load_with_identical_error(book,invalid):
    from haa.allocation_mode import ALLOCATION_MODE_ERROR
    remote,*_=book
    saved=client.put("/api/workspace",headers=HEADERS,json={"revision":1,"payload":{"rebalance_allocation_mode":invalid}})
    assert saved.status_code==422 and saved.json()["detail"]==ALLOCATION_MODE_ERROR
    remote["payload"]["rebalance_allocation_mode"]=invalid
    loaded=client.get("/api/rebalance",headers=HEADERS)
    assert loaded.status_code==400 and loaded.json()["detail"]==ALLOCATION_MODE_ERROR
    assert post("plan",request(remote)).json()["detail"]==ALLOCATION_MODE_ERROR


def test_mode_preference_save_preserves_account_and_other_preferences(book,monkeypatch):
    remote,*_=book
    before=deepcopy(remote)
    writes=[]
    def save(*args):
        writes.append(deepcopy(args[-2]));return 2
    monkeypatch.setattr(private.sync,"save_workspace",save)
    result=client.put("/api/workspace",headers=HEADERS,json={"revision":1,"payload":{"rebalance_allocation_mode":"proportional"}})
    assert result.status_code==200
    assert writes==[{**before["payload"],"rebalance_allocation_mode":"proportional"}]
    assert remote==before
    assert not any("unspent" in k for k in writes[0])


def test_mode_change_invalidates_plan_context_and_recording(book):
    remote,*_=book
    original=post("plan",request(remote)).json()
    remote["payload"]["rebalance_allocation_mode"]="proportional"
    changed=post("plan",request(remote)).json()
    assert original["plan"]["context_hash"]!=changed["plan"]["context_hash"]
    with pytest.raises(ValueError,match="changed"):
        apply_purchases(remote["payload"]["holdings_account"],original["plan"],[],changed["state"]["context"])
    result=post("record",request(remote,plan=original["plan"],confirmations=[],acknowledge=True))
    assert result.status_code==409
