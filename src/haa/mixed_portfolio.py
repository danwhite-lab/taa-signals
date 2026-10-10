"""Same-currency USD or ILS portfolios with optional sleeve-level transfers.

US daily sleeves execute at next-open; Israel daily sleeves at next-close/NAV. Monthly sleeves
trade at next-session close, using actual daily prices and security-level books.
Each sleeve retains its own cost bases and loss carryforward. Mixed portfolios
charge fees per actual buy/sell side; the legacy monthly-only engine is unchanged.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import BacktestResult, run_backtest, _normalise_weights
from .market_sessions import scheduled_execution_dates, us_equity_sessions, validate_us_equity_sessions, scheduled_tase_execution_dates, tase_equity_sessions, validate_tase_sessions
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


def _rebalance_dates(sessions, mode):
    """Return calendar quarter/year-end review sessions, excluding inception."""
    if mode == 'rvol_cap':
        periods=sessions.to_period('Q')
    elif mode == 'annual_target':
        periods=sessions.to_period('Y')
    else:
        return pd.DatetimeIndex([])
    completed=sessions.to_series().groupby(periods).max()
    return pd.DatetimeIndex([date for period,date in completed.items() if date.month == period.asfreq('M','end').month])


def _apply_sleeve_transfer(positions, bases, targets, fee, fixed_fee, tax_state=None, date=None, events=None):
    """Restore target sleeve weights after a review.

    Sleeve returns already include each strategy's own trading/tax ledger.  This
    models the additional sale needed to fund a transfer as a sale of the
    sleeve account itself.  It is deliberately an auditable approximation, not
    an underlying-security lot reconstruction.
    """
    from .backtest_options import order_fee
    total=sum(positions.values())
    desired={name: total*weight for name,weight in targets.items()}
    sales={name:max(0.,positions[name]-desired[name]) for name in positions}
    sales={name:value for name,value in sales.items() if value>max(total,1.)*1e-12}
    if not sales:
        return positions, bases, 0., 0., [], 0.
    sale_fees={name:order_fee(value,fee,fixed_fee) for name,value in sales.items()}
    tax_paid=0.
    transfer_events=[]
    retained={name:positions[name]-sales.get(name,0.) for name in positions}
    cash=sum(sales.values())-sum(sale_fees.values())
    for name,sale in sales.items():
        basis=bases.get(name,0.)
        sold_basis=min(basis,basis*sale/positions[name]) if positions[name] else 0.
        bases[name]=basis-sold_basis
        if tax_state is not None:
            event=tax_state.sell(sale-sale_fees[name],asset=name,cost_basis_sold=sold_basis)
            levy=event['tax_paid']
            tax_paid+=levy
            cash-=levy
            row={'date':date,'tax_level':'portfolio sleeve transfer','sold_sleeve':name,
                 'proceeds':sale-sale_fees[name],**event}
            events.append(row)
            transfer_events.append(row)
    # Pay purchase-side fees from the transfer pool, then distribute what is
    # left in target proportions.  The exact transfer lots are retained in the
    # audit/download rather than being hidden as a return adjustment.
    new_total=sum(retained.values())+cash
    target_after={name:new_total*weight for name,weight in targets.items()}
    buys={name:max(0.,target_after[name]-retained[name]) for name in retained}
    buy_fees={name:order_fee(value,fee,fixed_fee) for name,value in buys.items() if value>max(total,1.)*1e-12}
    total_fees=sum(buy_fees.values())
    if total_fees:
        new_total-=total_fees
        target_after={name:new_total*weight for name,weight in targets.items()}
        buys={name:max(0.,target_after[name]-retained[name]) for name in retained}
    positions={name:target_after[name] for name in positions}
    for name,buy in buys.items():
        if buy>0:
            bases[name]=bases.get(name,0.)+buy+buy_fees.get(name,0.)
            if tax_state is not None: tax_state.buy(name,buy+buy_fees.get(name,0.))
    return positions,bases,tax_paid,sum(sale_fees.values())+sum(buy_fees.values()),transfer_events,sum(sales.values())+sum(buys.values())


def _rebalance_mixed_daily(daily, sleeve_nav, after_sleeve_nav, weights, mode, cap_sleeve, cap, cap_target, fee, fixed_fee, taxed, tax_rate):
    """Apply optional sleeve transfers to already-run daily sleeve return streams."""
    if mode == 'none':
        return daily, sleeve_nav, [], []
    if mode not in {'rvol_cap','annual_target'}:
        raise ValueError('Unknown mixed-portfolio sleeve rebalancing mode.')
    if mode == 'rvol_cap':
        if cap_sleeve not in weights:
            raise ValueError('Select the RVol sleeve to cap.')
        if not 0 < cap_target < cap < 1:
            raise ValueError('RVol reset target must be positive and below the cap, which must be below 100%.')
    if not np.isfinite(fee) or fee < 0 or fixed_fee < 0:
        raise ValueError('Invalid sleeve transfer fee.')
    if daily.contribution.any():
        raise ValueError('Sleeve transfers are not available with monthly contributions yet.')
    dates=_rebalance_dates(daily.index,mode)
    pre_positions=sleeve_nav.iloc[0].to_dict()
    after_positions=after_sleeve_nav.iloc[0].to_dict()
    pre_bases=pre_positions.copy(); after_bases=after_positions.copy()
    tax=IsraeliTaxState(tax_rate=tax_rate) if taxed else None
    if tax is not None:
        for name,amount in after_bases.items(): tax.buy(name,amount)
    out_pre=[]; out_after=[]; out_sleeves=[]; turnover=[]; transfer_flags=[]; taxes=[]; audit=[]; events=[]
    previous_pre=sleeve_nav.iloc[0]; previous_after=after_sleeve_nav.iloc[0]
    for i,date in enumerate(daily.index):
        if i:
            factors=sleeve_nav.loc[date]/previous_pre
            after_factors=after_sleeve_nav.loc[date]/previous_after
            for name in weights:
                pre_positions[name]*=factors[name]
                after_positions[name]*=after_factors[name]
        changed=False; fees=0.; tax_paid=0.
        if date in dates:
            current=sum(pre_positions.values())
            current_weight=pre_positions[cap_sleeve]/current if mode=='rvol_cap' else None
            if mode=='annual_target' or current_weight>cap:
                targets=weights.copy()
                if mode=='rvol_cap':
                    remainder=1-cap_target
                    other_total=1-weights[cap_sleeve]
                    targets={name:(cap_target if name==cap_sleeve else weight/other_total*remainder) for name,weight in weights.items()}
                pre_positions,pre_bases,_,pre_fees,_,pre_notional=_apply_sleeve_transfer(pre_positions,pre_bases,targets,fee,fixed_fee)
                after_positions,after_bases,tax_paid,after_fees,transfer_events,after_notional=_apply_sleeve_transfer(after_positions,after_bases,targets,fee,fixed_fee,tax,date,events)
                fees=max(pre_fees,after_fees); changed=True
                audit.append({'execution_date':date,'execution_timing':'quarter-end close' if mode=='rvol_cap' else 'year-end close',
                              'rebalance_mode':mode,'target_weights':targets,'rvol_weight_before':current_weight,
                              'transfer_fees':fees,'transfer_tax':tax_paid,'transfer_notional':max(pre_notional,after_notional)})
        pre_value=sum(pre_positions.values()); after_value=sum(after_positions.values())
        out_pre.append(pre_value); out_after.append(after_value); out_sleeves.append(pre_positions.copy())
        turnover.append(audit[-1]['transfer_notional'] / max(pre_value,1e-300) if changed else 0.)
        transfer_flags.append(changed); taxes.append(tax_paid)
        previous_pre=sleeve_nav.loc[date]; previous_after=after_sleeve_nav.loc[date]
    adjusted=daily.copy(); adjusted['pre_tax_value']=out_pre; adjusted['after_tax_value']=out_after
    adjusted['portfolio_rebalance_tax']=taxes; adjusted['portfolio_rebalance']=transfer_flags
    adjusted['portfolio_rebalance_turnover']=turnover
    return adjusted,pd.DataFrame(out_sleeves,index=daily.index),events,audit


def monthly_daily_book(model, sessions, capital, fee, taxed, tax_rate, monthly_contribution=0., fixed_fee=0.):
    from .backtest_options import contribution_for, order_fee
    """Mark monthly holdings daily; only trade on scheduled closes (or initial funding).

    Fees/tax are paid from sale proceeds, then purchases share remaining cash
    proportionally. No forced liquidation of retained assets or final holdings.
    """
    decisions=model.decisions.sort_index()
    execution=(scheduled_tase_execution_dates if model.execution_currency == 'ILS' else scheduled_execution_dates)(decisions.index)
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


def run_mixed_portfolio(sleeves, initial, fee=0., taxed=False, tax_rate=.25, start=None, end=None, monthly_contribution=0., fixed_fee=0., sleeve_rebalance_mode='none', rebalance_sleeve=None, rebalance_cap=.15, rebalance_target=.10):
    from .portfolio_backtest import PortfolioBacktestResult
    weights={name:float(w) for name,(w,_) in sleeves.items()}
    currencies={model.execution_currency for _,model in sleeves.values()}
    if len(currencies) != 1 or not currencies.issubset({'USD','ILS'}):
        raise ValueError('Daily portfolios require USD sleeves together or ILS sleeves together; currencies cannot be combined without FX conversion.')
    local = currencies == {'ILS'}
    schedule_dates=scheduled_tase_execution_dates if local else scheduled_execution_dates
    session_dates=tase_equity_sessions if local else us_equity_sessions
    validate_sessions=validate_tase_sessions if local else validate_us_equity_sessions
    if not np.isfinite(initial) or initial<=0 or not 0<=fee<1 or not 0<=tax_rate<=1:
        raise ValueError('Invalid mixed-portfolio capital, fee or tax rate.')
    if any(not np.isfinite(w) or w<=0 for w in weights.values()) or abs(sum(weights.values())-1)>1e-9:
        raise ValueError('Portfolio sleeve weights must be positive and total exactly 100%.')
    lower=[]; upper=[]; benchmark=None
    for _,model in sleeves.values():
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
        validate_sessions(quotes)
        valid=np.isfinite(quotes).all(axis=1)&(quotes>0).all(axis=1)
        if not valid.any(): raise ValueError('No usable daily sleeve history.')
        lower.extend([quotes.index[valid][0],schedule_dates(model.decisions.index[:1])[0]])
        upper.append(min(quotes.index.max(),model.decisions.attrs.get('completed_through',quotes.index.max())))
    first=max(lower+[pd.Timestamp(start)] if start is not None else lower)
    last=min(upper+[pd.Timestamp(end)] if end is not None else upper)
    if first>last: raise ValueError('No common executable daily history in the requested date range.')
    sessions=session_dates(str(first.date()),str(last.date()))
    if sessions.empty: raise ValueError('No common executable trading sessions.')
    results={}; events=[]; audits=[]; benchmark_quotes=None
    for name,(weight,model) in sleeves.items():
        assets={benchmark}
        for _,row in model.decisions.iterrows(): assets.update(weights_for(row))
        values=model.daily_prices.reindex(sessions).loc[:,sorted(assets)]
        if monthly_contribution and not local:
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
        if model.decisions.attrs.get('execution_frequency')=='daily' and not model.decisions.attrs.get('local_daily_execution'):
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
    after_sleeve_nav=pd.DataFrame({n:r.daily.after_tax_value for n,r in results.items()})
    daily['pre_tax_value']=sleeve_nav.sum(axis=1)
    daily['after_tax_value']=after_sleeve_nav.sum(axis=1)
    daily_model=next((m for _,m in sleeves.values() if m.decisions.attrs.get('execution_frequency')=='daily'), next(iter(sleeves.values()))[1])
    if daily_model.daily_open_prices is None and not local: raise ValueError('Daily sleeve requires adjusted opening prices.')
    benchmark_opens=(daily_model.daily_prices if local else daily_model.daily_open_prices).reindex(sessions)[benchmark]
    if not np.isfinite(benchmark_opens).all() or (benchmark_opens<=0).any():
        raise ValueError('Missing/invalid benchmark opening prices in comparison history.')
    benchmark_open=benchmark_opens.loc[sessions[0]]
    daily['benchmark_value']=initial*daily_model.daily_prices.loc[sessions,benchmark]/benchmark_open
    daily['contribution']=sum(r.daily.contribution for r in results.values())
    open_flows=sum((r.daily.contribution for n,r in results.items() if not local and sleeves[n][1].decisions.attrs.get('execution_frequency')=='daily'), pd.Series(0., index=sessions))
    close_flows=daily.contribution-open_flows
    bench=initial
    benchmark_returns=[]; benchmark_values=[]
    for i,date in enumerate(sessions):
        prior_bench=bench
        opening=bench if i==0 else bench*benchmark_opens.loc[date]/daily_model.daily_prices.loc[sessions[i-1],benchmark]
        bench=(opening+open_flows.loc[date])*daily_model.daily_prices.loc[date,benchmark]/benchmark_opens.loc[date]+close_flows.loc[date]
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
    daily,sleeve_nav,transfer_events,transfer_audit=_rebalance_mixed_daily(
        daily,sleeve_nav,after_sleeve_nav,weights,sleeve_rebalance_mode,rebalance_sleeve,
        rebalance_cap,rebalance_target,fee,fixed_fee,taxed,tax_rate,
    )
    if sleeve_rebalance_mode != 'none':
        for value,ret in [('pre_tax_value','pre_tax_monthly_return'),('after_tax_value','after_tax_monthly_return')]:
            previous=daily[value].shift(1)
            previous.iloc[0]=initial
            daily[ret]=daily[value]/previous-1
        daily['turnover']+=daily['portfolio_rebalance_turnover']
        daily['allocation_change']=daily['allocation_change'].astype(int)+daily['portfolio_rebalance'].astype(int)
    if transfer_events:
        events.append(pd.DataFrame(transfer_events))
    if transfer_audit:
        audits.append(pd.DataFrame(transfer_audit).assign(sleeve='portfolio transfer'))
    monthly=aggregate_months(daily)
    sleeve_returns=pd.DataFrame({n:r.daily.pre_tax_monthly_return.groupby(r.daily.index.to_period('M')).apply(lambda x:(1+x).prod()-1).to_numpy() for n,r in results.items()},index=monthly.index)
    return PortfolioBacktestResult(monthly,sleeve_returns,sessions,
        pd.concat(events,ignore_index=True) if events else pd.DataFrame(),daily,sleeve_nav,
        pd.concat(audits,ignore_index=True))
