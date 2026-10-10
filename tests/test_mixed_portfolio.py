import numpy as np
import pandas as pd
import pytest

from haa.comparison import ModelInput
from haa.engine import run_backtest
from haa.portfolio_backtest import run_portfolio_backtest
from haa.market_sessions import us_equity_sessions


def fixture(end='2024-03-05'):
    dates=us_equity_sessions('2024-01-02',end)
    prices=pd.DataFrame({'A':100.,'B':100.,'SPY':100.},index=dates)
    d=pd.DataFrame({'target_weights':[{'A':1.} for _ in dates], 'selected_asset':'A'},index=dates)
    d.attrs.update(execution_frequency='daily',completed_through=dates[-1])
    monthly=pd.DataFrame({'selected_asset':'B'},index=pd.to_datetime(['2023-12-29','2024-01-31','2024-02-29']))
    daily=ModelInput('daily',d,prices,prices,'SPY',prices.copy())
    slow=ModelInput('monthly',monthly,prices,prices)
    return daily,slow,prices


def test_single_daily_sleeve_equals_standalone_next_open_with_tax_and_fees():
    daily,_,prices=fixture()
    prices.loc[prices.index[5]:,'A']=120
    daily.decisions.iloc[8:,daily.decisions.columns.get_loc('target_weights')]=pd.Series([{'B':1.}]*len(prices.index[8:]),index=prices.index[8:])
    result=run_portfolio_backtest({'rvol':(1.,daily)},1000,transaction_cost=.001,tax_enabled=True)
    standalone=run_backtest(daily.decisions,prices,1000,transaction_cost=.001,tax_enabled=True,daily_prices=prices,daily_open_prices=daily.daily_open_prices)
    for col in ('pre_tax_value','after_tax_value','benchmark_value'):
        np.testing.assert_allclose(result.daily[col],standalone.daily[col],rtol=1e-12)
    assert set(result.tax_events.tax_level)=={'strategy sleeve'}


def test_weights_drift_no_sleeve_reset_sales_or_tax():
    daily,slow,prices=fixture()
    prices.loc[prices.index[1]:,'A']=np.linspace(100,200,len(prices)-1)
    result=run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,slow)},100,tax_enabled=True)
    assert result.daily.pre_tax_value.iloc[-1]==pytest.approx(150)
    assert result.daily.after_tax_value.iloc[-1]==pytest.approx(150)
    assert result.sleeve_nav.fast.iloc[-1]/result.daily.pre_tax_value.iloc[-1]==pytest.approx(2/3)
    assert result.tax_events.empty
    assert result.daily.index.min()==prices.index[1]


def test_monthly_switch_at_next_close_and_only_real_sales_taxed():
    daily,slow,prices=fixture()
    slow.decisions['selected_asset']='A'
    slow.decisions.loc[pd.Timestamp('2024-01-31'),'selected_asset']='B'
    slow.decisions.loc[pd.Timestamp('2024-02-29'),'selected_asset']='B'
    prices.loc['2024-02-01','A']=200
    prices.loc['2024-02-02':,'A']=300
    result=run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,slow)},100,tax_enabled=True)
    sales=result.tax_events[result.tax_events.sold_sleeve=='slow']
    assert len(sales)==1
    assert sales.date.iloc[0]==pd.Timestamp('2024-02-01')
    assert sales.tax_paid.iloc[0]==pytest.approx(12.5)
    assert result.sleeve_nav.slow.loc['2024-02-01']==pytest.approx(100)
    assert result.sleeve_nav.slow.loc['2024-02-02']==pytest.approx(100)


def test_daily_monthly_compounding_reconciles_and_partial_month_is_kept():
    daily,slow,prices=fixture('2024-02-07')
    prices.loc[prices.index[1]:,'A']=np.linspace(100,140,len(prices)-1)
    result=run_portfolio_backtest({'fast':(.7,daily),'slow':(.3,slow)},100,transaction_cost=.001,tax_enabled=True)
    for col,ret in [('pre_tax_value','pre_tax_monthly_return'),('after_tax_value','after_tax_monthly_return'),('benchmark_value','benchmark_monthly_return')]:
        assert np.prod(1+result.monthly[ret])==pytest.approx(result.daily[col].iloc[-1]/100)
    assert result.monthly.index[-1]==pd.Timestamp('2024-02-07')


