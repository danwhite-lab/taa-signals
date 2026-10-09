import json
import numpy as np
import pandas as pd
import pytest

from haa.engine import run_backtest
from haa.comparison import ModelInput
from haa.portfolio_backtest import run_portfolio_backtest
from haa.backtest_options import result_metrics, unit_curves
from haa.portfolio_config import backtest_portfolio_config
from haa.deep_history import ALL_DEEP_HISTORY_SPECS, deep_history_model_input
from haa.market_sessions import us_equity_sessions


def monthly():
    dates = pd.date_range("2024-01-31", periods=4, freq="ME")
    p = pd.DataFrame({"A":100.,"B":100.,"SPY":100.},index=dates)
    d = pd.DataFrame({"selected_asset":"A"}, index=dates[:-1])
    return d,p


def daily():
    dates = us_equity_sessions("2024-01-29","2024-03-04")
    p=pd.DataFrame({"A":100.,"B":100.,"SPY":100.},index=dates)
    d=pd.DataFrame({"selected_asset":"A", "target_weights":[{"A":1.} for _ in dates]},index=dates)
    d.attrs.update(execution_frequency="daily",completed_through=dates[-1])
    return d,p


def test_monthly_dca_flat_market_is_not_return():
    d,p=monthly()
    r=run_backtest(d,p,1000,monthly_contribution=100)
    np.testing.assert_allclose(r.monthly.pre_tax_value,[1000,1100,1200])
    np.testing.assert_allclose(r.monthly.benchmark_value,[1000,1100,1200])
    np.testing.assert_allclose(r.monthly.pre_tax_monthly_return,0)
    m=result_metrics(r,"pre_tax_value",1000)
    assert m["CAGR"]==pytest.approx(0)
    assert m["Total contributed"]==1200
    assert m["Investment gain"]==0
    assert unit_curves(r,{"A":"pre_tax_value"},1000).A.eq(1000).all()


def test_fixed_fee_buy_switch_and_no_trade():
    d,p=monthly()
    d.loc[d.index[1]:,"selected_asset"]="B"
    r=run_backtest(d,p,1000,fixed_fee=5)
    np.testing.assert_allclose(r.monthly.pre_tax_fee,[5,10,0])
    np.testing.assert_allclose(r.monthly.pre_tax_value,[995,985,985])


def test_dca_purchase_fee_and_cost_basis_no_tax_on_deposits():
    d,p=monthly()
    d.iloc[-1,0]="B"
    r=run_backtest(d,p,1000,monthly_contribution=100,fixed_fee=5,tax_enabled=True)
    assert r.tax_events.tax_paid.sum()==0
    np.testing.assert_allclose(r.monthly.pre_tax_fee,[5,5,10])
    np.testing.assert_allclose(r.monthly.pre_tax_value,[995,1090,1180])
    np.testing.assert_allclose(r.monthly.pre_tax_value,r.monthly.after_tax_value)


def test_basket_fee_per_order_not_per_sleeve():
    d,p=monthly()
    d["target_weights"]=[{"A":.5,"B":.5}]*3
    r=run_backtest(d,p,1000,fixed_fee=5)
    assert r.monthly.pre_tax_fee.tolist()==[10,0,0]


def test_tax_excludes_dca_and_deducts_fixed_sale_fee():
    d,p=monthly()
    p.loc[p.index[1]:,"A"]=110
    d.iloc[-1,0]="B"
    r=run_backtest(d,p,1000,monthly_contribution=100,fixed_fee=5,tax_enabled=True)
    assert r.tax_events.tax_paid.sum()==pytest.approx(21.125)
    assert r.monthly.pre_tax_value.iloc[-1]==pytest.approx(1279.5)
    assert r.monthly.after_tax_value.iloc[-1]==pytest.approx(1258.375)


def test_contribution_too_small_for_fixed_fee_is_rejected():
    d,p=monthly()
    with pytest.raises(ValueError,match="consumes"):
        run_backtest(d,p,1000,monthly_contribution=1,fixed_fee=5)


def test_monthly_portfolio_dca_fixed_fee_and_tax():
    d,p=monthly()
    a=ModelInput("one",d,p)
    b=ModelInput("two",d.assign(selected_asset="B"),p)
    r=run_portfolio_backtest({"one":(.5,a),"two":(.5,b)},1000,monthly_contribution=100,fixed_fee=5,tax_enabled=True)
    np.testing.assert_allclose(r.monthly.pre_tax_value,[990,1080,1170])
    np.testing.assert_allclose(r.monthly.after_tax_value,r.monthly.pre_tax_value)
    assert result_metrics(r,"benchmark_value",1000)["CAGR"]==pytest.approx(0)


