"""Offline original-engine parity; synthetic prices and fake saved records only."""
import ast
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from test_api import client, module, ROOT
from test_private_api import signed_in, HEADERS
from server import compare as page, compare_presentation as view, cache
from server.signals_wire import clean
from haa.comparison import ModelInput, compare_models
from haa.portfolio_comparison import compare_portfolios
from haa.portfolio_signals import monthly_strategy_input
from haa.metrics import performance_metrics, annual_returns
from haa.backtest_options import result_metrics
from haa.market_sessions import us_equity_sessions

MONTHLY = ["HAA-Simple", "Inflation Compass Standard", "HAA Classic (No QQQ)"]
RVOL = "A-RVol Shifter V3 Cash-Only"


def prices_for(labels, start="2012-01-03", end="2024-06-28"):
    assets = tuple(dict.fromkeys(a for label in labels for a in (*getattr(page.definition(label).model_class,"data_assets",page.base.ASSETS), "SPY")))
    dates = us_equity_sessions(start, end)
    x = np.arange(len(dates))
    prices = pd.DataFrame({a: (2+.05*np.sin(x/80) if a == "T5YIE" else 100*np.exp(.00015*x+.09*np.sin(x/(30+i)))) for i,a in enumerate(assets)},index=dates)
    metadata = pd.DataFrame({"source":"Mock adjusted observations","identifier":list(assets),"price_field":"Mock Adj Close"},index=pd.Index(assets,name="asset"))
    return prices, metadata


def install(monkeypatch, labels):
    prices, metadata = prices_for(labels)
    calls = []
    def loader(descriptor, *, daily_bars=False):
        assets = tuple(dict.fromkeys((*descriptor.model_class().data_assets, descriptor.model_class().benchmark_asset)))
        calls.append((assets,daily_bars))
        own = prices.loc[:,assets]
        result = (own,metadata.loc[list(assets)],[])
        return (*result, own*.999) if daily_bars else result
    monkeypatch.setattr(page.signals,"load_inputs",loader)
    return prices, metadata, calls


def model_inputs(labels, prices, portfolio=False):
    result = {}
    for label in labels:
        d = page.definition(label); strategy = d.model_class()
        own=getattr(strategy,"data_assets",page.base.ASSETS)
        assets = tuple(dict.fromkeys((*own,"SPY"))) if portfolio else tuple(dict.fromkeys((*own,getattr(strategy,"benchmark_asset","SPY"))))
        daily = prices.loc[:,assets]
        market = tuple(dict.fromkeys((*getattr(strategy,"market_data_assets",assets),"SPY"))) if portfolio else getattr(strategy,"market_data_assets",assets)
        monthly, decision_monthly = monthly_strategy_input(daily,market) if portfolio else (page.base.data.to_month_end(daily.loc[:,list(market)]),None)
        decision_input = daily if getattr(strategy,"uses_daily_signals",False) else decision_monthly if portfolio else monthly
        decisions = strategy.decisions(decision_input)
        result[label] = ModelInput(label,decisions,monthly,daily,"SPY" if portfolio else getattr(strategy,"benchmark_asset","SPY"),prices*.999 if portfolio else None,d.execution_currency)
    return result


def saved(identifier, labels, weights):
    return {"id":identifier,"is_default":True,"payload":{"version":1,"name":"FAKE-PRIVATE-NAME-"+identifier,"total_ils":12345,"ils_per_usd":3.14159,
        "sleeves":[{"id":800+i,"model":label,"weight":weight} for i,(label,weight) in enumerate(zip(labels,weights))]}}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(page,"RESULTS",cache.ResultCache())
    monkeypatch.setattr(cache,"cache_client",Mock(side_effect=RuntimeError("Mock cache unavailable")))
    monkeypatch.setattr(module.private_api.sync,"list_portfolios",lambda *a:[])
    for name in ("save_portfolio","delete_portfolio","save_workspace"):
        monkeypatch.setattr(module.private_api.sync,name,Mock(side_effect=AssertionError("Compare must never write saved data")))


def post(body):
    response=client.post("/api/compare",headers=HEADERS,json=body)
    assert response.status_code==200,response.text
    assert response.headers["cache-control"]=="no-store, private" and len(response.content)<3_000_000
    return response.json()


