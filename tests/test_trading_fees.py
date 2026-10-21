"""Fake prices/capital only. No downloads or real account data."""
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from haa.trading_fees import TradingFees, rebalance, totals
from haa.engine import run_backtest
from haa.comparison import ModelInput
from haa.portfolio_backtest import run_portfolio_backtest
from haa.market_sessions import us_equity_sessions, tase_equity_sessions


def monthly():
    dates = pd.date_range('2024-01-31', periods=4, freq='ME')
    prices = pd.DataFrame({'A':100., 'B':100., 'SPY':100.}, index=dates)
    return pd.DataFrame({'selected_asset':['A','A','B']}, index=dates[:-1]), prices


def daily(local=False, end='2024-03-05'):
    dates = (tase_equity_sessions if local else us_equity_sessions)('2024-01-02',end)
    prices = pd.DataFrame({'A':100.,'B':100.,'SPY':100.},index=dates)
    d = pd.DataFrame({'target_weights':[{'A':1.} for _ in dates], 'selected_asset':'A', 'model_state':'A'},index=dates)
    d.attrs.update(execution_frequency='daily',completed_through=dates[-1])
    if local: d.attrs['local_daily_execution']=True
    return d, prices


@pytest.mark.parametrize('currency,notional,expected', [('ILS',1000,2),('ILS',10000,5),('ILS',4000,2),('USD',1000,5),('USD',100000,5)])
def test_currency_fee_rules(currency,notional,expected):
    assert TradingFees(currency).charge(notional)==expected
    assert TradingFees(currency).charge(0)==0


@pytest.mark.parametrize('kwargs', [{'currency':'EUR'},{'currency':'USD','usd_flat':-1}, {'currency':'ILS','ils_percent':float('nan')}, {'currency':'ILS','ils_percent':11}])
def test_invalid_assumptions(kwargs):
    with pytest.raises(ValueError): TradingFees(**kwargs)


def test_percentage_based_on_actual_purchase_not_cash_budget_and_minimum_not_additive():
    fees=TradingFees('ILS')
    buys, fee=fees.purchase(10000, {'A':10000})
    assert buys['A']==pytest.approx(10000/1.0005)
    assert fee==pytest.approx(buys['A']*.0005)
    buys, fee=fees.purchase(1000, {'A':500,'B':500})
    assert buys==pytest.approx({'A':498,'B':498})
    assert fee==4


@pytest.mark.parametrize('local',[False,True])
@pytest.mark.parametrize('taxed',[False,True])
def test_daily_fees_off_exact_legacy_frames(local,taxed):
    d,p=daily(local)
    kwargs=dict(daily_prices=p,daily_open_prices=p,tax_enabled=taxed,monthly_contribution=100)
    old=run_backtest(d,p,1000,**kwargs)
    off=run_backtest(d,p,1000,trading_fees=None,**kwargs)
    for field in ('monthly','daily','audit','tax_events'):
        assert_frame_equal(getattr(old,field),getattr(off,field),check_exact=True)


@pytest.mark.parametrize('weighted',[False,True])
@pytest.mark.parametrize('taxed',[False,True])
def test_monthly_fees_off_exact_legacy_frames(weighted,taxed):
    d,p=monthly()
    if weighted: d['target_weights']=[{'A':.5,'B':.5}]*3
    kwargs=dict(tax_enabled=taxed,monthly_contribution=100)
    old=run_backtest(d,p,1000,**kwargs)
    off=run_backtest(d,p,1000,trading_fees=None,**kwargs)
    for field in ('monthly','audit','tax_events'):
        assert_frame_equal(getattr(old,field),getattr(off,field),check_exact=True)


@pytest.mark.parametrize('fees',[TradingFees('USD',usd_flat=0),TradingFees('ILS',ils_percent=0,ils_minimum=0)])
def test_effective_zero_fee_schedule_is_also_exact_legacy(fees):
    d,p=monthly()
    legacy=run_backtest(d,p,1000,tax_enabled=True)
    zero=run_backtest(d,p,1000,tax_enabled=True,trading_fees=fees)
    for field in ('monthly','audit','tax_events'):
        assert_frame_equal(getattr(legacy,field),getattr(zero,field),check_exact=True)


@pytest.mark.parametrize('currency,expected_fee,final', [('USD',20,1180),('ILS',8,1192)])
def test_monthly_initial_deposit_and_switch_each_side(currency,expected_fee,final):
    d,p=monthly()
    r=run_backtest(d,p,1000,tax_enabled=True,monthly_contribution=100,trading_fees=TradingFees(currency))
    assert totals(r)=={'pre_tax':expected_fee,'after_tax':expected_fee}
    assert r.monthly.pre_tax_value.iloc[-1]==pytest.approx(final)
    assert r.monthly.after_tax_value.iloc[-1]==pytest.approx(final)
    assert r.tax_events.tax_paid.sum()==0
    orders=r.monthly.iloc[-1].security_trades
    assert [o['side'] for o in orders if o['book']=='pre-tax']==['sell','buy']


@pytest.mark.parametrize('local,currency,fee',[(False,'USD',5),(True,'ILS',2)])
def test_daily_deposits_switch_and_fee_totals_not_monthly_last_day(local,currency,fee):
    d,p=daily(local)
    for day in d.index[10:]:
        d.at[day,'target_weights']={'B':1.}
        d.at[day,'selected_asset']='B'; d.at[day,'model_state']='B'
    r=run_backtest(d,p,1000,daily_prices=p,daily_open_prices=p,tax_enabled=True,
                   monthly_contribution=100,trading_fees=TradingFees(currency))
    assert totals(r)=={'pre_tax':5*fee,'after_tax':5*fee}  # initial + switch two sides + Feb/Mar buys
    assert r.daily.pre_tax_value.iloc[-1]==pytest.approx(1200-5*fee)
    assert r.daily.after_tax_value.iloc[-1]==pytest.approx(1200-5*fee)
    assert r.monthly.pre_tax_fee.sum()==r.daily.pre_tax_fee.sum()


