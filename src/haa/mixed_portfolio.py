"""USD mixed-frequency portfolios: initial sleeve funding, no sleeve transfers.

Daily sleeves execute through the existing next-open engine. Monthly sleeves
trade at next-session close, using actual daily prices and security-level books.
Each sleeve retains its own cost bases and loss carryforward. Mixed portfolios
charge fees per actual buy/sell side; the legacy monthly-only engine is unchanged.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import BacktestResult, run_backtest, _normalise_weights
from .market_sessions import scheduled_execution_dates, us_equity_sessions, validate_us_equity_sessions
from .tax import IsraeliTaxState


def weights_for(row):
    return _normalise_weights(row.target_weights) if 'target_weights' in row.index else {row.selected_asset: 1.0}


def aggregate_months(daily):
    rows=[]
    for _, group in daily.groupby(daily.index.to_period('M')):
        row=group.iloc[-1].to_dict()
        for c in ('pre_tax_monthly_return','after_tax_monthly_return','benchmark_monthly_return'):
            row[c]=float((1+group[c]).prod()-1)
        row['allocation_change']=group.allocation_change.sum()
        row['turnover']=group.turnover.sum()
        if 'contribution' in group: row['contribution']=group.contribution.sum()
        rows.append({'holding_end':group.index[-1],**row})
    return pd.DataFrame(rows).set_index('holding_end')


def monthly_daily_book(model, sessions, capital, fee, taxed, tax_rate, monthly_contribution=0., fixed_fee=0.):
    from .backtest_options import contribution_for, order_fee
    """Mark monthly holdings daily; only trade on scheduled closes (or initial funding).

    Fees/tax are paid from sale proceeds, then purchases share remaining cash
    proportionally. No forced liquidation of retained assets or final holdings.
    """
    decisions=model.decisions.sort_index()
    execution=scheduled_execution_dates(decisions.index)
    schedule={d:(s,row) for d,(s,row) in zip(execution,decisions.iterrows())}
    prior=decisions.loc[decisions.index<sessions[0]]
    if prior.empty:
        raise ValueError('Monthly sleeve has no pre-start decision; refusing look-ahead initialization.')
    initial=(prior.index[-1],prior.iloc[-1])
    prices=model.daily_prices
    pre_positions={}; after_positions={}; pre_cash=after_cash=float(capital)
    tax=IsraeliTaxState(tax_rate=tax_rate)
    events=[]; audit=[]; output=[]; previous_date=None
    for i,date in enumerate(sessions):
        prior_pre=sum(pre_positions.values())+pre_cash
        prior_after=sum(after_positions.values())+after_cash
        contribution = contribution_for(date, None, previous_date, monthly_contribution)
        def opening_value(positions, cash):
            if previous_date is None: return cash
            if model.daily_open_prices is None: return sum(positions.values())+cash
            return sum(value*model.daily_open_prices.loc[date,asset]/prices.loc[previous_date,asset] for asset,value in positions.items())+cash
        open_pre = opening_value(pre_positions, pre_cash)
        open_after = opening_value(after_positions, after_cash)
        if previous_date is not None:
            for positions in (pre_positions,after_positions):
                for asset in positions:
                    positions[asset]*=prices.loc[date,asset]/prices.loc[previous_date,asset]
        trades=0.; change=False
        pre_cash += contribution
        after_cash += contribution
        if i==0 or date in schedule or contribution:
            prior = decisions.loc[decisions.index < date]
            signal,row=schedule.get(date,(prior.index[-1],prior.iloc[-1]))
            target=weights_for(row)
            details=[]
            for positions,is_after in ((pre_positions,False),(after_positions,True)):
                cash=after_cash if is_after else pre_cash
                total=sum(positions.values())+cash
                desired={a:total*w for a,w in target.items()}
                for asset,current in list(positions.items()):
                    sale=max(0.,current-desired.get(asset,0.))
                    if sale>max(total,1.)*1e-12:
                        sell_fee=order_fee(sale,fee,fixed_fee)
                        proceeds=sale-sell_fee
                        levy=0.
                        if is_after and taxed:
                            basis=tax.cost_bases.get(asset,0.)*sale/current
                            event=tax.sell(proceeds,asset=asset,cost_basis_sold=basis)
                            proceeds-=event['tax_paid']
                            levy=event['tax_paid']
                            events.append({'date':date,'signal_date':signal,'sold_asset':asset,'proceeds':sale-sell_fee,**event})
                        positions[asset]-=sale; cash+=proceeds
                        details.append({'book':'after-tax' if is_after else 'pre-tax','asset':asset,'side':'sell','notional':sale,'fee':sell_fee,'tax_paid':levy,'adjusted_price':prices.loc[date,asset]})
                        change=True
                deficits={a:max(0.,amount-positions.get(a,0.)) for a,amount in desired.items()}
                needed=sum(deficits.values())
                if needed>0:
                    # Cash budgets include buy fees, and never exceed available cash.
                    budget=min(cash,needed/(1-fee))
                    order_count=sum(deficit>max(total,1.)*1e-12 for deficit in deficits.values())
                    if budget <= fixed_fee*order_count: raise ValueError('Fixed fees consume monthly-sleeve purchase capital.')
                    net_budget=budget-fixed_fee*order_count
                    for asset,deficit in deficits.items():
                        if deficit<=max(total,1.)*1e-12: continue
                        spend=net_budget*deficit/needed
                        positions[asset]=positions.get(asset,0.)+spend*(1-fee)
                        if is_after and taxed and spend: tax.buy(asset,spend+fixed_fee)
                        if not is_after: trades+=spend*(1-fee)
                        if spend: details.append({'book':'after-tax' if is_after else 'pre-tax','asset':asset,'side':'buy','notional':spend*(1-fee),'fee':spend*fee+fixed_fee,'adjusted_price':prices.loc[date,asset]})
                        if spend: change=True
                    cash-=budget
                if is_after: after_cash=cash
                else: pre_cash=cash
            audit.append({'execution_date':date,'decision_date':signal,'execution_timing':'next-session-close','target_weights':target,'security_trades':details})
        pre=sum(pre_positions.values())+pre_cash; after=sum(after_positions.values())+after_cash
        output.append({'holding_end':date,'pre_tax_value':pre,'after_tax_value':after,
            'pre_tax_monthly_return':(pre-contribution)/prior_pre-1,'after_tax_monthly_return':(after-contribution)/prior_after-1,
            'contribution':contribution,'open_pre_tax_value':open_pre,'open_after_tax_value':open_after,
            'allocation_change':change,'purchase_notional':trades,'turnover':trades/max(prior_pre,1e-300)})
        previous_date=date
    daily=pd.DataFrame(output).set_index('holding_end')
    return BacktestResult(pd.DataFrame(),pd.DataFrame(audit),pd.DataFrame(events),daily)


def run_mixed_portfolio(sleeves, initial, fee=0., taxed=False, tax_rate=.25, start=None, end=None, monthly_contribution=0., fixed_fee=0.):
    from .portfolio_backtest import PortfolioBacktestResult
    weights={name:float(w) for name,(w,_) in sleeves.items()}
    if not np.isfinite(initial) or initial<=0 or not 0<=fee<1 or not 0<=tax_rate<=1:
        raise ValueError('Invalid mixed-portfolio capital, fee or tax rate.')
    if any(not np.isfinite(w) or w<=0 for w in weights.values()) or abs(sum(weights.values())-1)>1e-9:
        raise ValueError('Portfolio sleeve weights must be positive and total exactly 100%.')
    lower=[]; upper=[]; benchmark=None
    for _,model in sleeves.values():
        if model.execution_currency!='USD':
            raise ValueError('Mixed-frequency portfolios currently require USD sleeves on the US exchange calendar; no currency conversion is assumed.')
        if model.daily_prices is None or model.decisions.empty:
            raise ValueError('Mixed-frequency portfolios require actual daily security prices and decisions for every sleeve; monthly proxies cannot be used.')
        if model.decisions.index.has_duplicates or model.decisions.index.hasnans:
            raise ValueError('Sleeve decisions must have unique valid dates.')
        if benchmark is not None and benchmark!=model.benchmark_asset:
            raise ValueError('Mixed portfolio sleeves must share the same benchmark.')
        benchmark=model.benchmark_asset
        assets={benchmark}
        for _,row in model.decisions.iterrows(): assets.update(weights_for(row))
        if not assets.issubset(model.daily_prices.columns):
            raise ValueError('Required sleeve/benchmark security prices are unavailable.')
        quotes=model.daily_prices.loc[:,sorted(assets)].sort_index()
        validate_us_equity_sessions(quotes)
        valid=np.isfinite(quotes).all(axis=1)&(quotes>0).all(axis=1)
        if not valid.any(): raise ValueError('No usable daily sleeve history.')
        lower.extend([quotes.index[valid][0],scheduled_execution_dates(model.decisions.index[:1])[0]])
        upper.append(min(quotes.index.max(),model.decisions.attrs.get('completed_through',quotes.index.max())))
    first=max(lower+[pd.Timestamp(start)] if start is not None else lower)
    last=min(upper+[pd.Timestamp(end)] if end is not None else upper)
    if first>last: raise ValueError('No common executable daily history in the requested date range.')
    sessions=us_equity_sessions(str(first.date()),str(last.date()))
    if sessions.empty: raise ValueError('No common executable trading sessions.')
    results={}; events=[]; audits=[]; benchmark_quotes=None
    for name,(weight,model) in sleeves.items():
        assets={benchmark}
        for _,row in model.decisions.iterrows(): assets.update(weights_for(row))
        values=model.daily_prices.reindex(sessions).loc[:,sorted(assets)]
        if monthly_contribution:
            if model.daily_open_prices is None or not assets.issubset(model.daily_open_prices.columns):
                raise ValueError('Mixed DCA requires opening prices for every sleeve to measure cash-flow-adjusted returns.')
            if not np.isfinite(model.daily_open_prices.reindex(sessions).loc[:,sorted(assets)].to_numpy()).all():
                raise ValueError('Missing opening prices within mixed DCA history.')
        if not np.isfinite(values.to_numpy()).all() or (values<=0).any().any():
            raise ValueError(f'{name}: missing/invalid security prices within common history; refusing to bridge gaps.')
        if benchmark_quotes is not None and not np.allclose(values[benchmark],benchmark_quotes,rtol=1e-12,atol=1e-12):
            raise ValueError('Sleeves have inconsistent benchmark price histories.')
        benchmark_quotes=values[benchmark]
        if model.decisions.attrs.get('execution_frequency')=='daily':
            result=run_backtest(model.decisions,model.monthly_prices,initial*weight,fee,taxed,tax_rate,
                sessions[0],sessions[-1],daily_prices=model.daily_prices,benchmark_asset=benchmark,
                daily_open_prices=model.daily_open_prices, monthly_contribution=monthly_contribution*weight, fixed_fee=fixed_fee)
        else:
            required_months=pd.period_range(sessions[0].to_period('M')-1,sessions[-1].to_period('M')-1,freq='M')
            missing=required_months.difference(model.decisions.index.to_period('M'))
            if len(missing):
                raise ValueError(f'{name}: missing monthly decisions for {list(missing)}; refusing to carry an unexplained stale signal.')
            result=monthly_daily_book(model,sessions,initial*weight,fee,taxed,tax_rate, monthly_contribution*weight, fixed_fee)
        if not result.daily.index.equals(sessions): raise ValueError('Sleeve daily histories do not align exactly.')
        if model.decisions.attrs.get('execution_frequency')=='daily':
            buys=[]
            for i,(date,row) in enumerate(result.daily.iterrows()):
                asset=row.selected_asset
                intraday=model.daily_prices.loc[date,asset]/model.daily_open_prices.loc[date,asset]
                buys.append(row.pre_tax_value/intraday if i==0 or row.allocation_change else 0.)
            result.daily['purchase_notional']=buys
        results[name]=result
        if not result.tax_events.empty:
            events.append(result.tax_events.assign(sold_sleeve=name,tax_level='strategy sleeve'))
        audits.append(result.audit.assign(sleeve=name))
    daily=pd.DataFrame(index=sessions)
    sleeve_nav=pd.DataFrame({n:r.daily.pre_tax_value for n,r in results.items()})
    daily['pre_tax_value']=sleeve_nav.sum(axis=1)
    daily['after_tax_value']=sum(r.daily.after_tax_value for r in results.values())
    daily_model=next((m for _,m in sleeves.values() if m.decisions.attrs.get('execution_frequency')=='daily'), next(iter(sleeves.values()))[1])
    if daily_model.daily_open_prices is None: raise ValueError('Daily sleeve requires adjusted opening prices.')
    benchmark_opens=daily_model.daily_open_prices.reindex(sessions)[benchmark]
    if not np.isfinite(benchmark_opens).all() or (benchmark_opens<=0).any():
        raise ValueError('Missing/invalid benchmark opening prices in comparison history.')
    benchmark_open=daily_model.daily_open_prices.loc[sessions[0],benchmark]
    daily['benchmark_value']=initial*daily_model.daily_prices.loc[sessions,benchmark]/benchmark_open
    daily['contribution']=sum(r.daily.contribution for r in results.values())
    open_flows=sum((r.daily.contribution for n,r in results.items() if sleeves[n][1].decisions.attrs.get('execution_frequency')=='daily'), pd.Series(0., index=sessions))
    close_flows=daily.contribution-open_flows
    bench=initial
    benchmark_returns=[]; benchmark_values=[]
    for i,date in enumerate(sessions):
        prior_bench=bench
        opening=bench if i==0 else bench*daily_model.daily_open_prices.loc[date,benchmark]/daily_model.daily_prices.loc[sessions[i-1],benchmark]
        bench=(opening+open_flows.loc[date])*daily_model.daily_prices.loc[date,benchmark]/daily_model.daily_open_prices.loc[date,benchmark]+close_flows.loc[date]
        benchmark_values.append(bench)
        benchmark_returns.append(opening/prior_bench*(bench-close_flows.loc[date])/(opening+open_flows.loc[date])-1)
    daily['benchmark_value']=benchmark_values
    for value,ret in [('pre_tax_value','pre_tax_monthly_return'),('after_tax_value','after_tax_monthly_return'),('benchmark_value','benchmark_monthly_return')]:
        previous=daily[value].shift(1); previous.iloc[0]=initial
        if value=='benchmark_value': daily[ret]=benchmark_returns
        else:
            opening=sum(r.daily['open_'+value] for r in results.values())
            daily[ret]=opening/previous*(daily[value]-close_flows)/(opening+open_flows)-1
    daily['allocation_change']=sum(r.daily.allocation_change.astype(int) for r in results.values())
    prior=daily.pre_tax_value.shift(1); prior.iloc[0]=initial
    daily['turnover']=sum(r.daily.purchase_notional for r in results.values())/prior
    monthly=aggregate_months(daily)
    sleeve_returns=pd.DataFrame({n:r.daily.pre_tax_monthly_return.groupby(r.daily.index.to_period('M')).apply(lambda x:(1+x).prod()-1).to_numpy() for n,r in results.items()},index=monthly.index)
    return PortfolioBacktestResult(monthly,sleeve_returns,sessions,
        pd.concat(events,ignore_index=True) if events else pd.DataFrame(),daily,sleeve_nav,
        pd.concat(audits,ignore_index=True))
