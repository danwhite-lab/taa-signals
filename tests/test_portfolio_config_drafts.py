from copy import deepcopy
import pytest
from haa.portfolio_config import backtest_portfolio_config, deep_history_portfolio_config


def payload():
    return {'version':1,'name':'Fake draft','sleeves':[{'model':'Buy and Hold SPY','weight':90.}], 'total_ils':100.,'ils_per_usd':4.}


def test_save_only_validation_preserves_non_100_numbers_and_strict_readers():
    value=payload(); original=deepcopy(value); models={'Buy and Hold SPY':object()}
    cleaned, capital=backtest_portfolio_config(value,models,require_total=False)
    assert cleaned[0]['weight']==90.
    assert capital==25.
    assert value==original
    with pytest.raises(ValueError,match='total 100%'):
        backtest_portfolio_config(value,models)
    with pytest.raises(ValueError,match='total 100%'):
        deep_history_portfolio_config(value,models,{})


@pytest.mark.parametrize('patch',[{'sleeves':[]},{'sleeves':[{'model':'Unknown','weight':90}]},
    {'sleeves':[{'model':'Buy and Hold SPY','weight':0}]},{'sleeves':[{'model':'Buy and Hold SPY','weight':float('nan')}]},
    {'total_ils':0},{'ils_per_usd':0},{'version':2}])
def test_draft_save_does_not_relax_other_validation(patch):
    with pytest.raises(ValueError):
        backtest_portfolio_config({**payload(),**patch},{'Buy and Hold SPY':object()},require_total=False)


@pytest.mark.parametrize('fields',[{}, {'total_ils':None,'ils_per_usd':None}, {'total_ils':100.,'ils_per_usd':4.}])
def test_optional_capital_fx_only_for_explicit_consumers(fields):
    value={'version':1,'sleeves':[{'model':'Buy and Hold SPY','weight':100.}],**fields}
    original=deepcopy(value);models={'Buy and Hold SPY':object()}
    rows,capital=backtest_portfolio_config(value,models,require_capital_fx=False)
    assert capital is None and rows[0]['weight']==100.
    assert value==original
    if fields.get('total_ils'):
        assert backtest_portfolio_config(value,models)[1]==25.
    else:
        with pytest.raises(ValueError,match='Saved capital and FX rate must be positive and finite.'):
            backtest_portfolio_config(value,models)