def get_csv(value,kind):
    response=client.get("/api/compare/download",headers=HEADERS,params={"key":value["cache"]["key"],"kind":kind})
    assert response.status_code==200,response.text
    return response.content


@pytest.mark.parametrize("taxed",[False,True])
@pytest.mark.parametrize("narrow",[False,True])
def test_models_direct_engine_parity_tax_cost_window_and_audits(signed_in,monkeypatch,taxed,narrow):
    prices,_,calls=install(monkeypatch,MONTHLY)
    inputs=model_inputs(sorted(MONTHLY,key=str.casefold),prices)
    lower=max(page.base.data.common_monthly_period(m.monthly_prices)[0] for m in inputs.values())
    upper=min(page.base.data.common_monthly_period(m.monthly_prices)[1] for m in inputs.values())
    start=pd.Timestamp("2017-01-31") if narrow else lower
    direct=compare_models(inputs,10000,.0005,taxed,.25,start,upper)
    spy=Mock(wraps=page.compare_models);monkeypatch.setattr(page,"compare_models",spy)
    value=post({"models":MONTHLY,"initial":10000,"fee_pct":.05,"tax_enabled":taxed,"start":str(start.date()),"end":str(upper.date())})
    assert spy.call_count==1 and len(calls)==1 and not calls[0][1]
    assert value["window"]["periods"]==len(direct.common_index)
    assert value["coverage"]==clean(view.preview(direct.available_periods))
    summary=value["tables"]["summary_pre"]["rows"]
    for name,r in direct.results.items():
        for metric,expected in performance_metrics(r.monthly.pre_tax_value,10000).items():
            actual=next(row[name] for row in summary if row["metric"]==metric)
            assert actual==pytest.approx(expected,abs=1e-9,nan_ok=True) if pd.notna(expected) else actual is None
        years=len(direct.common_index)/12
        assert next(row[name] for row in summary if row["metric"]=="Annual turnover")==pytest.approx((r.monthly.turnover.sum() if "turnover" in r.monthly else r.monthly.allocation_change.sum())/years)
        assert next(row[name] for row in summary if row["metric"]=="Allocation changes")==int(r.monthly.allocation_change.sum())
        assert next(row[name] for row in summary if row["metric"]=="Average changes/year")==pytest.approx(r.monthly.allocation_change.sum()/years)
        assert get_csv(value,"audit:"+name)==r.audit.to_csv().encode()
        item=next(d for d in value["downloads"] if d["kind"]=="audit:"+name)
        assert item["filename"]==name.lower().replace(" ","_").replace("(","").replace(")","")+"_comparison_audit.csv"
        latest=r.monthly.iloc[-1];weights=latest.get("target_weights")
        expected=", ".join(f"{a} {w:.0%}" for a,w in weights.items()) if isinstance(weights,dict) else latest.selected_asset
        allocation_row=next(row for row in value["tables"]["allocation"]["rows"] if row["model"]==name)
        assert allocation_row==clean({"model":name,"signal_date":latest.signal_date,"regime":latest.regime,"target allocation":expected})
        if taxed:
            after=value["tables"]["summary_after"]["rows"]
            for metric,expected in performance_metrics(r.monthly.after_tax_value,10000).items():
                actual=next(row[name] for row in after if row["metric"]==metric)
                assert actual==pytest.approx(expected,abs=1e-9) if pd.notna(expected) else actual is None
    pre_curves=pd.DataFrame({name:r.monthly.pre_tax_value for name,r in direct.results.items()})
    pre_curves["SPY buy-and-hold"]=next(iter(direct.results.values())).monthly.benchmark_value
    assert value["charts"]["value_pre"]==view.plot(pre_curves)
    assert value["charts"]["drawdown"]==view.plot(pre_curves.div(pre_curves.cummax()).sub(1))
    if taxed:
        after_curves=pd.DataFrame({name:r.monthly.after_tax_value for name,r in direct.results.items()})
        assert value["charts"]["value_after"]==view.plot(after_curves)
    for taxed_run in (False,True) if taxed else (False,):
        suffix="after" if taxed_run else "pre";column="after_tax_monthly_return" if taxed_run else "pre_tax_monthly_return"
        returns=pd.DataFrame({name:r.monthly[column] for name,r in direct.results.items()})
        if not taxed_run:returns["SPY buy-and-hold"]=next(iter(direct.results.values())).monthly.benchmark_monthly_return
        assert get_csv(value,"after-tax-monthly-returns" if taxed_run else "monthly-returns")==returns.to_csv().encode()
        assert value["tables"]["monthly_"+suffix]==clean(view.preview(returns,percentages=True))
        annual=pd.DataFrame({name:annual_returns(returns[name]) for name in returns})
        assert value["tables"]["annual_"+suffix]==clean(view.preview(annual,percentages=True))
    assert value["tables"]["summary_pre"]["display_rows"]
    if not taxed:assert "summary_after" not in value["tables"]


