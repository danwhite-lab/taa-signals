import numpy as np
import pandas as pd
import pytest
from haa.valuation_gaps import valuation_prices, require_execution_prices, MAX_VALUATION_GAP_SESSIONS
from haa.market_sessions import us_equity_sessions


def prices():
    days=us_equity_sessions('2024-01-02','2024-01-31')
    return pd.DataFrame({'FAKE':np.arange(len(days))+100.},index=days)


@pytest.mark.parametrize('length',[1,2,MAX_VALUATION_GAP_SESSIONS])
def test_only_prior_real_value_used_and_source_unchanged(length):
    source=prices();days=source.index[3:3+length];source.loc[days,'FAKE']=np.nan
    source.iloc[3+length,0]=9999.
    before=source.copy(deep=True)
    marked,warnings=valuation_prices(source,source.index,['FAKE'])
    assert marked.loc[days,'FAKE'].eq(source.iloc[2,0]).all()
    assert warnings and all(str(day.date()) in warnings[0] for day in days)
    assert 'FAKE' in warnings[0] and 'price carried forward' in warnings[0]
    pd.testing.assert_frame_equal(source,before,check_exact=True)
    with pytest.raises(ValueError,match='execution price unavailable.*'+str(days[0].date())):
        require_execution_prices(marked,days[0],['FAKE'])


@pytest.mark.parametrize('case',['four','first','last','zero','negative','infinite','cropped-long'])
def test_invalid_or_unbounded_gaps_still_fail(case):
    source=prices()
    if case in ('four','cropped-long'):source.iloc[3:7,0]=np.nan
    elif case=='first':source.iloc[0,0]=np.nan
    elif case=='last':source.iloc[-1,0]=np.nan
    else:source.iloc[3,0]={'zero':0.,'negative':-1.,'infinite':np.inf}[case]
    sessions=source.index[4:5] if case=='cropped-long' else source.index
    with pytest.raises(ValueError):valuation_prices(source,sessions,['FAKE'])


def test_unchanged_history_is_exact_and_has_no_warning_metadata():
    source=prices();marked,warnings=valuation_prices(source,source.index,['FAKE'])
    pd.testing.assert_frame_equal(marked,source,check_exact=True)
    assert not warnings and not marked.attrs


def test_daily_valuation_gap_does_not_create_a_trade_and_execution_gap_stops():
    from haa.engine import run_backtest
    source=prices();source['SPY']=100.;source['OTHER']=100.
    decisions=pd.DataFrame({'target_weights':[{'FAKE':1.}]*len(source),'selected_asset':'FAKE'},index=source.index)
    decisions.attrs['execution_frequency']='daily'
    opens=source.copy()
    baseline=run_backtest(decisions,source,1000.,daily_prices=source,daily_open_prices=opens)
    day=source.index[4];source.loc[day,'FAKE']=np.nan
    result=run_backtest(decisions,source,1000.,daily_prices=source,daily_open_prices=opens)
    assert result.daily.loc[day,'pre_tax_value']==pytest.approx(result.daily.iloc[2].pre_tax_value)
    assert list(result.audit.execution_date)==list(baseline.audit.execution_date)
    assert result.daily.iloc[-1].pre_tax_value==pytest.approx(baseline.daily.iloc[-1].pre_tax_value)
    assert result.price_warnings and str(day.date()) in result.price_warnings[0]
    decisions.loc[source.index[3]:,'target_weights']=pd.Series([{'OTHER':1.}]*(len(source)-3),index=source.index[3:])
    with pytest.raises(ValueError,match='FAKE.*execution price unavailable.*'+str(day.date())):
        run_backtest(decisions,source,1000.,daily_prices=source,daily_open_prices=opens)


def test_monthly_daily_book_does_not_execute_on_a_carried_price():
    from test_mixed_portfolio import fixture
    from haa.mixed_portfolio import run_mixed_portfolio
    from dataclasses import replace
    fast,slow,source=fixture()
    opens=source.copy();slow=replace(slow,daily_open_prices=opens)
    day=pd.Timestamp('2024-02-01');source.loc[day,'B']=np.nan
    with pytest.raises(ValueError,match='B.*execution price unavailable.*2024-02-01'):
        run_mixed_portfolio({'fast':(.5,fast),'slow':(.5,slow)},1000.)


def test_fee_transfer_replay_uses_flagged_valuation_marks_without_changing_orders():
    from test_mixed_portfolio import fixture
    from haa.mixed_portfolio import run_mixed_portfolio
    from haa.trading_fees import TradingFees
    fast,slow,source=fixture()
    sleeves={'fast':(.5,fast),'slow':(.5,slow)}
    options=dict(trading_fees=TradingFees('USD'),sleeve_rebalance_mode='rvol_cap',
                 rebalance_sleeve='fast',rebalance_cap=.6,rebalance_target=.4)
    baseline=run_mixed_portfolio(sleeves,1000.,**options)
    day=source.index[10];source.loc[day,'B']=np.nan
    result=run_mixed_portfolio(sleeves,1000.,**options)
    assert np.isfinite(result.daily.pre_tax_value).all()
    pd.testing.assert_frame_equal(result.daily,baseline.daily,check_exact=True)
    pd.testing.assert_frame_equal(result.audit,baseline.audit,check_exact=True)
    assert result.price_warnings and str(day.date()) in result.price_warnings[0]
