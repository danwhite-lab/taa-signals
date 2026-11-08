"""Published no-trade prices through the real loader and unchanged engines."""
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
import pandas as pd
import pytest
from server import backtest as base, backtest_multi as multi, signals, cache, input_cache, market_cache
from haa import tase_data
from haa.market_sessions import us_equity_sessions, tase_equity_sessions
from haa.model_catalog import definition_for_label


def test_union_retains_published_utilities_close_and_matches_single_ic(monkeypatch):
    us=us_equity_sessions('2021-01-04','2022-12-30')
    local=tase_equity_sessions('2021-01-04','2022-12-30')
    entry=pd.Timestamp('2022-11-02')
    published=[]
    def yahoo(mapping,**kwargs):
        return pd.DataFrame({a:100*np.exp(np.arange(len(us))*(-.0003 if a=='SPY' else .0002)) for a in mapping},index=us)
    def fred(assets):
        return pd.DataFrame({a:3+np.arange(len(us))*.0001 for a in assets},index=us)
    def eod(security_id,**kwargs):
        published.append((security_id,kwargs))
        records=[]
        for i,day in enumerate(local):
            no_trade=security_id=='1150507' and day==entry
            value=2671. if security_id=='1150507' else 100+i*.01
            records.append(f'{day:%d/%m/%Y},{value:.2f},{value:.2f},{"" if no_trade else value},{"" if no_trade else value},{0 if no_trade else 1}')
        csv='Published valuations\n2021–2022\nDate,Closing Price,Adjusted Closing Price,High,Low,Volume\n'+'\n'.join(records)
        # Includes the actual reported no-trade fixture, with no high/low bars.
        if security_id=='1150507':assert '02/11/2022,2671.00,2671.00,,,0' in csv
        return tase_data.parse_published_eod_closes(csv)
    class Security:
        def history(self,**kwargs):
            pytest.fail('Years-carrying ETF runs must retain published no-trade valuations')
    monkeypatch.setattr(signals.data,'download_yahoo_prices',yahoo)
    monkeypatch.setattr(signals.data,'download_fred_series',fred)
    monkeypatch.setattr(tase_data,'_default_security_factory',lambda _:Security())
    monkeypatch.setattr(tase_data,'download_published_eod_closes',eod)
    monkeypatch.setattr(market_cache,'model_inputs',lambda *a,**kw:pytest.fail('Must bypass the short daily snapshot'))
    monkeypatch.setattr(input_cache,'RESULTS',cache.ResultCache())
    monkeypatch.setattr(base,'RESULTS',cache.ResultCache())
    monkeypatch.setattr(cache,'cache_client',Mock(side_effect=RuntimeError('Offline cache')))
    request=multi.Inputs(mode='portfolio',initial=10000,tax_enabled=False,fees_enabled=False,
        sleeves=[multi.Sleeve(id=1,model='Inflation Compass Standard Israel',weight=75),multi.Sleeve(id=2,model='Buy and Hold SPY Israel',weight=25)])
    models,_,metadata,_,_,_=multi.live_inputs(request)
    ic=next(model for key,(_,model) in models.items() if key.startswith('Inflation Compass'))
    assert ic.daily_prices.loc[entry,'XLU_IL']==2671.
    assert ic.decisions.loc['2022-10-31','target_weights']=={'XLU_IL':1.}
    single_prices,single_metadata,_,_=base.load_data(definition_for_label('Inflation Compass Standard Israel'))
    pd.testing.assert_series_equal(ic.daily_prices.XLU_IL.dropna(),single_prices.XLU_IL.dropna())
    assert single_metadata.loc['XLU_IL','source']==metadata.loc['XLU_IL','source']
    result=base.run_backtest(ic.decisions,ic.monthly_prices,10000,daily_prices=ic.daily_prices,benchmark_asset=ic.benchmark_asset)
    assert entry in pd.DatetimeIndex(result.audit.execution_date)
    value=multi.run(request,'published-close-regression')
    assert value['monthly_rows']>0
    assert all(kwargs=={'history_years':8} for _,kwargs in published)
    assert {'1150507','1145903','1159193','1150366','1159268','1159250'} <= {sid for sid,_ in published}
    for asset in ('XLU_IL','XLE_IL','XLK_IL','XLP_IL','IEF_IL','CSPX_IL'):
        assert 'published no-trade valuations retained (not guaranteed fills)' in metadata.loc[asset,'source']


@pytest.mark.parametrize('years',[[],[8],[6,10]])
def test_union_history_years_is_class_and_instance_attribute_only_when_needed(monkeypatch,years):
    classes=[type('Model'+str(i),(),{'data_assets':('SPY',),'tase_history_years':value}) for i,value in enumerate(years)]
    classes.append(type('DefaultModel',(),{'data_assets':('SPY',)}))
    definitions=[SimpleNamespace(model_class=cls,execution_currency='USD') for cls in classes]
    monkeypatch.setattr(base,'definition',lambda label:definitions[int(label)])
    def capture(descriptor,**kwargs):
        cls=descriptor.model_class
        assert isinstance(cls,type)
        if years: assert cls.tase_history_years==cls().tase_history_years==max(years)
        else: assert not hasattr(cls,'tase_history_years') and not hasattr(cls(),'tase_history_years')
        raise RuntimeError('Descriptor inspected')
    monkeypatch.setattr(signals,'load_inputs',capture)
    request=SimpleNamespace(sleeves=[multi.Sleeve(id=i+1,model=str(i),weight=100/len(definitions)) for i in range(len(definitions))])
    with pytest.raises(RuntimeError,match='Descriptor inspected'):multi.live_inputs(request)


def test_same_assets_different_history_windows_cannot_share_input_cache(monkeypatch):
    monkeypatch.setattr(input_cache,'RESULTS',cache.ResultCache())
    monkeypatch.setattr(cache,'cache_client',Mock(side_effect=RuntimeError('Offline cache')))
    frame=pd.DataFrame({'SPY':[100.]},index=pd.to_datetime(['2022-11-02']))
    metadata=pd.DataFrame({'source':['fixture']},index=['SPY'])
    build=Mock(return_value=(frame,metadata,[]))
    default=SimpleNamespace(data_assets=('SPY',),benchmark_asset='SPY')
    extended=SimpleNamespace(data_assets=('SPY',),benchmark_asset='SPY',tase_history_years=8)
    input_cache.inputs(default,False,build);input_cache.inputs(extended,False,build)
    assert build.call_count==2
    input_cache.inputs(extended,False,build)
    assert build.call_count==2