@pytest.mark.parametrize("method,taxed",[("monthly",False),("monthly",True),("daily",True)])
def test_portfolio_parity_and_no_private_cache_or_writes(signed_in,monkeypatch,method,taxed):
    labels=["Century Momentum","HAA-Simple",RVOL] if method=="daily" else MONTHLY
    prices,_,calls=install(monkeypatch,labels)
    records=[saved("FAKE-ID-A",labels[:2],[60,40]),saved("FAKE-ID-B",labels,[40,30,30])]
    original=deepcopy(records)
    monkeypatch.setattr(module.private_api.sync,"list_portfolios",lambda *a:deepcopy(records))
    templates=model_inputs(labels,prices,portfolio=True)
    portfolios={}
    for i,record in enumerate(records,1):
        sleeves={}
        for j,s in enumerate(record["payload"]["sleeves"],1):
            key=f"{s['model']} ({j})";sleeves[key]=(s["weight"]/100,replace(templates[s["model"]],name=key))
        portfolios[f"Portfolio {i}"]=sleeves
    preliminary=compare_portfolios(portfolios,10000,.0005,taxed,.25,drift=method=="daily")
    direct=compare_portfolios(portfolios,10000,.0005,taxed,.25,preliminary.common_index[0],preliminary.common_index[-1],drift=method=="daily")
    spy=Mock(wraps=page.compare_portfolios);monkeypatch.setattr(page,"compare_portfolios",spy)
    cache_spy=Mock(wraps=page.RESULTS.run);monkeypatch.setattr(page.RESULTS,"run",cache_spy)
    body={"mode":"portfolios","portfolio_ids":[r["id"] for r in records],"initial":10000,"fee_pct":.05,"tax_enabled":taxed,"method":method}
    value=post(body)
    assert spy.call_count==2 and len(calls)==1 and calls[0][1]==(method=="daily")
    suffix="after" if taxed else "pre";column="after_tax_value" if taxed else "pre_tax_value"
    summary=pd.DataFrame({name:result_metrics(r,column,10000) for name,r in direct.results.items()})
    first=next(iter(direct.results.values()));summary["SPY buy-and-hold"]=result_metrics(first,"benchmark_value",10000)
    observed=first.daily if first.daily is not None else first.monthly
    summary.loc["Tested from (first observation)"]=observed.index.min().strftime("%Y-%m-%d")
    summary.loc["Tested through (last observation)"]=observed.index.max().strftime("%Y-%m-%d")
    assert value["tables"]["summary_"+suffix]==clean(view.preview(summary.rename_axis("metric"),summary=True))
    returns=pd.DataFrame({name:r.monthly["after_tax_monthly_return" if taxed else "pre_tax_monthly_return"] for name,r in direct.results.items()})
    returns["SPY buy-and-hold"]=first.monthly.benchmark_monthly_return
    assert get_csv(value,"portfolio-returns")==returns.to_csv().encode()
    curves=pd.DataFrame({name:(r.daily if method=="daily" else r.monthly)[column] for name,r in direct.results.items()})
    curves["SPY buy-and-hold"]=(first.daily if method=="daily" else first.monthly).benchmark_value
    assert value["charts"]["drawdown"]==view.plot(curves.div(curves.cummax().clip(lower=10000)).sub(1))
    again=post(body)
    assert spy.call_count==2 and again["cache"]["hit"]=="memory" and again["timing"]["engine_seconds"]==0
    envelope=json.dumps({k:v for k,v in cache_spy.call_args.kwargs.items() if k!="compute"})+json.dumps(list(page.RESULTS.warm.values()))
    for marker in ("FAKE-ID", "FAKE-PRIVATE", "mock-user", "mock-token", "3.14159", "12345", "portfolio_ids", "is_default"):
        assert marker not in envelope
    assert records==original


