"""Offline feature coverage; only synthetic prices and fake sessions."""
import pandas as pd
import pytest

from test_api import client
from test_private_api import signed_in, HEADERS
from server import backtest as single, backtest_multi as multi, cache
from haa.model_catalog import definition_for_label
from haa.tase_data import TASE_ISRAEL_ASSET_IDS

LABELS=("Buy and Hold TA-125 x3 Israel","Buy and Hold Nasdaq-100 x3 Monthly Israel",
        "Buy and Hold S&P 500 x3 Israel","Buy and Hold DAX x3 Monthly Israel")


@pytest.fixture
def prices(monkeypatch):
    days=pd.bdate_range("2024-01-02","2024-06-28")
    frame=pd.DataFrame({"TA125_X3_IL":[100.+i/10 for i in range(len(days))],
                        "NASDAQ_X3_MONTHLY_IL":[200.+i/5 for i in range(len(days))],
                        "SP500_X3_IL":[150.+i/8 for i in range(len(days))],
                        "DAX_X3_MONTHLY_IL":[250.+i/6 for i in range(len(days))],
                        "SPY":[400.+i/4 for i in range(len(days))]},index=days)
    metadata=pd.DataFrame([
        {"asset":a,"source":"Synthetic test prices","identifier":TASE_ISRAEL_ASSET_IDS.get(a,a),
         "price_field":"Maya published redemption price" if a in {"TA125_X3_IL","SP500_X3_IL"} else "Adjusted close"}
        for a in frame],).set_index("asset")
    monkeypatch.setattr(single,"load_data",lambda selected:(frame,metadata,[],None))
    monkeypatch.setattr(multi.signals,"load_inputs",lambda *a,**kw:(frame,metadata,[]))
    monkeypatch.setattr(single,"RESULTS",cache.ResultCache())
    monkeypatch.setattr(cache,"cache_client",lambda:(_ for _ in ()).throw(RuntimeError("Offline test")))
    return frame


@pytest.mark.parametrize("label",LABELS)
def test_new_models_in_catalogue_single_options_and_portfolio_config(signed_in,prices,label):
    catalogue=client.get("/api/strategies").json()
    assert next(row for row in catalogue if row["label"]==label)["execution_currency"]=="ILS"
    options=client.get("/api/backtest/options",params={"label":label},headers=HEADERS)
    assert options.status_code==200,options.text
    assert options.json()["label"]==label and options.json()["currency"]=="ILS"
    assert label in [row["label"] for row in options.json()["models"]]
    config=client.get("/api/backtest/config",params={"mode":"portfolio"},headers=HEADERS)
    assert config.status_code==200
    assert label in [row["label"] for row in config.json()["models"]]
    rules=next(row for row in client.get("/api/rules").json()["models"] if row["label"]==label)
    assert rules["markdown"] and not rules["description_missing"]
    assert rules["risk_warning"]==definition_for_label(label).model_class.risk_warning


@pytest.mark.parametrize("label",LABELS)
@pytest.mark.parametrize("deposit",[0.,100.])
def test_single_backtests_with_and_without_monthly_deposits(signed_in,prices,label,deposit):
    response=client.post("/api/backtest",headers=HEADERS,json={
        "label":label,"initial":10000.,"monthly_contribution":deposit,"fees_enabled":False})
    assert response.status_code==200,response.text
    result=response.json()
    assert result["currency"]=="ILS"
    assert result["settings"]["monthly_contribution"]==deposit
    assert definition_for_label(label).model_class.risk_warning in result["warnings"]
    assert result["metrics"]["pre_tax"]["Final value"]>10000.


@pytest.mark.parametrize("label",LABELS)
def test_single_request_before_fund_history_fails_visibly(signed_in,prices,label):
    response=client.post("/api/backtest",headers=HEADERS,json={"label":label,"start":"1999-01-01"})
    assert response.status_code==400
    assert "outside the available data range" in response.json()["detail"]


@pytest.mark.parametrize("labels",[LABELS[:2],LABELS[2:]])
def test_two_new_sleeves_and_dca_run_with_entry_fee_warning_visible(signed_in,prices,labels):
    response=client.post("/api/backtest",headers=HEADERS,json={
        "mode":"portfolio","initial":10000.,"monthly_contribution":100.,"tax_enabled":True,
        "sleeves":[{"id":1,"model":labels[0],"weight":50.},{"id":2,"model":labels[1],"weight":50.}]})
    assert response.status_code==200,response.text
    result=response.json()
    assert result["metrics"]["pre_tax"]["Final value"]>10000.
    for label in labels:
        assert definition_for_label(label).model_class.risk_warning in result["warnings"]


@pytest.mark.parametrize("labels",[LABELS[:2],LABELS[2:]])
def test_saved_portfolio_accepts_new_models_alongside_an_existing_model(signed_in,monkeypatch,labels):
    from server import private_api
    payload={"version":1,"name":"Synthetic mixed library portfolio","total_ils":10000.,"ils_per_usd":3.5,
             "sleeves":[{"id":i,"model":label,"weight":weight} for i,(label,weight) in enumerate(
                 [(labels[0],40.),(labels[1],40.),("Buy and Hold Gold Israel",20.)],1)]}
    saved=[]
    def save(*args,**kwargs):
        saved.append(args[-1])
        return {"id":"fake-id","payload":args[-1]}
    monkeypatch.setattr(private_api.sync,"save_portfolio",save)
    result=client.post("/api/portfolios",headers=HEADERS,json={"payload":payload})
    assert result.status_code==200,result.text
    assert saved==[payload]