def test_daily_dca_flat_and_same_holding_buys_only_once_per_month():
    d,p=daily()
    r=run_backtest(d,p,1000,daily_prices=p,daily_open_prices=p,monthly_contribution=100,fixed_fee=5,tax_enabled=True)
    assert r.daily.contribution.sum()==200
    assert r.daily.pre_tax_fee.sum()==15
    assert r.daily.pre_tax_value.iloc[-1]==1185
    assert r.daily.benchmark_value.iloc[-1]==1200
    assert r.tax_events.empty
    assert result_metrics(r,"benchmark_value",1000)["CAGR"]==pytest.approx(0)


def test_daily_dca_overnight_and_intraday_are_time_weighted():
    d,p=daily()
    opens=p.copy()
    p.loc["2024-02-01":,"A"]=120.
    p.loc["2024-02-01":,"SPY"]=120.
    opens.loc["2024-02-01",["A","SPY"]]=110.
    opens.loc["2024-02-02":,["A","SPY"]]=120.
    r=run_backtest(d,p,1000,daily_prices=p,daily_open_prices=opens,monthly_contribution=100)
    assert r.daily.loc["2024-02-01","pre_tax_monthly_return"]==pytest.approx(.2)
    assert r.daily.loc["2024-02-01","pre_tax_value"]==pytest.approx(1200*120/110)


def test_mixed_dca_flat_market_and_fees():
    d,p=daily()
    slow_d=pd.DataFrame({"selected_asset":"B"},index=pd.to_datetime(["2023-12-29","2024-01-31","2024-02-29"]))
    fast=ModelInput("fast",d,p,p,"SPY",p.copy())
    slow=ModelInput("slow",slow_d,p,p,"SPY",p.copy())
    r=run_portfolio_backtest({"fast":(.5,fast),"slow":(.5,slow)},1000,monthly_contribution=100,fixed_fee=5,tax_enabled=True)
    assert r.daily.contribution.sum()==200
    assert r.daily.pre_tax_value.iloc[-1]==1170
    assert r.daily.benchmark_value.iloc[-1]==1200
    assert r.tax_events.empty
    assert result_metrics(r,"benchmark_value",1000)["CAGR"]==pytest.approx(0)


def test_synthetic_dca_keeps_returns_and_tax_fee_guards():
    model=deep_history_model_input(ALL_DEEP_HISTORY_SPECS["rvol_synthetic"])
    opts=dict(daily_prices=model.daily_prices,benchmark_asset=model.benchmark_asset,start=pd.Timestamp("2024-01-31"),end=pd.Timestamp("2024-12-31"))
    a=run_backtest(model.decisions,model.monthly_prices,1000,**opts)
    b=run_backtest(model.decisions,model.monthly_prices,1000,monthly_contribution=100,**opts)
    np.testing.assert_allclose(a.monthly.pre_tax_monthly_return,b.monthly.pre_tax_monthly_return)
    assert b.monthly.contribution.sum()==1100
    assert b.monthly.pre_tax_value.iloc[-1]>a.monthly.pre_tax_value.iloc[-1]
    with pytest.raises(ValueError): run_backtest(model.decisions,model.monthly_prices,1000,fixed_fee=5,**opts)


@pytest.mark.parametrize("option,value",[("monthly_contribution",-1),("monthly_contribution",float("nan")),("fixed_fee",float("inf")),("fixed_fee",-1)])
def test_invalid_options_fail_closed(option,value):
    d,p=monthly()
    with pytest.raises(ValueError): run_backtest(d,p,1000,**{option:value})


def test_portfolio_json_validation_is_atomic_and_converts_capital():
    payload={"version":1,"total_ils":3700,"ils_per_usd":3.7,"sleeves":[{"model":"A","weight":100,"id":999}]}
    before=json.dumps(payload)
    sleeves,capital=backtest_portfolio_config(payload,{"A":object()})
    assert capital==1000 and sleeves[0]["id"]==1
    assert json.dumps(payload)==before
    for bad in ({**payload,"ils_per_usd":float("nan")},{**payload,"sleeves":[{"model":"A","weight":90}]},{**payload,"sleeves":[{"model":"UNKNOWN","weight":100}]}):
        with pytest.raises(ValueError): backtest_portfolio_config(bad,{"A":object()})
