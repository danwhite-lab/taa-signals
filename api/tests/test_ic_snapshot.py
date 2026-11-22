"""Real refresh/reader/adapter parity using frozen public provider fixtures only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from test_api import client
from test_cache_cron import snapshot_store
from haa import tase_data, data
from haa.market_sessions import us_equity_sessions, tase_equity_sessions
from haa.model_catalog import definition_for_label
from server import cron, signals, market_cache, input_cache, today


@pytest.fixture
def extended_bundle(monkeypatch):
    definition = definition_for_label('Inflation Compass Standard Israel')
    strategy = definition.model_class()
    now = pd.Timestamp.now(tz='Asia/Jerusalem').tz_localize(None).normalize()
    start, end = now - pd.DateOffset(years=10), now - pd.Timedelta(days=1)
    us = us_equity_sessions(str(start.date()), str(end.date()))
    local = tase_equity_sessions(str(start.date()), str(end.date()))
    assets = {a: tase_data.TASE_ISRAEL_ASSET_IDS[a] for a in strategy.data_assets if a in tase_data.TASE_ISRAEL_ASSET_IDS}
    provider = {}
    for index, (asset, identifier) in enumerate(assets.items()):
        dates = local[local >= now - pd.DateOffset(years=2)] if asset == 'IEF_IL' else local
        values = np.arange(len(dates), dtype=float) + 100 + index
        frame = pd.DataFrame({'Adj Close':values, 'Close':values + 7}, index=dates.as_unit('ns').rename('Date'))
        frame.iloc[10, 0] = np.nan  # A missing adjusted observation must stay missing.
        provider[identifier] = frame
    calls = []
    class Security:
        def __init__(self, identifier): self.identifier = identifier
        def history(self, years):
            calls.append(('history',self.identifier,years))
            return provider[self.identifier].loc[now - pd.DateOffset(years=years):].copy()
    def eod(self, identifier, ptype):
        identifier = identifier.lstrip('0')
        calls.append(('published',identifier,ptype))
        frame = provider[identifier].rename(columns={'Adj Close':'Adjusted Closing Price','Close':'Closing Price (0.01 ILS)'})
        return 'Official fixture\nActual available dates\n' + frame.to_csv(date_format='%d/%m/%Y',index_label='Date')
    monkeypatch.setattr(tase_data, '_default_security_factory', Security)
    monkeypatch.setattr('tasekit.api.TaseClient.fetch_eod_csv', eod)
    yahoo = tuple(a for a in strategy.data_assets if a not in (*assets,*cron.FRED_ASSETS))
    closes = pd.DataFrame({a:100 + np.arange(len(us),dtype=float) * (.01 + i*.001) for i,a in enumerate(yahoo)},index=us)
    opens = closes * .999
    macro = pd.DataFrame({'T5YIE':2 + .1*np.sin(np.arange(len(us))/60)},index=us)
    def bars(mapping):
        calls.append(('yahoo',tuple(mapping)))
        return closes.loc[:,list(mapping)].copy(), opens.loc[:,list(mapping)].copy()
    def prices(mapping, **kwargs):
        calls.append(('yahoo-close',tuple(mapping)))
        return closes.loc[:,list(mapping)].copy()
    def fred(symbols):
        calls.append(('fred',tuple(symbols)))
        return macro.loc[:,list(symbols)].copy()
    monkeypatch.setattr(data,'download_yahoo_daily_bars',bars)
    monkeypatch.setattr(data,'download_yahoo_prices',prices)
    monkeypatch.setattr(data,'download_fred_series',fred)
    original = signals.live_inputs(definition)
    monkeypatch.setattr(cron,'yahoo_universe',lambda:list(yahoo))
    monkeypatch.setattr(cron,'fred_universe',lambda:['T5YIE'])
    monkeypatch.setattr(tase_data,'TASE_ISRAEL_ASSET_IDS',assets)
    monkeypatch.setenv('CRON_SECRET','fixture')
    monkeypatch.setattr(cron,'cache_client',lambda:object())
    records = {}
    def write(_client,symbol,source,rows):
        records[source,symbol]={'symbol':symbol,'rows':deepcopy(rows),'updated_at':datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(cron,'write_prices',write)
    response=client.get('/api/cron/refresh-prices',headers={'Authorization':'Bearer fixture'})
    assert response.status_code == 200 and response.json()['success'], response.text
    assert any(c[0]=='history' and c[-1]==5 for c in calls)
    assert any(c[0]=='published' for c in calls)
    assert len({r['rows'][0]['refresh_id'] for r in records.values()}) == 1
    snapshot_store(monkeypatch,records)
    # Exercise signals.load_inputs rather than unrelated shared memo storage.
    monkeypatch.setattr(input_cache,'inputs',lambda strategy,daily_bars,compute:compute())
    calls.clear()
    return definition, records, original, calls, now


@pytest.mark.parametrize('label',['Inflation Compass Standard Israel','Inflation Compass Fast (40-day) Israel','Inflation Compass Steady (80-day) Israel'])
def test_ic_saved_eight_year_bundle_exactly_matches_original_loader_without_provider_calls(extended_bundle,label):
    definition, records, original, calls, now = extended_bundle
    definition=definition_for_label(label)
    result=signals.load_inputs(definition)
    assert not calls and not result[2]
    assert result[0].attrs['input_source']['source']=='daily_snapshot'
    plain=result[0].copy();plain.attrs={}
    pd.testing.assert_frame_equal(plain,original[0],check_exact=True,check_freq=False)
    pd.testing.assert_frame_equal(result[1],original[1],check_exact=True)
    assert plain['XLE_IL'].first_valid_index() < now-pd.DateOffset(years=5)
    assert plain['XLE_IL'].first_valid_index() >= now-pd.DateOffset(years=8)
    assert plain['IEF_IL'].first_valid_index() >= now-pd.DateOffset(years=2)
    assert plain['IEF_IL'].isna().any()
    # Also prove the original decisions and Today output are unchanged.
    pd.testing.assert_frame_equal(definition.model_class().decisions(plain),definition.model_class().decisions(original[0]),check_exact=True)
    assert today.build_sleeve(definition,plain,result[1],[],False)==today.build_sleeve(definition,original[0],original[1],[],False)


@pytest.mark.parametrize('damage',['missing','default_window','truncated','mixed','stale','field','index_metadata'])
def test_ic_rejects_entire_invalid_bundle_and_calls_full_original_loader(extended_bundle,monkeypatch,damage):
    definition,records,original,calls,now=extended_bundle
    key=(cron.tase_snapshot_source(8),'XLE_IL')
    record=records[key]
    if damage=='missing':del records[key]
    elif damage=='default_window':records[key]=deepcopy(records[cron.TASE_SOURCE,'XLE_IL'])
    elif damage=='truncated':
        header=deepcopy(record['rows'][0]);record['rows']=record['rows'][-100:]
        record['rows'][0].update({k:header[k] for k in ['refresh_id','index_name','index_unit','tase_window']})
    elif damage=='mixed':record['rows'][0]['refresh_id']='other-refresh'
    elif damage=='stale':record['updated_at']=(datetime.now(timezone.utc)-timedelta(hours=37)).isoformat()
    elif damage=='field':record['rows'][0]['field']='Close'
    else:record['rows'][0]['index_name']='Wrong index metadata'
    live=MagicMock(wraps=signals.live_inputs)
    monkeypatch.setattr(signals,'live_inputs',live)
    result=signals.load_inputs(definition)
    live.assert_called_once_with(definition,daily_bars=False)
    assert calls and result[2]==[market_cache.FALLBACK_WARNING]
    plain=result[0].copy();plain.attrs={}
    pd.testing.assert_frame_equal(plain,original[0],check_exact=True)
    pd.testing.assert_frame_equal(result[1],original[1],check_exact=True)
    assert result[0].attrs['input_source']['snapshot_fallback'] is True


def test_ic_live_refresh_still_bypasses_both_caches(extended_bundle,monkeypatch):
    definition,_,original,calls,_=extended_bundle
    monkeypatch.setattr(input_cache,'inputs',lambda *a,**kw:pytest.fail('Live Refresh read the memo'))
    monkeypatch.setattr(market_cache,'read_snapshot',lambda *a:pytest.fail('Live Refresh read saved inputs'))
    with signals.input_policy(force_live=True):
        result=signals.load_inputs(definition)
    assert calls and result[0].attrs['input_source']['source']=='live'
    plain=result[0].copy();plain.attrs={}
    pd.testing.assert_frame_equal(plain,original[0],check_exact=True)
    assert not result[2]


def test_ic_overnight_snapshot_uses_original_rolling_cutoff_and_source_dates(extended_bundle,monkeypatch):
    definition,records,_,calls,_=extended_bundle
    real_timestamp=pd.Timestamp
    class Tomorrow(real_timestamp):
        @classmethod
        def now(cls,tz=None):
            return real_timestamp.now(tz=tz)+pd.Timedelta(days=1)
    monkeypatch.setattr(pd,'Timestamp',Tomorrow)
    expected=signals.live_inputs(definition)
    calls.clear()
    result=signals.load_inputs(definition)
    assert not calls and not result[2]
    plain=result[0].copy();plain.attrs={}
    pd.testing.assert_frame_equal(plain,expected[0],check_exact=True,check_freq=False)
    pd.testing.assert_frame_equal(result[1],expected[1],check_exact=True)


def test_private_account_inputs_still_bypass_every_public_snapshot(monkeypatch):
    from dataclasses import replace
    from haa.my_funds import PREFIX
    definition=definition_for_label('Inflation Compass Standard Israel')
    private_class=type('PrivateFixture',(definition.model_class,),{'data_assets':(PREFIX+'fixture',)})
    definition=replace(definition,model_class=private_class)
    original=(pd.DataFrame({'private':[1.]}),pd.DataFrame(),[])
    live=MagicMock(return_value=original)
    monkeypatch.setattr(signals,'live_inputs',live)
    monkeypatch.setattr(input_cache,'inputs',lambda *a,**kw:pytest.fail('Private account entered public memo'))
    monkeypatch.setattr(market_cache,'read_snapshot',lambda *a:pytest.fail('Private account read public prices'))
    assert signals.load_inputs(definition) is original
    live.assert_called_once_with(definition,daily_bars=False)
