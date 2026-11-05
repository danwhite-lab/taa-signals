"""Deterministic actual-ETF-shaped fixtures, never live provider requests."""
from copy import deepcopy
import csv
import io
import json
from unittest.mock import Mock
import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from test_api import client, module
from test_private_api import signed_in, HEADERS
from server import backtest as single, backtest_multi as multi, compare, cache, signals, usd_equivalents as usd
from haa.model_catalog import definition_for_label
from haa.comparison import ModelInput, compare_models
from haa.engine import run_backtest
from haa.portfolio_backtest import run_portfolio_backtest
from haa.backtest_options import result_metrics


@pytest.fixture
def market(monkeypatch, signed_in):
    calls=[]
    def load(selected, daily_bars=False):
        strategy=selected.model_class()
        assets=tuple(dict.fromkeys((*getattr(strategy,"data_assets",single.ASSETS),getattr(strategy,'benchmark_asset','SPY'))))
        local=any(a.endswith('_IL') or a=='CSPX_IL' for a in assets)
        dates=pd.bdate_range('2004-01-01' if local else '2000-01-03','2005-12-30')
        t=np.arange(len(dates))
        prices=pd.DataFrame({a:100*np.exp(t*.0001*(1+sum(map(ord,a))%5)+np.sin(t/47)*.015) for a in assets},index=dates)
        metadata=pd.DataFrame({'source':'deterministic test fixture','identifier':assets,'price_field':'Adj Close'},index=pd.Index(assets,name='asset'))
        calls.append(assets)
        return (prices,metadata,[],prices*.999) if daily_bars else (prices,metadata,[])
    monkeypatch.setattr(signals,'load_inputs',load)
    monkeypatch.setattr(cache,'cache_client',Mock(side_effect=RuntimeError('No remote test cache')))
    monkeypatch.setattr(single,'RESULTS',cache.ResultCache())
    monkeypatch.setattr(compare,'RESULTS',cache.ResultCache())
    return calls


def post(body):
    return client.post('/api/backtest',headers=HEADERS,json={'initial':10000,'tax_enabled':False,'fees_enabled':False,**body})


def test_explicit_mapping_cash_retreat_and_unsupported_no_substitution():
    selected=usd.resolve('Century Momentum Move to Cash Israel')
    assert selected.label=='Century Momentum Move to Cash'
    assert selected.execution_currency=='USD'
    assert selected.model_class.defensive_asset=='BIL'
    for label in ['A-RVol Shifter V3 Cash-Only Israel','A-RVol V3 US Signals / TASE — 1x Middle','TA-125 Smart Momentum']:
        with pytest.raises(HTTPException) as exc: usd.resolve(label)
        assert exc.value.status_code==400 and label in exc.value.detail
    for source,item in usd.REGISTRY['mappings'].items():
        assert usd.resolve(source).execution_currency=='USD'
    assert 'DAILY' in usd.REGISTRY['mappings']['Buy and Hold Nasdaq-100 x3 Monthly Israel']['note']
    assert usd.resolve('Buy and Hold World Value Israel').model_class.holding_asset=='IVLU'


def test_options_extend_dates_preserve_original_us_signal_assets_and_default(market):
    normal=client.get('/api/backtest/options',params={'label':'HAA-Simple Israel'},headers=HEADERS)
    mapped=client.get('/api/backtest/options',params={'label':'HAA-Simple Israel','usd_equivalents':'true'},headers=HEADERS)
    assert normal.status_code==mapped.status_code==200,(normal.text,mapped.text)
    assert normal.json()['currency']=='ILS' and 'usd_equivalents' not in normal.json()
    assert mapped.json()['currency']=='USD'
    assert mapped.json()['bounds']['start_min'] < normal.json()['bounds']['start_min']
    assert set(definition_for_label('HAA-Simple Israel').model_class.signal_assets).issubset(market[-1])
    assert not any(a.endswith('_IL') for a in market[-1])


