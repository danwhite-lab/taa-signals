from copy import deepcopy
import pytest
from haa.portfolio_config import portfolio_transfer_config, backtest_portfolio_config, TRANSFER_ERROR

RVOL='A-RVol Shifter V3 Cash-Only'
MODELS={RVOL:object(),'Buy and Hold SPY':object()}


def saved():
    return {'version':1,'name':'Fake rule portfolio','total_ils':1200,'ils_per_usd':4,
        'sleeves':[{'id':91,'model':'Buy and Hold SPY','weight':80},{'id':777,'model':RVOL,'weight':20}]}


def cap():
    return {'mode':'rvol_cap','sleeve_model':RVOL,'cap_percent':17.5,'target_percent':9.25}


@pytest.mark.parametrize('rule',[None,{'mode':'none'},{'mode':'annual_target'},cap()])
def test_transfer_metadata_roundtrip_leaves_sleeves_capital_fx_unchanged(rule):
    value=saved()
    if rule is not None: value['transfer_rule']=rule
    original=deepcopy(value)
    rows,capital=backtest_portfolio_config(value,MODELS)
    result=portfolio_transfer_config(value,rows)
    assert value==original and capital==300
    assert result['sleeve_rebalance_mode']==('none' if rule is None else rule['mode'])
    if rule and rule['mode']=='rvol_cap':
        assert result==dict(sleeve_rebalance_mode='rvol_cap',rebalance_sleeve=2,rebalance_cap=17.5,rebalance_target=9.25)
    else:
        assert result['rebalance_sleeve'] is None and result['rebalance_cap']==15 and result['rebalance_target']==10


def test_cap_identity_survives_row_reordering_and_arbitrary_saved_ids():
    value={**saved(),'transfer_rule':cap()}
    value['sleeves'].reverse()
    rows,_=backtest_portfolio_config(value,MODELS)
    result=portfolio_transfer_config(value,rows)
    assert result['rebalance_sleeve']==1
    assert rows[0]['model']==RVOL
    assert value['sleeves'][0]['id']==777


@pytest.mark.parametrize('rule',[None,[],{}, {'mode':[]},{'mode':'unknown'},
    {'mode':'rvol_cap'}, {**cap(),'sleeve_model':'Buy and Hold SPY'}, {**cap(),'sleeve_model':'Missing private name'},
    {**cap(),'cap_percent':None}, {**cap(),'cap_percent':float('nan')}, {**cap(),'cap_percent':True},
    {**cap(),'cap_percent':100}, {**cap(),'target_percent':0}, {**cap(),'target_percent':18}])
def test_invalid_stored_rules_are_not_silently_changed(rule):
    with pytest.raises(ValueError,match=TRANSFER_ERROR):
        portfolio_transfer_config({**saved(),'transfer_rule':rule})


def test_missing_or_duplicate_cap_target_is_rejected():
    value={**saved(),'transfer_rule':cap()}
    for rows in ([value['sleeves'][0]],value['sleeves']+[value['sleeves'][1]]):
        with pytest.raises(ValueError,match=TRANSFER_ERROR):
            portfolio_transfer_config({**value,'sleeves':rows})
