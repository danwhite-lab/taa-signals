from io import StringIO
from copy import deepcopy
import pandas as pd
import numpy as np
import pytest
from server.price_warnings import annotate_price_warnings
from test_private_api import signed_in, HEADERS


def test_warning_is_in_public_cached_bundle_and_every_csv_without_changing_values():
    frame=pd.DataFrame({'value':[1.25,2.5]})
    warning='Fake fund (1234567): 2024-01-10 — price carried forward for valuation only.'
    bundle={'public':{},'downloads':{'nav':{'csv':frame.to_csv(),'filename':'nav.csv'},'tax':{'csv':'\n','filename':'tax.csv'}}}
    result=annotate_price_warnings(bundle,[warning,warning])
    assert result['public']['warnings']==result['public']['price_warnings']==[warning]
    for item in result['downloads'].values():assert warning in item['csv']
    actual=pd.read_csv(StringIO(result['downloads']['nav']['csv']),index_col=0)
    pd.testing.assert_frame_equal(actual[['value']],frame,check_exact=True)


def test_no_warning_keeps_existing_bundle_bytes_unchanged():
    bundle={'public':{'warnings':['Existing warning']},'downloads':{'nav':{'csv':'value\n1.23456789\n'}}}
    original=deepcopy(bundle)
    assert annotate_price_warnings(bundle,())==original


@pytest.mark.parametrize('module_name,bundle_kind,path',[
    ('backtest','single-backtest-v1','backtest'),
    ('compare','compare-models-v1','compare'),
    ('research','research-v1','research'),
])
def test_warning_sidecar_download_is_allowed(signed_in,monkeypatch,module_name,bundle_kind,path):
    import importlib
    from test_api import client
    from server.cache import ResultCache
    page=importlib.import_module('server.'+module_name)
    monkeypatch.setattr(page,'RESULTS',ResultCache())
    warning='Example fund (1234567): 2024-01-10 — price carried forward for valuation only.'
    key='a'*64
    page.RESULTS.warm[key]=annotate_price_warnings({'kind':bundle_kind,'public':{},'downloads':{}},[warning])
    response=client.get('/api/'+path+'/download',headers=HEADERS,params={'key':key,'kind':'price-warnings'})
    assert response.status_code==200 and warning in response.text


def test_real_backtest_warning_survives_cache_and_generated_downloads(signed_in,monkeypatch):
    from test_api import client
    from test_signals import fixtures
    from server import backtest as page, cache
    from haa.ic_israel_execution import execution_schedule
    from haa.market_sessions import tase_equity_sessions
    label='Inflation Compass Standard Israel'
    prices,metadata,warnings=fixtures(label)
    selected=page.definition(label);decisions=selected.model_class().decisions(prices)
    entry,exit=next(iter(execution_schedule(decisions,prices,'SPY').values()))
    asset=next(iter(decisions.loc[next(iter(execution_schedule(decisions,prices,'SPY'))),'target_weights']))
    day=tase_equity_sessions(str(entry.date()),str(exit.date()))[2]
    prices.loc[day,asset]=np.nan
    monkeypatch.setattr(page,'RESULTS',cache.ResultCache())
    monkeypatch.setattr(cache,'cache_client',lambda:(_ for _ in ()).throw(RuntimeError('Mock offline')))
    monkeypatch.setattr(page,'load_data',lambda _:(prices,metadata,warnings,None))
    body={'label':label,'tax_enabled':False,'fees_enabled':False}
    response=client.post('/api/backtest',headers=HEADERS,json=body)
    assert response.status_code==200,response.text
    value=response.json()
    assert value['price_warnings'] and str(day.date()) in value['price_warnings'][0]
    assert 'price carried forward' in value['price_warnings'][0]
    again=client.post('/api/backtest',headers=HEADERS,json=body).json()
    assert again['cache']['hit']=='memory' and again['price_warnings']==value['price_warnings']
    assert all(w in again['warnings'] for w in value['price_warnings'])
    for kind in ('audit','price-warnings'):
        result=client.get('/api/backtest/download',headers=HEADERS,params={'key':value['cache']['key'],'kind':kind})
        assert result.status_code==200 and 'price carried forward' in result.text