def test_single_portfolio_compare_parity_cache_separation_and_exports(market, monkeypatch):
    original='HAA-Simple Israel'
    settings={'usd_equivalents':True,'start':'2002-01-01','end':'2005-11-30'}
    result=post({'label':original,**settings})
    assert result.status_code==200,result.text
    one=result.json()
    portfolio=post({'mode':'portfolio','sleeves':[{'id':1,'model':original,'weight':100}],**settings})
    assert portfolio.status_code==200,portfolio.text
    two=portfolio.json()
    assert one['currency']==two['currency']=='USD'
    assert one['metrics']['pre_tax']==pytest.approx(two['metrics']['pre_tax'],rel=1e-10,abs=1e-10)
    comparison=client.post('/api/compare',headers=HEADERS,json={'mode':'models','models':[original,'HAA-Simple'],'initial':10000,'tax_enabled':False,**settings})
    assert comparison.status_code==200,comparison.text
    comp=comparison.json()
    assert comp['usd_equivalents']['mappings'][0]['resolved']=='HAA-Simple'
    cagr=next(row for row in comp['tables']['summary_pre']['rows'] if row['metric']=='CAGR')
    assert cagr[original]==pytest.approx(one['metrics']['pre_tax']['CAGR'],rel=1e-10)
    assert cagr['HAA-Simple']==pytest.approx(cagr[original],rel=1e-10)
    cached=post({'label':original,**settings}).json()
    assert cached['cache']['key']==one['cache']['key']
    ordinary=post({'label':'HAA-Simple', 'start':settings['start'],'end':settings['end']}).json()
    assert ordinary['cache']['key']!=one['cache']['key']
    assert ordinary['metrics']==one['metrics']
    explicit_off=post({'label':'HAA-Simple','usd_equivalents':False,'start':settings['start'],'end':settings['end']}).json()
    assert explicit_off['cache']['key']==ordinary['cache']['key'] and 'usd_equivalents' not in explicit_off
    for response,endpoint in [(one,'backtest'),(two,'backtest'),(comp,'compare')]:
        assert response['usd_equivalents']['mapping_version']==usd.VERSION
        download=client.get(f'/api/{endpoint}/download',headers=HEADERS,params={'key':response['cache']['key'],'kind':'usd-equivalents'})
        assert download.status_code==200,download.text
        rows=list(csv.DictReader(io.StringIO(download.text)))
        assert rows and all(r['currency']=='USD' for r in rows)
    audit=client.get('/api/backtest/download',headers=HEADERS,params={'key':one['cache']['key'],'kind':'audit'})
    assert audit.status_code==200 and 'usd-equivalents' in audit.text and 'usd_mapping_version' in audit.text
    records=[{'id':'one','payload':{'version':1,'name':'one','sleeves':[{'model':original,'weight':100}]}},
             {'id':'two','payload':{'version':1,'name':'two','sleeves':[{'model':original,'weight':100}]}}]
    before=deepcopy(records)
    monkeypatch.setattr(module.private_api,'portfolios',lambda session:records)
    response=client.post('/api/compare',headers=HEADERS,json={'mode':'portfolios','portfolio_ids':['one','two'],'initial':10000,'tax_enabled':False,**settings})
    assert response.status_code==200,response.text
    assert response.json()['usd_equivalents']['currency']=='USD' and records==before


def test_all_sleeves_kept_and_unsupported_refused_before_loading(market):
    prior=len(market)
    response=post({'mode':'portfolio','usd_equivalents':True,'sleeves':[{'id':1,'model':'HAA-Simple Israel','weight':75},{'id':2,'model':'TA-125 Smart Momentum','weight':25}]})
    assert response.status_code==400 and 'TA-125' in response.text
    assert len(market)==prior
    response=post({'mode':'portfolio','usd_equivalents':True,'sleeves':[{'id':1,'model':'HAA-Simple Israel','weight':75},{'id':2,'model':'Buy and Hold Gold Israel','weight':25}]})
    assert response.status_code==200,response.text
    info=response.json()['usd_equivalents']
    assert len(info['mappings'])==2
    assert response.json()['settings']['sleeves'][0]['weight']==75
    deep=post({'mode':'deep','usd_equivalents':True,'sleeves':[{'id':1,'model':'century_momentum','weight':100}]})
    assert deep.status_code==400


def test_shared_availability_and_auth(market, monkeypatch):
    response=client.post('/api/usd-equivalents/options',headers=HEADERS,json={'mode':'portfolio','models':['HAA-Simple Israel','Buy and Hold Gold Israel']})
    assert response.status_code==200,response.text
    assert response.json()['currency']=='USD' and len(response.json()['mappings'])==2
    assert client.post('/api/usd-equivalents/options',json={'mode':'models','models':['HAA-Simple Israel']}).status_code==401
    records=[{'id':'one','payload':{'version':1,'name':'one','sleeves':[{'model':'HAA-Simple Israel','weight':100}]}}]
    monkeypatch.setattr(module.private_api,'portfolios',lambda session:records)
    response=client.post('/api/usd-equivalents/options',headers=HEADERS,json={'mode':'portfolios','models':['TA-125 Smart Momentum'],'portfolio_ids':['one']})
    assert response.status_code==200,response.text
    assert len(response.json()['mappings'])==1
    assert response.json()['fees']==usd.WORDS['compare_fees']


@pytest.mark.parametrize('tax,deposit,fees',[(False,1000,False),(True,0,False),(True,1000,True)])
def test_single_sleeve_engine_parity_with_cashflows_tax_and_usd_tariff(market,tax,deposit,fees):
    settings={'usd_equivalents':True,'initial':10000,'tax_enabled':tax,'fees_enabled':fees,'monthly_contribution':deposit,'start':'2002-01-01','end':'2005-11-30'}
    first=post({'label':'HAA-Simple Israel',**settings})
    second=post({'mode':'portfolio','sleeves':[{'id':1,'model':'HAA-Simple Israel','weight':100}],**settings})
    assert first.status_code==second.status_code==200,(first.text,second.text)
    for column in ('pre_tax','after_tax','benchmark'):
        assert first.json()['metrics'][column]==pytest.approx(second.json()['metrics'][column],rel=1e-9,abs=1e-9)
    if fees:
        assert first.json()['fees']['currency']=='USD'
        assert first.json()['engine_parameters']['trading_fees']['usd_flat']==5


def test_mapping_version_changes_cache_identity(market, monkeypatch):
    body={'label':'HAA-Simple Israel','usd_equivalents':True,'start':'2002-01-01','end':'2005-11-30'}
    first=post(body).json()
    monkeypatch.setattr(usd,'VERSION','changed-source-version')
    second=post(body).json()
    assert first['cache']['key']!=second['cache']['key']
    assert second['usd_equivalents']['mapping_version']=='changed-source-version'
