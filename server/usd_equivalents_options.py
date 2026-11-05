"""Actual executable USD date bounds shared by portfolio and Compare selectors."""
from types import SimpleNamespace
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from . import usd_equivalents as usd, backtest_multi as multi, backtest as base
from haa.portfolio_config import backtest_portfolio_config


class OptionsRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    usd_equivalents: bool = True
    mode: Literal['portfolio','models','portfolios']
    models: list[str]=Field(default_factory=list,max_length=100)
    portfolio_ids: list[str]=Field(default_factory=list,max_length=100)
    method: Literal['monthly','daily']='monthly'


def availability(request, records):
    labels=[] if request.mode=='portfolios' else list(request.models)
    if request.mode=='portfolios':
        for identifier in request.portfolio_ids:
            row=next((r for r in records if str(r.get('id'))==identifier),None)
            if row is None: raise HTTPException(400,usd.WORDS['missing_saved'])
            try:
                sleeves,_=backtest_portfolio_config(row.get('payload'),multi.MODELS,require_capital_fx=False)
            except (ValueError, TypeError, OverflowError, KeyError) as exc:
                raise HTTPException(400,str(exc)) from None
            labels.extend(s['model'] for s in sleeves)
        currencies={base.definition(label).execution_currency for label in labels}
        if len(currencies)>1: raise HTTPException(400,usd.WORDS['mixed_history'])
    labels=list(dict.fromkeys(labels))
    if not labels: raise HTTPException(400,usd.WORDS['select_history'])
    try:
        mapping=usd.mappings(labels) if request.usd_equivalents else []
        descriptor=SimpleNamespace(sleeves=[multi.Sleeve(id=i,model=label,weight=100/len(labels)) for i,label in enumerate(labels,1)],
                                   usd_equivalents=request.usd_equivalents,daily_valuation=request.method=='daily')
        models,version,_,warnings,benchmark,_=multi.live_inputs(descriptor)
        currencies={model.execution_currency for _,model in models.values()}
        if len(currencies)!=1: raise ValueError(usd.WORDS['mixed_history'])
        common=None
        for _,model in models.values():
            result=base.run_backtest(model.decisions,model.monthly_prices,100000.,daily_prices=model.daily_prices,
                                    benchmark_asset=model.benchmark_asset,daily_open_prices=model.daily_open_prices)
            dates=(result.daily if request.method=='daily' and result.daily is not None else result.monthly).index
            common=dates if common is None else common.intersection(dates)
        if common is None or common.empty: raise ValueError(usd.WORDS['no_common'])
        return {'currency':next(iter(currencies)),'bounds':{'start_min':str(common.min().date()),'start_max':str(common.max().date()),
                    'end_min':str(common.min().date()),'end_max':str(common.max().date())},
                'mapping_version':usd.VERSION,'mappings':mapping,'data_version':version,'benchmark':benchmark,'warnings':warnings,
                'fees':usd.WORDS['backtest_fees' if request.mode=='portfolio' else 'compare_fees']}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400,str(exc)) from None