def test_subrange_restarts_capital_and_books_no_pre_start_tax():
    daily,slow,prices=fixture()
    prices.loc['2024-01-10':,'A']=150
    daily.daily_open_prices.loc['2024-01-10':,'A']=150
    result=run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,slow)},100,tax_enabled=True,start='2024-02-05',end='2024-02-09')
    assert result.daily.pre_tax_value.iloc[0]==pytest.approx(100)
    assert result.tax_events.empty
    assert result.common_index.min()==pd.Timestamp('2024-02-05')


def test_missing_sessions_prices_or_opens_rejected():
    daily,slow,prices=fixture()
    broken=prices.drop(prices.index[10])
    with pytest.raises(ValueError,match='Missing US equity trading sessions'):
        run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,ModelInput('slow',slow.decisions,broken,broken))},100)
    daily.daily_open_prices.iloc[10,0]=np.nan
    with pytest.raises(ValueError,match='opening prices'):
        run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,slow)},100)


def test_monthly_only_proxy_and_ils_not_silently_mixed():
    daily,slow,prices=fixture()
    with pytest.raises(ValueError,match='actual daily security prices'):
        run_portfolio_backtest({'fast':(.5,daily),'proxy':(.5,ModelInput('proxy',slow.decisions,prices))},100)
    with pytest.raises(ValueError,match='USD sleeves'):
        run_portfolio_backtest({'fast':(.5,daily),'ils':(.5,ModelInput('ils',slow.decisions,prices,prices,execution_currency='ILS'))},100)


def test_weighted_monthly_book_does_not_liquidate_retained_assets():
    daily,slow,prices=fixture()
    slow.decisions['target_weights']=[{'A':.5,'B':.5} for _ in slow.decisions.index]
    prices.loc['2024-01-05':,'A']=200
    result=run_portfolio_backtest({'fast':(.5,daily),'basket':(.5,slow)},100,tax_enabled=True)
    sales=result.tax_events[result.tax_events.sold_sleeve=='basket']
    # Rebalancing the now overweight asset sells only its excess, not the entire holding.
    assert sales.iloc[0].proceeds==pytest.approx(12.5)
    assert sales.iloc[0].realized_gain==pytest.approx(6.25)
    assert set(sales.sold_asset)=={'A'}


def test_intramonth_drawdown_not_hidden_by_monthly_aggregation():
    daily,slow,prices=fixture('2024-01-31')
    prices.loc[prices.index[5],'A']=50
    result=run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,slow)},100)
    from haa.daily_engine import daily_performance_metrics
    assert daily_performance_metrics(result,'pre_tax_value',100)['Maximum drawdown']==pytest.approx(-.25)
    assert result.monthly.pre_tax_monthly_return.iloc[-1]==pytest.approx(0)


def test_initial_weights_and_missing_daily_decisions_fail():
    daily,slow,prices=fixture()
    with pytest.raises(ValueError,match='total exactly 100%'):
        run_portfolio_backtest({'fast':(.4,daily),'slow':(.4,slow)},100)
    broken=daily.decisions.drop(daily.decisions.index[5])
    broken.attrs=daily.decisions.attrs.copy()
    with pytest.raises(ValueError,match='No daily decision scheduled'):
        run_portfolio_backtest({'fast':(.5,ModelInput('broken',broken,prices,prices,'SPY',daily.daily_open_prices)),'slow':(.5,slow)},100)


def test_missing_monthly_decision_is_not_silently_carried():
    daily,slow,prices=fixture()
    incomplete=slow.decisions.drop(pd.Timestamp('2024-01-31'))
    with pytest.raises(ValueError,match='missing monthly decisions'):
        run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,ModelInput('slow',incomplete,prices,prices))},100)


