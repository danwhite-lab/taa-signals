import numpy as np
import pandas as pd
import pytest
from haa.deep_history import ALL_DEEP_HISTORY_SPECS, deep_history_model_input, DEEP_HISTORY_DIR
from haa.synthetic_history import monthly_blend_input
from haa.synthetic_tax import trade_factors, ProxyBook, reset_sleeves
from haa.engine import run_backtest
from haa.portfolio_backtest import run_portfolio_backtest


def inputs():
    synthetic=deep_history_model_input(ALL_DEEP_HISTORY_SPECS["rvol_synthetic"])
    cm=deep_history_model_input(ALL_DEEP_HISTORY_SPECS["century_momentum"])
    ic=deep_history_model_input(ALL_DEEP_HISTORY_SPECS["inflation_compass"])
    return synthetic, {"A-RVol":(.3,monthly_blend_input(synthetic)), "CM":(.4,cm), "IC":(.3,ic)}


def test_all_source_nav_factors_and_execution_dates_reconcile():
    model,_=inputs()
    factors=trade_factors(DEEP_HISTORY_DIR/"arvol_synthetic_v5/daily.csv")
    np.testing.assert_allclose(100*factors.nav_factor.cumprod(),model.daily_prices.nav,rtol=1e-12)
    assert (factors.old_asset!=factors.new_asset).sum()==354
    assert (factors.execution=="NEXT_OPEN_TRADE_TODAY").sum()==226
    early=factors.loc[:"2000-12-31"]
    assert (early.after_factor==1).all()


def test_sale_at_open_tax_precedes_intraday_return_and_losses_offset():
    events=[]; audit=[]
    book=ProxyBook("test",True,.25,events,audit)
    book.buy("QLD",100,"2024-01-01","initial")
    book.mark(1.2)
    cash=book.sell("QLD",book.value,"2024-01-02","open switch")
    assert cash==115
    assert events[-1]["tax_paid"]==5
    book.buy("TQQQ",cash,"2024-01-02","switch")
    book.mark(1.1)
    assert book.value==pytest.approx(126.5)
    book.mark(.5)
    cash=book.sell("TQQQ",book.value,"2024-01-03","loss")
    assert book.tax.loss_carryforward==pytest.approx(51.75)
    book.buy("DEF",cash,"2024-01-03","cash")
    book.mark(1.1)
    book.sell("DEF",book.value,"2024-01-04","cash exit")
    assert events[-1]["tax_paid"]==0
    assert book.tax.loss_carryforward==pytest.approx(45.425)


def test_dca_is_basis_and_reset_tax_is_self_financing():
    events=[]; audit=[]
    a=ProxyBook("A",True,.25,events,audit); b=ProxyBook("B",True,.25,events,audit)
    a.buy("QLD",50,"2024-01-01","initial"); b.buy("BIL",50,"2024-01-01","initial")
    a.mark(2.)
    reset_sleeves({"A":a,"B":b},{"A":.5,"B":.5},{"A":{"QLD":1.},"B":{"BIL":1.}},"2024-01-31",20)
    total=a.value+b.value
    paid=sum(e["tax_paid"] for e in events)
    assert total==pytest.approx(170-paid)
    assert a.value==pytest.approx(b.value)
    assert paid>0
    assert all(e["reason"]=="monthly sleeve reset" for e in events)
    assert b.tax.cost_bases["BIL"]==pytest.approx(b.value)


def test_single_tax_zero_preserves_daily_source_and_dca():
    model,_=inputs()
    for contribution in (0.,1000.):
        options=dict(daily_prices=model.daily_prices,benchmark_asset=model.benchmark_asset,
                     start="2024-01-31",end="2025-12-31",monthly_contribution=contribution)
        pre=run_backtest(model.decisions,model.monthly_prices,100000,**options)
        zero=run_backtest(model.decisions,model.monthly_prices,100000,tax_enabled=True,tax_rate=0.,**options)
        np.testing.assert_allclose(zero.daily.after_tax_value,pre.daily.pre_tax_value,rtol=1e-12)
        np.testing.assert_allclose(zero.monthly.after_tax_monthly_return,pre.monthly.pre_tax_monthly_return,atol=1e-12)
        taxed=run_backtest(model.decisions,model.monthly_prices,100000,tax_enabled=True,**options)
        assert taxed.tax_events.tax_paid.sum()>0
        assert taxed.monthly.after_tax_value.iloc[-1]<pre.monthly.pre_tax_value.iloc[-1]
        assert taxed.tax_events.date.min()>=pd.Timestamp("2024-01-01")
        np.testing.assert_allclose(taxed.monthly.pre_tax_value,pre.monthly.pre_tax_value)


