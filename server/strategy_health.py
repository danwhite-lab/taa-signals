"""Account-scoped, read-only health reports using existing loaders and engines."""
from datetime import date
from dataclasses import replace
import json
from pathlib import Path

from fastapi import HTTPException
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from haa.comparison import ModelInput
from haa.engine import run_backtest
from haa.market_sessions import scheduled_execution_dates, validate_us_equity_sessions, tase_equity_sessions, us_equity_sessions
from haa.model_catalog import definition_for_label
from haa.portfolio_backtest import run_portfolio_backtest
from haa.portfolio_signals import monthly_strategy_input
from haa.strategy_health import analyze
from haa.deep_history import DEEP_HISTORY_SPECS, load_deep_history
from haa.health_reference import replacement_returns, replace_defensive_returns
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
    minimum_falls: int = Field(default=WORDS['thresholdDefaults']['minimum_falls'], ge=1)
    warning_fraction: float = Field(default=WORDS['thresholdDefaults']['warning_fraction'], gt=0, le=1)
    gap_tail_percent: float = Field(default=WORDS['thresholdDefaults']['gap_tail_percent'], gt=0, le=100)
    minimum_years: int = Field(default=WORDS['thresholdDefaults']['minimum_years'], ge=0)


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


def unavailable(key, reason, failures=None):
    return {'key': key, 'status': 'insufficient', 'reason': reason, 'metrics': {},
            'action': WORDS['missingAction'], 'findings': [], 'failures': failures or [], 'caveats': []}


def recommendations(report):
    """Name only the measure(s) setting the light, separately from data notes."""
    metrics = report.get('metrics', {})
    triggers = [key for key, metric in metrics.items() if metric['status'] == report['status']]
    names = ', '.join(WORDS['triggerNames'][key] for key in triggers)
    report['triggered_by'] = triggers
    report['summary'] = WORDS['lightReasons'][report['status']].format(measures=names or WORDS['history'], years=report.get('minimum_years', WORDS['thresholdDefaults']['minimum_years']))
    report['findings'] = []
    report['action'] = WORDS['monitor'] if report['status'] == 'green' else WORDS['missingAction'] if report['status'] in {'insufficient', 'short_history'} else WORDS['trafficRule']
    return report


def reference_history(label, before):
    """Read an opt-in bundled proxy for earlier health falls only."""
    config = WORDS.get('referenceProxies', {}).get(label)
    if config is None:
        return None, None
    spec = DEEP_HISTORY_SPECS[config['series']]
    if spec.currency != 'USD':
        raise ValueError('A USD health reference needs a USD proxy.')
    decisions, returns = load_deep_history(spec)
    if replacement := config.get('replacement'):
        # Reconstruct only the earlier health segment. Trading results never
        # read this stream, and no IEF defensive return survives reconstruction.
        returns = returns.loc[returns.index < pd.Timestamp(before)]
        returns = replace_defensive_returns(
            decisions, returns, replacement_returns(replacement),
            risk_asset=replacement['risk_asset'], defensive_asset=replacement['defensive_asset'])
    earlier = returns.loc[(returns.index >= pd.Timestamp(config['start'])) & (returns.index < pd.Timestamp(before))]
    if earlier.empty:
        raise ValueError('The configured health proxy has no earlier observations.')
    return earlier, config


def price_age_finding(identifier, stamp, clock):
    """Date a local quote using completed TASE sessions, independently of signals."""
    try:
        observed = pd.Timestamp(stamp).normalize()
        if observed.tzinfo is not None:
            observed = observed.tz_localize(None)
        last_completed_day = clock.normalize() - pd.Timedelta(days=1)
        sessions = tase_equity_sessions(str(observed.date()), str(last_completed_day.date())) if observed <= last_completed_day else []
        age = int(sum(session > observed for session in sessions))
    except (ValueError, TypeError):
        return {'kind': 'data', 'status': 'insufficient', 'message': WORDS['priceAgeUnknown'].format(identifier=identifier), 'action': WORDS['technicalAction']}
    wording = WORDS['priceAgeOne'] if age == 1 else WORDS['priceAgeMany']
    return {'kind': 'data', 'status': 'review' if age >= 2 else 'normal',
            'message': wording.format(identifier=identifier, date=observed.date().isoformat(), days=age),
            'action': WORDS['technicalAction'] if age >= 2 else None, 'trading_days_old': age}