def test_initial_fees_not_repeated_by_passive_monthly_holding():
    daily,slow,prices=fixture()
    result=run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,slow)},100,transaction_cost=.01)
    assert result.daily.pre_tax_value.iloc[0]==pytest.approx(99)
    assert result.daily.pre_tax_value.iloc[-1]==pytest.approx(99)
    assert result.daily.turnover.iloc[0]==pytest.approx(.99)
    assert result.daily.turnover.iloc[1:].sum()==pytest.approx(0)


def test_future_price_changes_do_not_change_prior_portfolio_values():
    daily,slow,prices=fixture()
    base=run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,slow)},100)
    prices.loc['2024-02-12':,'A']*=2
    changed=run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,slow)},100)
    pd.testing.assert_frame_equal(base.daily.loc[:'2024-02-09'],changed.daily.loc[:'2024-02-09'])


def test_three_sleeves_supported_with_independent_initial_funding():
    daily,slow,prices=fixture()
    prices.loc[prices.index[1]:,'A']=np.linspace(100,200,len(prices)-1)
    result=run_portfolio_backtest({'fast':(.2,daily),'slow1':(.3,slow),'slow2':(.5,slow)},100)
    assert result.daily.pre_tax_value.iloc[-1]==pytest.approx(120)
    assert result.sleeve_nav.slow1.iloc[-1]==pytest.approx(30)
    assert result.sleeve_nav.slow2.iloc[-1]==pytest.approx(50)


def test_inconsistent_benchmark_series_rejected():
    daily,slow,prices=fixture()
    other=prices.copy(); other.SPY*=2
    with pytest.raises(ValueError,match='inconsistent benchmark'):
        run_portfolio_backtest({'fast':(.5,daily),'slow':(.5,ModelInput('slow',slow.decisions,other,other))},100)


def test_quarterly_cap_trims_a_daily_sleeve_and_records_transfer_tax():
    fast,_,prices=fixture('2024-04-05')
    prices.loc[prices.index[1]:,'A']=np.linspace(100,300,len(prices)-1)
    fast.daily_open_prices.loc[prices.index[1]:,'A']=prices.loc[prices.index[1]:,'A']
    slow_decisions=fast.decisions.copy()
    slow_decisions['target_weights']=[{'B':1.} for _ in slow_decisions.index]
    slow=ModelInput('slow',slow_decisions,prices,prices,'SPY',prices.copy())
    result=run_portfolio_backtest(
        {'rvol':(.3,fast),'other':(.7,slow)},100,tax_enabled=True,
        sleeve_rebalance_mode='rvol_cap',rebalance_sleeve='rvol',
        rebalance_cap=.40,rebalance_target=.20,
    )
    review=result.daily.index[result.daily.portfolio_rebalance][0]
    assert result.sleeve_nav.loc[review,'rvol']/result.daily.loc[review,'pre_tax_value']==pytest.approx(.20)
    assert result.daily.loc[review,'portfolio_rebalance_turnover']>0
    assert set(result.tax_events.tax_level).issuperset({'portfolio sleeve transfer'})


def test_annual_target_reset_restores_all_starting_weights():
    fast,_,prices=fixture('2025-01-10')
    prices.loc[prices.index[1]:,'A']=np.linspace(100,300,len(prices)-1)
    fast.daily_open_prices.loc[prices.index[1]:,'A']=prices.loc[prices.index[1]:,'A']
    slow_decisions=fast.decisions.copy()
    slow_decisions['target_weights']=[{'B':1.} for _ in slow_decisions.index]
    slow=ModelInput('slow',slow_decisions,prices,prices,'SPY',prices.copy())
    result=run_portfolio_backtest(
        {'fast':(.4,fast),'slow':(.6,slow)},100,
        sleeve_rebalance_mode='annual_target',
    )
    review=result.daily.index[result.daily.portfolio_rebalance][0]
    assert result.sleeve_nav.loc[review,'fast']/result.daily.loc[review,'pre_tax_value']==pytest.approx(.40)
    assert result.sleeve_nav.loc[review,'slow']/result.daily.loc[review,'pre_tax_value']==pytest.approx(.60)