def test_three_sleeve_zero_tax_reconciles_and_tax_ledger_includes_resets():
    _,sleeves=inputs()
    options=dict(start="2024-01-31",end="2025-12-31",monthly_contribution=1000)
    pre=run_portfolio_backtest(sleeves,100000,**options)
    zero=run_portfolio_backtest(sleeves,100000,tax_enabled=True,tax_rate=0.,**options)
    np.testing.assert_allclose(zero.monthly.after_tax_value,pre.monthly.pre_tax_value,rtol=1e-11)
    np.testing.assert_allclose(zero.monthly.after_tax_monthly_return,pre.monthly.pre_tax_monthly_return,atol=1e-12)
    taxed=run_portfolio_backtest(sleeves,100000,tax_enabled=True,**options)
    assert taxed.tax_events.tax_paid.sum()>0
    assert "monthly sleeve reset" in set(taxed.tax_events.reason)
    assert "NEXT_OPEN_TRADE_TODAY" in set(taxed.tax_events.reason)
    assert "monthly proxy allocation" in set(taxed.tax_events.reason)
    assert set(taxed.tax_events.sold_sleeve)==set(sleeves)
    assert taxed.tax_events.date.min()>=pd.Timestamp("2023-12-31")
    assert taxed.daily is None
    assert taxed.monthly.contribution.sum()==23000
    assert taxed.monthly.after_tax_value.iloc[-1]<pre.monthly.pre_tax_value.iloc[-1]
    assert taxed.monthly.tax_paid.sum()==pytest.approx(taxed.tax_events.tax_paid.sum())
    assert taxed.monthly.portfolio_reset_tax.sum()==pytest.approx(taxed.tax_events.loc[taxed.tax_events.reason=="monthly sleeve reset","tax_paid"].sum())
    assert taxed.tax_events.date.is_monotonic_increasing
    resets=taxed.tax_events.loc[taxed.tax_events.reason=="monthly sleeve reset"]
    assert (resets.date.dt.day==1).all()
    assert (resets.date.dt.to_period("M")==resets.holding_period.dt.to_period("M")).all()


def test_full_common_history_zero_tax_and_large_cost_bases_reconcile():
    _,sleeves=inputs()
    zero=run_portfolio_backtest(sleeves,100000,tax_enabled=True,tax_rate=0.)
    assert len(zero.monthly)==478
    np.testing.assert_allclose(zero.monthly.after_tax_value,zero.monthly.pre_tax_value,rtol=1e-11)
    assert zero.tax_events.tax_paid.sum()==0.


def test_full_sale_of_large_basis_does_not_overshoot_from_rounding():
    book=ProxyBook("test",True,.25,[],[])
    book.buy("asset",876543210.1234567,"2024-01-01","initial")
    book.mark(1.123456789)
    book.sell("asset",book.value,"2024-01-02","exit")
    assert not book.tax.cost_bases


def test_single_sleeve_portfolio_equals_standalone_tax_when_no_dca():
    model,_=inputs()
    options=dict(start="1999-01-31",end="2002-12-31",tax_enabled=True)
    single=run_backtest(model.decisions,model.monthly_prices,100000,daily_prices=model.daily_prices,benchmark_asset=model.benchmark_asset,**options)
    portfolio=run_portfolio_backtest({"A-RVol":(1.,monthly_blend_input(model))},100000,**options)
    np.testing.assert_allclose(portfolio.monthly.after_tax_value,single.monthly.after_tax_value,rtol=1e-12)


def test_old_import_stays_tax_unsupported():
    model=deep_history_model_input(ALL_DEEP_HISTORY_SPECS["rvol_daily"])
    with pytest.raises(ValueError,match="requires daily"):
        run_backtest(model.decisions,model.monthly_prices,100000,tax_enabled=True,benchmark_asset=model.benchmark_asset)


def test_tax_preserves_benchmark_choice_and_does_not_invent_daily_benchmark():
    from haa.deep_history import DEEP_HISTORY_BENCHMARKS
    endings=[]
    for benchmark in DEEP_HISTORY_BENCHMARKS.values():
        model=deep_history_model_input(ALL_DEEP_HISTORY_SPECS["rvol_synthetic"],benchmark)
        result=run_backtest(model.decisions,model.monthly_prices,100000,daily_prices=model.daily_prices,
            benchmark_asset=model.benchmark_asset,tax_enabled=True,start="2024-01-31",end="2025-12-31")
        expected=model.monthly_prices[model.benchmark_asset].pct_change().loc[result.monthly.index]
        np.testing.assert_allclose(result.monthly.benchmark_monthly_return,expected)
        assert "benchmark_value" not in result.daily
        endings.append(result.monthly.after_tax_value.iloc[-1])
    assert endings[0]==pytest.approx(endings[1])


def test_factor_cache_rejects_changed_inputs(tmp_path):
    from shutil import copyfile
    root=DEEP_HISTORY_DIR/"arvol_synthetic_v5"
    (tmp_path/"inputs").mkdir()
    for file in ("NDX", "IRX"):
        copyfile(root/"inputs"/f"{file}.csv",tmp_path/"inputs"/f"{file}.csv")
    copyfile(root/"daily.csv",tmp_path/"daily.csv")
    trade_factors(tmp_path/"daily.csv")
    # A new input path containing wrong bytes must never hit the old cache.
    copyfile(root/"inputs/IRX.csv",tmp_path/"inputs/NDX.csv")
    with pytest.raises(ValueError,match="NDX input differs"):
        trade_factors(tmp_path/"daily.csv")


def test_no_sale_month_has_zero_tax_and_exportable_empty_ledger():
    model,_=inputs()
    factors=trade_factors(DEEP_HISTORY_DIR/"arvol_synthetic_v5/daily.csv")
    month=next(period.to_timestamp("M") for period,group in factors.groupby(factors.index.to_period("M"))
               if period>=pd.Period("1986-12") and (group.old_asset==group.new_asset).all())
    result=run_backtest(model.decisions,model.monthly_prices,100000,daily_prices=model.daily_prices,
        benchmark_asset=model.benchmark_asset,tax_enabled=True,start=month,end=month)
    assert result.tax_events.empty
    assert "cost_basis_sold" in result.tax_events.columns
    assert result.monthly.tax_paid.sum()==0.
    np.testing.assert_allclose(result.monthly.after_tax_value,result.monthly.pre_tax_value,rtol=1e-12)
