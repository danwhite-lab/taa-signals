"""Shared explicit USD mapping for research only; never called by live signals."""
import csv
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path

from fastapi import HTTPException
from haa.constants import ASSETS
from haa.model_catalog import definition_for_label
from haa.strategies.buy_and_hold import BuyAndHoldSPY
from haa.tase_data import TASE_EXECUTION_ASSET_IDS

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT/'data/usd_equivalents.json').read_text())
WORDS = json.loads((ROOT/'web/content/usd-equivalents.json').read_text())
VERSION = hashlib.sha256(json.dumps([REGISTRY, WORDS],sort_keys=True).encode()).hexdigest()


def resolve(label):
    try: original = definition_for_label(label)
    except ValueError: raise HTTPException(400, WORDS['unsupported'].replace('{label}',label)) from None
    if original.execution_currency == 'USD':
        return original
    item = REGISTRY['mappings'].get(label)
    if not item:
        raise HTTPException(400, WORDS['unsupported'].replace('{label}',label))
    if 'model' in item:
        selected = definition_for_label(item['model'])
        if selected.execution_currency != 'USD':
            raise ValueError('USD mapping must resolve to USD.')
        return selected
    ticker = item['ticker']
    strategy = type('USDProxy'+ticker, (BuyAndHoldSPY,), {'name':'USD proxy '+ticker,
        'holding_asset':ticker, 'data_assets':(ticker,), 'market_data_assets':(ticker,), 'benchmark_asset':'SPY'})
    return replace(original, label=strategy.name, model_class=strategy, execution_currency='USD')


def mappings(labels):
    result=[]
    for label in labels:
        selected=resolve(label)
        original=definition_for_label(label)
        assets=getattr(original.model_class,'execution_proxies',{}).values()
        if not assets: assets=getattr(original.model_class,'data_assets',())
        funds=sorted({TASE_EXECUTION_ASSET_IDS[a] for a in assets if a in TASE_EXECUTION_ASSET_IDS})
        result.append({'original':label,'resolved':selected.label,'funds':', '.join(funds),
            'assets':', '.join(getattr(selected.model_class,'data_assets',ASSETS)),
            'caveat':REGISTRY['mappings'].get(label,{}).get('note','Already USD: original implementation retained.'),
            'warning':REGISTRY['mappings'].get(label,{}).get('note','') if REGISTRY['mappings'].get(label,{}).get('prominent') else ''})
    return result


def guard(request, labels):
    if not getattr(request,'usd_equivalents',False): return []
    if getattr(request,'mode',None)=='deep': raise HTTPException(400, WORDS['deep_unsupported'])
    return mappings(labels)  # Resolve every sleeve before any loader or calculation.


def annotate(bundle, rows, request, window, *, compare=False):
    if not rows: return bundle
    public=bundle['public']
    info={'enabled':True,'currency':'USD','mapping_version':VERSION,'mappings':rows,
          'requested':{'start':str(request.start) if request.start else None,'end':str(request.end) if request.end else None},
          'tested':{'start':str(window[0]),'end':str(window[1])},
          'benchmark':WORDS['benchmark'],'fees':WORDS['compare_fees' if compare else 'backtest_fees']}
    public['usd_equivalents']=info
    additions=['history_mode','result_currency','usd_mapping_version','usd_equivalent_mappings','usd_equivalent_caveat']
    values=['usd-equivalents','USD',VERSION,json.dumps(rows,ensure_ascii=False),WORDS['notice']]
    for item in bundle['downloads'].values():
        source=list(csv.reader(io.StringIO(item['csv'])))
        if not source: continue
        out=io.StringIO(); writer=csv.writer(out)
        writer.writerow(source[0]+additions)
        for row in source[1:]: writer.writerow(row+values)
        item['csv']=out.getvalue()
    out=io.StringIO(); writer=csv.DictWriter(out,fieldnames=['original','resolved','funds','assets','caveat','warning','history_mode','currency','mapping_version','tested_start','tested_end'])
    writer.writeheader()
    for row in rows: writer.writerow({**row,'history_mode':'usd-equivalents','currency':'USD','mapping_version':VERSION,'tested_start':str(window[0]),'tested_end':str(window[1])})
    bundle['downloads']['usd-equivalents']={'csv':out.getvalue(),'filename':'usd_equivalent_mappings.csv','label':WORDS['download']}
    return bundle