def test_tase_annual_blend_reset_charges_both_security_sides():
    dates=tase_equity_sessions('2024-12-29','2025-01-06')
    p=pd.DataFrame({'A':100.,'B':100.,'SPY':100.},index=dates)
    p.loc['2024-12-31':,'A']=200.
    d=pd.DataFrame({'target_weights':[{'A':.5,'B':.5} for _ in dates], 'selected_asset':'blend', 'model_state':'QLD'},index=dates)
    d.attrs.update(execution_frequency='daily',local_daily_execution=True,completed_through=dates[-1])
    r=run_backtest(d,p,1000,daily_prices=p,trading_fees=TradingFees('ILS'))
    assert totals(r)['pre_tax']==8
    assert r.daily.pre_tax_value.iloc[-1]==pytest.approx(1490)
    assert len(r.audit)==2
    assert r.audit.annual_reset.iloc[-1]


def test_sale_fee_reduces_proceeds_before_tax_and_buy_fee_in_basis():
    d,p=monthly()
    p.loc[p.index[1]:,'A']=120.
    r=run_backtest(d,p,1000,tax_enabled=True,trading_fees=TradingFees('USD'))
    # Initial net $995, appreciates to $1194; sale $1194-$5,
    # acquisition basis $1000. Tax ($1189-$1000)*25%=$47.25.
    assert r.tax_events.iloc[0].proceeds==pytest.approx(1189)
    assert r.tax_events.iloc[0].tax_paid==pytest.approx(47.25)
    assert r.monthly.after_tax_value.iloc[-1]==pytest.approx(1136.75)


def test_retained_holdings_no_trades_no_final_liquidation_and_each_basket_side():
    d,p=monthly(); d['target_weights']=[{'A':.5,'B':.5}]*3
    p.loc[p.index[1]:,'A']=200.
    r=run_backtest(d,p,10000,trading_fees=TradingFees('USD'))
    assert r.monthly.pre_tax_fee.iloc[0]==10
    assert r.monthly.pre_tax_fee.iloc[1]==10 # drift reset: A sale, B buy
    assert r.monthly.pre_tax_fee.iloc[-1]==0 # no drift/strategy change
    assert totals(r)['pre_tax']==20


def test_minimum_consumes_cash_fails_explicitly():
    with pytest.raises(ValueError,match='consume'):
        TradingFees('USD').purchase(5,{'A':5})
    with pytest.raises(ValueError,match='consume'):
        rebalance({'A':1},0,{'B':1},TradingFees('USD'))


def test_portfolio_separate_sleeve_orders_and_off_parity():
    d,p=monthly(); d['selected_asset']='A'
    sleeves={'one':(.5,ModelInput('one',d,p)), 'two':(.5,ModelInput('two',d,p))}
    off=run_portfolio_backtest(sleeves,1000,trading_fees=None)
    old=run_portfolio_backtest(sleeves,1000)
    assert_frame_equal(off.monthly,old.monthly,check_exact=True)
    r=run_portfolio_backtest(sleeves,1000,monthly_contribution=100,trading_fees=TradingFees('USD'))
    assert totals(r)['pre_tax']==30 # two sleeves, inception and two deposits
    assert r.monthly.pre_tax_value.iloc[-1]==pytest.approx(1170)


def test_losses_do_not_cross_sleeve_ledgers():
    from haa.trading_fees import SleeveTaxBooks
    tax=SleeveTaxBooks(.25)
    tax.buy('one::A',1000); tax.buy('two::A',1000)
    tax.sell(900,asset='one::A',cost_basis_sold=1000)
    event=tax.sell(1100,asset='two::A',cost_basis_sold=1000)
    assert event['tax_paid']==25


def test_nav_proxy_without_trade_notionals_not_silently_fee_free():
    d,p=monthly(); d.attrs['daily_nav_proxy']=True
    with pytest.raises(ValueError,match='turn fees off'):
        run_backtest(d,p,1000,trading_fees=TradingFees('USD'))


@pytest.mark.parametrize('mode',['none','annual_target','rvol_cap'])
def test_mixed_security_fees_and_transfers_reconcile(mode):
    d,p=daily(end='2025-01-08')
    p['A']=np.linspace(100,200,len(p))
    slow_d=pd.DataFrame({'selected_asset':'B'},index=pd.date_range('2023-12-31','2024-12-31',freq='ME'))
    # Match actual US month-end sessions; schedules use actual post-signal sessions.
    fast=ModelInput('fast',d,p,p,'SPY',p.copy())
    slow=ModelInput('slow',slow_d,p,p)
    kwargs=dict(sleeve_rebalance_mode=mode,rebalance_sleeve='fast',rebalance_cap=.51,rebalance_target=.5,tax_enabled=True)
    r=run_portfolio_backtest({'fast':(.5,fast),'slow':(.5,slow)},10000,trading_fees=TradingFees('USD'),**kwargs)
    for book,label in [('pre_tax','pre-tax'),('after_tax','after-tax')]:
        count=0
        for _,row in r.audit.iterrows():
            for order in row.get('security_trades',[]):
                if order.get('book',row.get('book'))==label:
                    assert order['fee']==5
                    count+=1
        assert totals(r)[book]==5*count
    if mode!='none':
        assert 'portfolio transfer' in set(r.audit.sleeve)
        assert r.daily.pre_tax_fee.iloc[-1]==0 # no fabricated terminal sale
    np.testing.assert_allclose(r.sleeve_nav.sum(axis=1),r.daily.pre_tax_value)