def model_history(definition, clock):
    """Original USD models and a common adjusted-close SPY benchmark only."""
    strategy = definition.model_class()
    assets = list(dict.fromkeys((*strategy.data_assets, 'SPY')))
    # Reuse the original loader's strict adjusted-close option. A raw Close
    # fallback would make a dividend-paying SPY comparison inconsistent.
    loader_class = type('HealthAdjusted' + definition.model_class.__name__, (definition.model_class,),
                        {'data_assets': tuple(assets), 'benchmark_asset': 'SPY',
                         'require_adjusted_assets': tuple(asset for asset in assets if asset not in FRED_ASSETS)})
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
                findings.append({'kind': 'data', 'status': 'review', 'message': f"{label} · {signals.safe_error(warning)}", 'action': WORDS['technicalAction']})
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
                    findings.append(price_age_finding('TASE:' + str(security), valid.index[-1], clock))
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
                if str(row.get('id', '')).startswith('TASE:'):
                    findings.insert(0, price_age_finding(row['id'], row.get('price_as_of'), clock))
                else:
                    findings.insert(0, {'kind': 'data', 'status': 'review', 'message': WORDS['datedPrice'].format(identifier=row.get('id', ''), date=row.get('price_as_of', '')), 'action': WORDS['technicalAction']})
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
    histories, failed, warnings = {}, {}, {}
    for index, (sleeve, definition) in enumerate(zip(sleeves, definitions)):
        try:
            original = usd_equivalents.resolve(sleeve.model)
            if original.execution_currency != 'USD':
                raise ValueError(WORDS['historyUnavailable'])
        except Exception:
            failed[index] = {'model': sleeve.model, 'message': WORDS['missingUsdMapping'].format(sleeve=sleeve.model)}
            continue
        try:
            model, history, alerts = model_history(original, clock)
            histories[index] = (model, history)
            warnings[index] = alerts
        except Exception as exc:
            detail = str(exc)
            # Only known calculation errors are safe to display. Provider and
            # transport exceptions may contain private connection information.
            known_error = isinstance(exc, ValueError) and (detail in WORDS.values() or detail.startswith(('Missing US equity trading sessions', 'No valid signals', 'No complete post-signal', 'Missing monthly signal')))
            message_key = 'missingHealthBenchmark' if isinstance(exc, KeyError) and "'SPY'" in detail else 'missingSleeveHistory'
            failed[index] = {'model': sleeve.model, 'message': WORDS[message_key].format(sleeve=sleeve.model, underlying=original.label),
                             'detail': signals.safe_error(exc) if known_error else None}
    groups = {family: [i for i, d in enumerate(definitions) if d.strategy == strategy] for strategy, family in FAMILIES.items()}
    # Combined always includes ALL configured sleeves at their saved weights.
    # Missing USD mappings/history must never silently drop or renormalize one.
    groups['combined'] = list(range(len(sleeves)))
    cutoff = min(pd.Timestamp(body.end) if body.end else clock.normalize(), clock.normalize())
    for key, indices in groups.items():
        if not indices or any(i in failed for i in indices):
            report = unavailable(key, 'historyUnavailable', [failed[i] for i in indices if i in failed])
            if key == 'combined':
                report['composition'] = 'all_sleeves'
            output['reports'].append(report)
            continue
        policy = body.thresholds.model_dump()
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
            earlier, extension = None, None
            proxy_warning = None
            # A composite needs its own complete reference, not a subset of
            # its sleeves. Only configured single-strategy references extend.
            if len(indices) == 1:
                try:
                    earlier, extension = reference_history(histories[indices[0]][0].name, first)
                except Exception:
                    proxy_warning = WORDS['proxyLoadFailed']
            try:
                report = analyze(monthly, first, policy, earlier)
            except ValueError:
                report = analyze(monthly, first, policy)
                proxy_warning = WORDS['proxyLoadFailed']
            report.update(key=key, models=[sleeves[i].model for i in indices])
            report['caveats'] = [{'model': sleeves[i].model, 'warning': signals.safe_error(warning)}
                                  for i in indices for warning in warnings[i]]
            if report.get('proxy_before') and extension:
                report['reference_proxy'] = extension['series']
                report['caveats'].append({'model': report['models'][0], 'warning': extension.get('note', '')})
            if proxy_warning:
                report['caveats'].append({'model': report['models'][0], 'warning': proxy_warning})
            # Prominent proxy disclosures come from the shared mapping data,
            # so every affected health card identifies its return proxy.
            for i in indices:
                mapping = usd_equivalents.REGISTRY['mappings'].get(sleeves[i].model, {})
                if mapping.get('prominent'):
                    report['caveats'].append({'model': sleeves[i].model, 'warning': mapping['note']})
            if key == 'combined':
                report['composition'] = 'all_sleeves'
            # A requested historical date is explicitly historical. For Today,
            # a completed execution month that has not arrived cannot be stale.
            expected = scheduled_execution_dates(pd.DatetimeIndex([(clock.to_period('M') - 1).to_timestamp('M')]))[0]
            if body.end is None and expected < clock.normalize() and pd.Timestamp(report.get('as_of', '1900-01-01')).to_period('M') < expected.to_period('M'):
                report['caveats'].append({'model': ', '.join(report['models']), 'warning': WORDS['staleData']})
            output['reports'].append(recommendations(report))
        except Exception:
            failures = [{'model': sleeves[i].model, 'message': WORDS['combinedEngineFailure'].format(sleeve=sleeves[i].model)} for i in indices]
            report = unavailable(key, 'historyUnavailable', failures)
            if key == 'combined':
                report['composition'] = 'all_sleeves'
            output['reports'].append(report)
    return clean(output)