def test_options_no_prices_engines_or_mutations_and_sorted_defaults(signed_in,monkeypatch):
    records=[saved("FAKE-ID",["HAA-Simple"],[100])]
    monkeypatch.setattr(module.private_api.sync,"list_portfolios",lambda *a:records)
    monkeypatch.setattr(page,"load",Mock(side_effect=AssertionError("Options must not load prices")))
    monkeypatch.setattr(page,"compare_models",Mock(side_effect=AssertionError("Options must not run")))
    response=client.get("/api/compare/options",headers=HEADERS)
    assert response.status_code==200 and response.headers["cache-control"]=="no-store, private"
    value=response.json();labels=[m["label"] for m in value["models"]]
    assert labels==sorted(labels,key=str.casefold) and value["defaults"]["models"]==labels[:2]
    assert value["defaults"]["tax_enabled"] is False and value["defaults"]["initial"]==100000
    assert value["portfolios"]==[{"id":"FAKE-ID","name":"FAKE-PRIVATE-NAME-FAKE-ID"}]


@pytest.mark.parametrize("mode",["models","portfolios"])
def test_selection_gates_no_prices(signed_in,monkeypatch,mode):
    monkeypatch.setattr(page,"load",Mock(side_effect=AssertionError("No load for selection gate")))
    value=post({"mode":mode})
    assert value=={"gate":"selection","reason":page.WORDS["modelsGate" if mode=="models" else "portfoliosGate"]}


@pytest.mark.parametrize("labels,expected",[
    (["HAA-Simple","Buy and Hold Gold Israel"],"Compare only models with the same buy-and-hold benchmark. The selected models use different benchmark assets or currencies."),
    (["HAA-Simple",RVOL],"Daily-execution models currently support single-strategy Backtest only; monthly Compare periods are not equivalent.")])
def test_model_refusals(signed_in,monkeypatch,labels,expected):
    install(monkeypatch,labels)
    response=client.post("/api/compare",headers=HEADERS,json={"models":labels})
    assert response.status_code==400 and response.json()["detail"]==expected and not page.RESULTS.warm


@pytest.mark.parametrize("flag,expected",[("single_strategy_only","Daily supplied proxies are single-strategy only; use their built-in benchmark comparison."),("execution_frequency","Daily-execution models currently support single-strategy Backtest only; monthly Compare periods are not equivalent.")])
def test_original_engine_refusal_attributes_are_not_hidden(signed_in,monkeypatch,flag,expected):
    prices,_=prices_for(MONTHLY[:2]);models=model_inputs(MONTHLY[:2],prices)
    next(iter(models.values())).decisions.attrs[flag]="daily" if flag=="execution_frequency" else True
    monthly=next(iter(models.values())).monthly_prices
    loaded={"inputs":models,"bounds":tuple(d.date() for d in page.base.data.common_monthly_period(monthly))}
    with pytest.raises(ValueError,match=expected.replace(".",r"\.")):page.calculate(page.Inputs(models=MONTHLY[:2]),loaded)


@pytest.mark.parametrize("change,expected",[("currency","Portfolio comparisons currently require USD sleeves; no FX conversion is assumed."),("benchmark","All compared portfolios must share the same benchmark."),("rvol","A-RVol comparisons require initial weights / daily valuation, not monthly resets.")])
def test_portfolio_engine_refusals(change,expected):
    prices,_=prices_for(["HAA-Simple"]);model=model_inputs(["HAA-Simple"],prices,True)["HAA-Simple"]
    other=replace(model,execution_currency="ILS") if change=="currency" else replace(model,benchmark_asset="ACWI") if change=="benchmark" else replace(model,decisions=model.decisions.copy())
    if change=="rvol":other.decisions.attrs["execution_frequency"]="daily"
    with pytest.raises(ValueError,match=expected.replace(".",r"\.")):
        page.calculate(page.Inputs(mode="portfolios"),{"inputs":{"Portfolio 1":{"A":(1,model)},"Portfolio 2":{"B":(1,other)}}})


