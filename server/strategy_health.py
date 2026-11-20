"""Account-scoped, read-only health reports using existing loaders and engines."""
from datetime import date
from dataclasses import replace
import json
from pathlib import Path

from fastapi import HTTPException
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from haa.comparison import ModelInput
from haa.engine import run_backtest
from haa.market_sessions import scheduled_execution_dates, validate_us_equity_sessions, tase_equity_sessions, us_equity_sessions
from haa.model_catalog import definition_for_label
from haa.portfolio_backtest import run_portfolio_backtest
from haa.portfolio_signals import monthly_strategy_input
from haa.strategy_health import analyze
from haa.tase_data import TASE_EXECUTION_ASSET_IDS
from haa.constants import FRED_ASSETS, INFLATION_COMPASS_ISRAEL_EXECUTION_MAP
from . import signals, usd_equivalents
from .backtest import definition as model_definition
from .performance import decisions as cached_decisions
from .signals_wire import clean

WORDS = json.loads((Path(__file__).resolve().parents[1] / 'web/content/strategy-health.json').read_text())
FAMILIES = {'Century Momentum': 'cm', 'Inflation Compass': 'ic'}


class Thresholds(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    review: float = Field(default=WORDS['thresholdDefaults']['review'], gt=0, lt=100)
    structural: float = Field(default=WORDS['thresholdDefaults']['structural'], gt=0, lt=100)
    ic_review: float = Field(default=WORDS['thresholdDefaults']['ic_review'], gt=0, lt=100)
    ic_structural: float = Field(default=WORDS['thresholdDefaults']['ic_structural'], gt=0, lt=100)

    @model_validator(mode='after')
    def ordered(self):
        if (self.review >= self.structural or self.ic_review >= self.ic_structural
                or self.ic_review > self.review or self.ic_structural > self.structural):
            raise ValueError(WORDS['invalidThresholds'])
        return self


class Sleeve(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    model: str
    weight: float = Field(gt=0, le=100)


class Inputs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sleeves: list[Sleeve] | None = Field(default=None, min_length=1, max_length=100)
    end: date | None = None
    thresholds: Thresholds = Field(default_factory=Thresholds)
    checks_only: bool = False


def unavailable(key, reason):
    return {'key': key, 'status': 'insufficient', 'reason': reason, 'metrics': {},
            'action': WORDS['missingAction'], 'findings': []}


def recommendations(report):
    findings = []
    for key, metric in report.get('metrics', {}).items():
        if metric['status'] in {'review', 'structural'}:
            template = 'structuralTemplate' if metric['status'] == 'structural' else 'reasonTemplate'
            threshold = metric['structural_threshold'] if metric['status'] == 'structural' else metric['review_threshold']
            findings.append({'kind': key, 'status': metric['status'],
                             'message': WORDS[template].format(metric=WORDS[key], percentile=f"{metric['percentile']:.1f}", threshold=threshold),
                             'action': WORDS[key + 'Action']})
    findings.sort(key=lambda item: item['status'] != 'structural')
    if report.get('reason'):
        findings.append({'kind': 'data', 'status': 'insufficient', 'message': WORDS[report['reason']], 'action': WORDS['missingAction']})
    report['findings'] = findings
    report['action'] = findings[0]['action'] if findings else WORDS['monitor']
    return report


def model_history(definition, clock):
    """Original USD models and a common adjusted-close SPY benchmark only."""
    strategy = definition.model_class()
    assets = list(dict.fromkeys((*strategy.data_assets, 'SPY')))
    # Reuse the original loader's strict adjusted-close option. A raw Close
    # fallback would make a dividend-paying SPY comparison inconsistent.
    loader_class = type('HealthAdjusted' + definition.model_class.__name__, (definition.model_class,),
                        {'require_adjusted_assets': tuple(asset for asset in assets if asset not in FRED_ASSETS)})
    prices, metadata, warnings = signals.load_inputs(replace(definition, model_class=loader_class))
    prices = prices.loc[prices.index < clock.normalize()]
    prices = prices.reindex(columns=assets)
    if prices.index.has_duplicates or not prices.index.is_monotonic_increasing:
        raise ValueError(WORDS['gap'])
    for asset in getattr(strategy, 'market_data_assets', assets):
        series = prices[asset].dropna()
        if (not len(series) or not np.isfinite(series).all() or series.le(0).any()):
            raise ValueError(WORDS['missingData'])
        validate_us_equity_sessions(series.to_frame())
    warnings = list(warnings)
    for asset in set(assets).intersection(FRED_ASSETS):
        observed = prices[asset].dropna()
        if observed.empty or observed.index[-1] < (clock.to_period('M') - 1).start_time:
            warnings.append(WORDS['staleMacro'])
    monthly, signal_monthly = monthly_strategy_input(prices, getattr(strategy, 'market_data_assets', assets))
    decisions = cached_decisions(strategy, prices if getattr(strategy, 'uses_daily_signals', False) else signal_monthly)
    if decisions.empty:
        raise ValueError(WORDS['historyUnavailable'])
    model = ModelInput(definition.label, decisions, monthly, prices, 'SPY')
    result = run_backtest(decisions, monthly, 1., daily_prices=prices, benchmark_asset='SPY')
    return model, result, warnings


def implementation_checks(labels, current=None, clock=None):
    """Keep implementation evidence independent of simulated performance."""
    clock = pd.Timestamp.now(tz='UTC').tz_localize(None) if clock is None else pd.Timestamp(clock)
    findings, proxies, observations = [], [], []
    for label in labels:
        definition = model_definition(label)
        if definition.strategy not in FAMILIES:
            continue
        strategy = definition.model_class()
        mapping = getattr(strategy, 'execution_proxies', None)
        if definition.execution_currency != 'ILS':
            mapping = {}
        elif mapping is None:
            mapping = INFLATION_COMPASS_ISRAEL_EXECUTION_MAP
        try:
            prices, metadata, warnings = signals.load_inputs(definition)
            prices = prices.loc[prices.index < clock.normalize()]
            for warning in warnings:
                findings.append({'kind': 'data', 'status': 'review', 'message': WORDS['sourceWarning'], 'action': WORDS['technicalAction']})
            source_assets = getattr(strategy, 'signal_assets', strategy.data_assets)
            sessions = us_equity_sessions(str((clock - pd.Timedelta(days=14)).date()), str((clock.normalize() - pd.Timedelta(days=1)).date()))
            for asset in source_assets:
                series = prices[asset].dropna() if asset in prices else pd.Series(dtype=float)
                stamp = series.index[-1].date().isoformat() if len(series) else None
                status = 'normal'
                reason = None
                if not len(series) or not np.isfinite(series).all() or (asset not in FRED_ASSETS and series.le(0).any()):
                    status, reason = 'review', 'missingData'
                elif asset not in FRED_ASSETS:
                    try:
                        validate_us_equity_sessions(series.to_frame())
                    except ValueError:
                        status, reason = 'review', 'gap'
                    if len(sessions) and series.index[-1] < sessions[-1]:
                        status, reason = 'review', 'staleInput'
                else:
                    status = 'insufficient'
                    if series.index[-1] < (clock.to_period('M') - 1).start_time:
                        status, reason = 'review', 'staleMacro'
                observations.append({'model': label, 'asset': asset, 'last_date': stamp, 'status': status})
                if reason:
                    findings.append({'kind': 'data', 'status': status, 'message': f"{asset} ({stamp or WORDS['insufficient']}) · " + WORDS[reason], 'action': WORDS['technicalAction']})
            for underlying, local in mapping.items():
                security = TASE_EXECUTION_ASSET_IDS.get(local)
                published = str(metadata.loc[local].get('identifier', '')) if local in metadata.index else ''
                # Compare native session dates only for coverage. A local ILS
                # close is not a USD total return or an aligned US session.
                series = prices[local] if local in prices else pd.Series(dtype=float)
                valid = series.where(np.isfinite(series) & series.gt(0)).dropna()
                proxies.append({'model': label, 'underlying': underlying, 'holding': local, 'security': security,
                                'published_identifier': published or None,
                                'last_price_date': valid.index[-1].date().isoformat() if len(valid) else None,
                                'tracking_status': 'insufficient', 'reason': WORDS['trackingUnavailable']})
                mismatch = bool(published and security and published != security)
                findings.append({'kind': 'mapping', 'status': 'review' if mismatch else 'normal' if published else 'insufficient',
                                 'message': f"{local} · " + WORDS['mappingMismatch' if mismatch else 'mappingKnown' if published else 'mappingUnavailable'],
                                 'action': WORDS['technicalAction'] if mismatch else None})
                if not len(valid) or (~np.isfinite(series.dropna()) | series.dropna().le(0)).any():
                    findings.append({'kind': 'data', 'status': 'review', 'message': f"{local} · " + WORDS['missingData'], 'action': WORDS['technicalAction']})
                elif local in TASE_EXECUTION_ASSET_IDS:
                    now = clock.normalize()
                    sessions = tase_equity_sessions(str((now - pd.Timedelta(days=14)).date()), str((now - pd.Timedelta(days=1)).date()))
                    if len(sessions) and valid.index[-1] < sessions[-1]:
                        findings.append({'kind': 'data', 'status': 'review', 'message': f"{local} ({valid.index[-1]:%Y-%m-%d}) · " + WORDS['stalePrice'], 'action': WORDS['technicalAction']})
            if definition.strategy == 'Inflation Compass' and definition.execution_currency == 'ILS':
                findings.append({'kind': 'changes', 'status': 'normal', 'message': WORDS['icHedge'], 'action': None})
        except Exception:
            findings.append({'kind': 'data', 'status': 'insufficient', 'message': WORDS['missingData'], 'action': WORDS['technicalAction']})
    if current is None:
        findings.append({'kind': 'holdings', 'status': 'insufficient', 'message': WORDS['holdingsUnavailable'], 'action': WORDS['technicalAction']})
    else:
        rows = current.get('comparison')
        if rows and all(row.get('Actual %') is not None for row in rows):
            differences = [row for row in rows if row.get('Status') not in {'On target', 'Outside the rebalance'}]
            findings.insert(0, {'kind': 'holdings', 'status': 'review' if differences else 'normal',
                                'message': WORDS['mismatch' if differences else 'matched'], 'action': WORDS['holdingsAction'] if differences else None,
                                'rows': rows})
        else:
            findings.insert(0, {'kind': 'holdings', 'status': 'insufficient', 'message': WORDS['holdingsUnavailable'], 'action': WORDS['technicalAction']})
        for row in current.get('signals', []):
            if row.get('status_code') != 'ok':
                findings.insert(0, {'kind': 'data', 'status': 'review', 'message': WORDS['missingData'], 'action': WORDS['technicalAction']})
        for row in rows or []:
            if row.get('price_fresh') is False:
                findings.insert(0, {'kind': 'data', 'status': 'review', 'message': f"{row.get('id', '')} ({row.get('price_as_of', '')}): " + WORDS['staleData'], 'action': WORDS['technicalAction']})
    findings.append({'kind': 'changes', 'status': 'insufficient', 'message': WORDS['changesUnavailable'], 'action': None})
    findings.sort(key=lambda row: (row['status'] != 'review', row['kind'] != 'data'))
    return {'findings': findings, 'proxies': proxies, 'observations': observations}


def run(body, sleeves, current=None, clock=None):
    clock = pd.Timestamp.now(tz='UTC').tz_localize(None) if clock is None else pd.Timestamp(clock)
    if clock.tzinfo is not None:
        clock = clock.tz_convert('UTC').tz_localize(None)
    if len(sleeves) > 100 or abs(sum(s.weight for s in sleeves) - 100) > 1e-8:
        raise HTTPException(400, WORDS['weights'])
    try:
        definitions = [model_definition(s.model) for s in sleeves]
    except ValueError:
        raise HTTPException(400, WORDS['notSelected']) from None
    monitored = any(d.strategy in FAMILIES for d in definitions)
    output = {'reports': [], 'checks': {'findings': [], 'proxies': []}, 'thresholds': body.thresholds.model_dump(),
              'reason': None if monitored else 'notSelected', 'weights': [s.model_dump() for s in sleeves]}
    if not monitored:
        return output
    output['checks'] = implementation_checks([s.model for s in sleeves], current, clock)
    if body.checks_only:
        return clean(output)
    histories, failed, warnings = {}, set(), {}
    for index, (sleeve, definition) in enumerate(zip(sleeves, definitions)):
        try:
            original = usd_equivalents.resolve(sleeve.model)
            if original.execution_currency != 'USD':
                raise ValueError(WORDS['historyUnavailable'])
            model, history, alerts = model_history(original, clock)
            histories[index] = (model, history)
            warnings[index] = alerts
        except Exception:
            failed.add(index)
    groups = {family: [i for i, d in enumerate(definitions) if d.strategy == strategy] for strategy, family in FAMILIES.items()}
    groups['combined'] = list(range(len(sleeves)))
    cutoff = min(pd.Timestamp(body.end) if body.end else clock.normalize(), clock.normalize())
    for key, indices in groups.items():
        if not indices or any(i in failed for i in indices):
            output['reports'].append(unavailable(key, 'historyUnavailable'))
            continue
        uses_ic = any(definitions[i].strategy == 'Inflation Compass' for i in indices)
        policy = {'review': body.thresholds.ic_review if uses_ic else body.thresholds.review,
                  'structural': body.thresholds.ic_structural if uses_ic else body.thresholds.structural}
        try:
            total = sum(sleeves[i].weight for i in indices)
            if len(indices) == 1:
                result = histories[indices[0]][1]
            else:
                models = {str(i): (sleeves[i].weight / total, histories[i][0]) for i in indices}
                result = run_portfolio_backtest(models, 1.)
            monthly = result.monthly.loc[result.monthly.index <= cutoff]
            first = monthly.iloc[0].get('execution_date')
            if first is None or pd.isna(first):
                first = max(histories[i][1].monthly.loc[monthly.index[0], 'execution_date'] for i in indices)
            report = analyze(monthly, first, policy, WORDS['minimumSamples'])
            report.update(key=key, policy='ic' if uses_ic else 'cm', models=[sleeves[i].model for i in indices])
            if any(warnings[i] for i in indices):
                report.update(status='insufficient', reason='sourceWarning')
            # A requested historical date is explicitly historical. For Today,
            # a completed execution month that has not arrived cannot be stale.
            expected = scheduled_execution_dates(pd.DatetimeIndex([(clock.to_period('M') - 1).to_timestamp('M')]))[0]
            if body.end is None and expected < clock.normalize() and pd.Timestamp(report.get('as_of', '1900-01-01')).to_period('M') < expected.to_period('M'):
                report.update(status='insufficient', reason='staleData')
            output['reports'].append(recommendations(report))
        except Exception:
            output['reports'].append(unavailable(key, 'historyUnavailable'))
    return clean(output)
