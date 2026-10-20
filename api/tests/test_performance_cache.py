"""Fake public inputs only; exact memo parity and snapshot safety."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pandas as pd
import pytest
from server import input_cache as cache, performance
from test_signals import fixtures
from haa.model_catalog import definition_for_label
from haa.constants import ASSETS


@pytest.mark.parametrize("label",["HAA-Simple","A-RVol Shifter V3 Cash-Only","Inflation Compass Standard"])
def test_decision_memo_bit_exact_and_mutation_isolated(label):
    strategy=definition_for_label(label).model_class()
    daily,_,_=fixtures(label)
    from haa.portfolio_signals import monthly_strategy_input
    _,monthly=monthly_strategy_input(daily,getattr(strategy,"market_data_assets",getattr(strategy,"data_assets",ASSETS)))
    inputs=daily if getattr(strategy,"uses_daily_signals",False) else monthly
    expected=strategy.decisions(inputs)
    actual=performance.decisions(strategy,inputs)
    pd.testing.assert_frame_equal(expected,actual,check_exact=True)
    actual.loc[actual.index[0],"regime"]="mutated"
    if "target_weights" in actual:
        weights=next((v for v in actual.target_weights if isinstance(v,dict)),None)
        if weights is not None:weights["FAKE-ALTERED"]=99
    pd.testing.assert_frame_equal(expected,performance.decisions(strategy,inputs),check_exact=True)


def test_snapshot_json_roundtrip_preserves_binary_float_dates_missing_and_metadata():
    frame=pd.DataFrame({"A":[1.2345678901234567,float("nan")],"B":[None,2.]},index=pd.date_range("2024-01-01",periods=2,name="session"))
    restored=cache.unpack(json.loads(json.dumps(cache.pack(frame),allow_nan=False)))
    pd.testing.assert_frame_equal(frame,restored,check_exact=True,check_freq=False)
    meta=pd.DataFrame({"source":["Actual source"],"identifier":["FAKE"],"price_field":["Actual field"]},index=pd.Index(["A"],name="asset"))
    pd.testing.assert_frame_equal(meta,cache.unpack(json.loads(json.dumps(cache.pack(meta)))),check_exact=True)


def test_snapshot_expiration_degraded_failure_and_settings(monkeypatch):
    import server.cache as shared
    monkeypatch.setattr(shared,"cache_client",Mock(side_effect=RuntimeError("Mock unavailable")))
    clock=[301.];monkeypatch.setattr(cache,"time",lambda:clock[0])
    frame=pd.DataFrame({"A":[1.2345678901234567]},index=pd.date_range("2024-01-01",periods=1))
    meta=pd.DataFrame({"source":["Fake"]},index=["A"])
    load=Mock(return_value=(frame,meta,[]))
    strategy=SimpleNamespace(data_assets=["A"])
    first=cache.inputs(strategy,False,load);second=cache.inputs(strategy,False,load)
    assert load.call_count==1
    pd.testing.assert_frame_equal(first[0],second[0],check_exact=True,check_freq=False)
    second[0].iloc[0,0]=99
    assert cache.inputs(strategy,False,load)[0].iloc[0,0]==frame.iloc[0,0]
    clock[0]=601.;cache.inputs(strategy,False,load);assert load.call_count==2
    strategy.benchmark_asset="B";cache.inputs(strategy,False,load);assert load.call_count==3
    clock[0]=901.;load.return_value=(frame,meta,["Mock download degraded"])
    for _ in range(2):assert cache.inputs(strategy,False,load)[2]==["Mock download degraded"]
    assert load.call_count==5
    clock[0]=1201.;load.side_effect=RuntimeError("Mock download failed")
    for _ in range(2):
        with pytest.raises(RuntimeError,match="Mock download failed"):cache.inputs(strategy,False,load)
    assert load.call_count==7