def test_cache_revisions_settings_code_failures_and_oversize(signed_in,monkeypatch):
    prices,_,_=install(monkeypatch,MONTHLY[:2]);spy=Mock(wraps=page.compare_models);monkeypatch.setattr(page,"compare_models",spy)
    body={"models":MONTHLY[:2]};one=post(body);two=post(body)
    assert spy.call_count==1 and two["timing"]["engine_seconds"]==0
    prices.iloc[-30,0]*=1.0001;three=post(body);assert three["cache"]["key"]!=one["cache"]["key"]
    four=post({**body,"fee_pct":.1});assert four["cache"]["key"]!=three["cache"]["key"]
    monkeypatch.setattr(module,"_engine_code_version",lambda:"Mock code revision")
    five=post(body);assert five["cache"]["key"]!=three["cache"]["key"]
    monkeypatch.setattr(page,"RESULTS",cache.ResultCache())
    original=view.present
    def oversize(*a):
        bundle=original(*a);bundle["public"]["oversize"]="X"*3_000_000;return bundle
    monkeypatch.setattr(view,"present",oversize)
    response=client.post("/api/compare",headers=HEADERS,json=body)
    assert response.status_code==400 and not page.RESULTS.warm
    monkeypatch.setattr(page,"compare_models",Mock(side_effect=ValueError("Mock engine failure")))
    response=client.post("/api/compare",headers=HEADERS,json=body)
    assert response.status_code==400 and not page.RESULTS.warm


@pytest.mark.parametrize("body",[{"models":["unknown"]},{"mode":"portfolios","portfolio_ids":["FAKE-UNKNOWN"]},{"user_id":"FAKE-PRIVATE"},{"initial":0},{"fee_pct":11},{"tax_rate":101},{"mode":"unknown"}])
def test_invalid_input_without_echo(signed_in,body):
    response=client.post("/api/compare",headers=HEADERS,json=body)
    assert response.status_code==400 and "FAKE-PRIVATE" not in response.text and not page.RESULTS.warm


@pytest.mark.parametrize("mode,expected",[("models","Comparison start must not be after comparison end."),("portfolios","Start must not be after end.")])
def test_exact_date_order(mode,expected):
    with pytest.raises(HTTPException) as exc:page.calculate(page.Inputs(mode=mode,start="2023-01-01",end="2022-01-01"),{"inputs":{}})
    assert exc.value.detail==expected


def test_out_of_range_missing_download_and_auth_methods(signed_in,monkeypatch):
    install(monkeypatch,MONTHLY[:2])
    response=client.post("/api/compare",headers=HEADERS,json={"models":MONTHLY[:2],"start":"1900-01-01"})
    assert response.status_code==400 and response.json()["detail"]==page.WORDS["dateRange"]
    for path,method in [("/api/compare/options","get"),("/api/compare","post"),("/api/compare/download?key=bad&kind=monthly-returns","get")]:
        assert getattr(client,method)(path).status_code==401
    assert client.get("/api/compare",headers=HEADERS).status_code==405
    assert client.post("/api/compare/options",headers=HEADERS).status_code==405
    response=client.get("/api/compare/download",headers=HEADERS,params={"key":"0"*64,"kind":"monthly-returns"})
    assert response.status_code==404 and response.json()["detail"]==page.WORDS["downloadError"]
    monkeypatch.setattr(module.private_api.sync,"verified_session",Mock(side_effect=ValueError("Mock expired")))
    assert client.post("/api/compare",headers=HEADERS,json={}).status_code==401


def test_original_captions_and_no_runtime_reader_or_fee_notice():
    literals={node.value for node in ast.walk(ast.parse((ROOT/"app.py").read_text())) if isinstance(node,ast.Constant) and isinstance(node.value,str)}
    for key in ("modelsCaption","savedCaption","methodCaption","modelsGate","portfoliosGate","closing","mismatch","dateOrder","portfolioDateOrder"):
        assert page.WORDS[key] in literals,key
    source=(ROOT/"server/compare.py").read_text()+(ROOT/"server/compare_presentation.py").read_text()
    assert "app.py" not in source and "MINIMUM_NOTE" not in source


def simple_model(start, *, gap=False, benchmark=100.):
    dates=pd.date_range(start,periods=8,freq="ME")
    if gap:dates=dates.delete(4)
    prices=pd.DataFrame({"A":np.arange(len(dates))+100.,"SPY":benchmark},index=dates)
    decisions=pd.DataFrame({"selected_asset":"A"},index=dates[:-1])
    return ModelInput("Mock monthly",decisions,prices)


@pytest.mark.parametrize("mode",["models","portfolios"])
def test_no_common_periods_refused_without_caching(mode):
    first,second=simple_model("2020-01-31"),simple_model("2022-01-31")
    request=page.Inputs(mode=mode)
    if mode=="models":
        loaded={"inputs":{"A":first,"B":second},"bounds":(pd.Timestamp("2022-01-31").date(),pd.Timestamp("2020-08-31").date())}
        expected="The selected models have no common executable holding periods."
        with pytest.raises(ValueError,match="no common executable"):
            compare_models(loaded["inputs"],10000)
    else:
        loaded={"inputs":{"Portfolio 1":{"A":(1,first)},"Portfolio 2":{"B":(1,second)}}}
        expected="The selected portfolios have no shared executable history."
    with pytest.raises(ValueError) as exc:page.calculate(request,loaded)
    assert str(exc.value)==expected and not page.RESULTS.warm


@pytest.mark.parametrize("change,expected",[("gap","Shared monthly comparison history contains missing or duplicate holding periods."),("benchmark","Compared portfolios have inconsistent benchmark histories.")])
def test_portfolio_gaps_and_inconsistent_benchmark_refused(change,expected):
    first=simple_model("2020-01-31",gap=change=="gap")
    second=simple_model("2020-01-31",gap=change=="gap",benchmark=100.)
    if change=="benchmark":second.monthly_prices.loc[second.monthly_prices.index[3]:,"SPY"]=110.
    with pytest.raises(ValueError) as exc:
        page.calculate(page.Inputs(mode="portfolios"),{"inputs":{"Portfolio 1":{"A":(1,first)},"Portfolio 2":{"B":(1,second)}}})
    assert str(exc.value)==expected


def test_usd_only_page_guard_and_invalid_private_payload_never_echoed(signed_in,monkeypatch):
    records=[saved("FAKE-ID-A",["HAA-Simple"],[100]),saved("FAKE-ID-B",["Buy and Hold Gold Israel"],[100])]
    monkeypatch.setattr(module.private_api.sync,"list_portfolios",lambda *a:records)
    monkeypatch.setattr(page,"load",Mock(side_effect=AssertionError("Invalid selection must not load prices")))
    body={"mode":"portfolios","portfolio_ids":[r["id"] for r in records]}
    response=client.post("/api/compare",headers=HEADERS,json=body)
    assert response.status_code==400 and response.json()["detail"]=="Buy and Hold Gold Israel: portfolio comparison requires USD sleeves."
    records[1]["payload"]["sleeves"][0]["weight"]="FAKE-PRIVATE-INVALID"
    response=client.post("/api/compare",headers=HEADERS,json=body)
    assert response.status_code==400 and "FAKE-PRIVATE" not in response.text


def test_portfolio_cache_order_is_not_silently_sorted(signed_in,monkeypatch):
    labels=["HAA-Simple","Inflation Compass Standard"]
    install(monkeypatch,labels)
    records=[saved("FAKE-A",labels,[60,40]),saved("FAKE-B",labels,[30,70])]
    monkeypatch.setattr(module.private_api.sync,"list_portfolios",lambda *a:deepcopy(records))
    body={"mode":"portfolios","portfolio_ids":["FAKE-A","FAKE-B"]}
    one=post(body)
    records[0]["payload"]["name"]="FAKE-RENAMED"
    records[0]["payload"]["total_ils"]=9876
    records[0]["payload"]["ils_per_usd"]=2.71828
    assert post(body)["cache"]["key"]==one["cache"]["key"]
    records[0]["payload"]["sleeves"].reverse()
    assert post(body)["cache"]["key"]!=one["cache"]["key"]
