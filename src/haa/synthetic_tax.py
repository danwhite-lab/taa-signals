"""Funded proxy tax books: daily synthetic trades, monthly proxy allocations.

USD/average-cost approximation. Cash is an accumulating proxy instrument,
taxed on realization, not an interest withholding model. No FX/indexation,
cross-sleeve loss netting, terminal liquidation or extra commissions.
"""
from pathlib import Path
from functools import lru_cache
import hashlib
import numpy as np
import pandas as pd
from .tax import IsraeliTaxState

INPUT_HASHES = {
    "NDX": "fdeffa631612b26570b216d9ab668f56bf4199dc61bdf3bb24c34357117f38b1",
    "IRX": "38970fbb92ff6a57e66eea9ad5d46e6ad1fde0b516799e696500478183df0371",
}
EVENT_COLUMNS = ["date", "holding_period", "sold_sleeve", "sold_asset", "proceeds",
                 "cost_basis_sold", "reason", "realized_gain", "taxable_gain",
                 "tax_paid", "loss_carryforward"]


def trade_factors(path):
    """Cache only by current content hashes; changed files still fail closed."""
    path=Path(path).resolve()
    files=[path, path.parent/"inputs/NDX.csv", path.parent/"inputs/IRX.csv"]
    fingerprint=tuple(hashlib.sha256(file.read_bytes()).hexdigest() for file in files)
    return _trade_factors_cached(str(path),fingerprint).copy(deep=True)


@lru_cache(maxsize=4)
def _trade_factors_cached(path, fingerprint):
    """Split exact supplied NAV ratios at verified execution prices.

    Delivered NAV is rounded to 4 decimals. Recomputed unrounded generator
    returns must reconcile to those rounding intervals before being accepted.
    A tiny documented residual in the post-fill factor preserves supplied NAV.
    """
    from .synthetic_history import load_synthetic_daily
    daily = load_synthetic_daily(Path(path))
    raw = {}
    for key, digest in INPUT_HASHES.items():
        file = Path(path).parent / "inputs" / f"{key}.csv"
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Synthetic tax {key} input differs from the reviewed frozen data.")
        raw[key] = pd.read_csv(file, index_col=0, parse_dates=True)
    ndx = raw["NDX"].reindex(daily.index)
    # This yield carry-forward is part of the supplied generator, not a new
    # interpolation of security returns. Persist flags in the audit output.
    rf = raw["IRX"].close.reindex(raw["IRX"].index.union(daily.index)).sort_index().ffill().reindex(daily.index)/100/252
    position = daily.position.map(lambda p: "DEF" if p.startswith("DEF") else p)
    target = daily.position_end_of_day.map(lambda p: "DEF" if p.startswith("DEF") else p)
    if not position.isin(["DEF", "QLD", "TQQQ"]).all() or not target.isin(["DEF", "QLD", "TQQQ"]).all():
        raise ValueError("Unknown synthetic position.")
    if not position.iloc[1:].reset_index(drop=True).equals(target.iloc[:-1].reset_index(drop=True)):
        raise ValueError("Synthetic position continuity is broken.")
    lev = {"DEF": 0., "QLD": 2., "TQQQ": 3.}
    rows=[]; unrounded=100.
    for i, date in enumerate(daily.index):
        old, new = position.iloc[i], target.iloc[i]
        if i == 0:
            rows.append((date, old, new, 1., 1., 1., 0., daily.loc[date,"exec"]))
            continue
        pc=ndx.close.iloc[i-1]; close=ndx.close.iloc[i]; k=rf.iloc[i]
        if not np.isfinite([pc,close,k]).all() or pc<=0 or close<=0:
            raise ValueError("Missing synthetic return inputs; refusing to bridge sessions.")
        carry=lambda p: k if p=="DEF" else -((lev[p]-1)*k+.0095/252)
        switch=old!=new
        if date>=pd.Timestamp("2001-01-02") and switch:
            op=ndx.open.iloc[i]
            if not np.isfinite(op) or op<=0: raise ValueError("Missing synthetic execution open.")
            before=1+lev[old]*(op/pc-1)
            computed=before*(1+lev[new]*(close/op-1))+carry(new)
            expected_exec="NEXT_OPEN_TRADE_TODAY"
        else:
            computed=1+lev[old]*(close/pc-1)+carry(old)
            before=computed if switch else 1.
            expected_exec="NEXT_CLOSE_FALLBACK_pre2001_no_real_NDX_open" if date<pd.Timestamp("2001-01-02") else "NEXT_OPEN_regime_no_trade"
        if daily.loc[date,"exec"] != expected_exec:
            raise ValueError("Synthetic execution flag disagrees with reconstructed trade.")
        unrounded*=computed
        if abs(unrounded-daily.nav.iloc[i])>0.000051+abs(unrounded)*1e-12:
            raise ValueError("Synthetic reconstruction does not reproduce supplied NAV within export rounding.")
        exact=daily.nav.iloc[i]/daily.nav.iloc[i-1]
        # No switch: all of the day's return accrues to the current asset.
        if not switch or date<pd.Timestamp("2001-01-02"): before=exact
        after=exact/before
        if not np.isfinite([before,after]).all() or min(before,after)<=0:
            raise ValueError("Nonpositive modeled execution factor.")
        rows.append((date,old,new,before,after,exact,exact-computed,expected_exec))
    return pd.DataFrame(rows, columns=["date","old_asset","new_asset","before_factor","after_factor","nav_factor","rounding_residual","execution"] ).set_index("date")


class ProxyBook:
    def __init__(self, name, taxed, rate, events, audit):
        self.name=name; self.taxed=taxed; self.tax=IsraeliTaxState(tax_rate=rate if taxed else 0.)
        self.positions={}; self.events=events; self.audit=audit
        self.holding_period=None

    @property
    def value(self): return sum(self.positions.values())

    def buy(self, asset, amount, date, reason):
        if amount<=0: return
        self.positions[asset]=self.positions.get(asset,0.)+amount
        self.tax.buy(asset,amount)
        self.audit.append(dict(date=date,sleeve=self.name,side="buy",asset=asset,amount=amount,reason=reason))

    def sell(self, asset, amount, date, reason):
        current=self.positions.get(asset,0.)
        if amount<=0: return 0.
        if amount>current+max(current,1.)*1e-10: raise ValueError("Proxy sale exceeds position.")
        amount=min(amount,current)
        available_basis=self.tax.cost_bases.get(asset,0.)
        basis=min(available_basis,available_basis*(amount/current))
        event=self.tax.sell(amount,asset=asset,cost_basis_sold=basis)
        paid=event["tax_paid"] if self.taxed else 0.
        self.positions[asset]=max(0.,current-amount)
        self.events.append(dict(date=date,holding_period=self.holding_period,sold_sleeve=self.name,sold_asset=asset,proceeds=amount,cost_basis_sold=basis,reason=reason,**{**event,"tax_paid":paid}))
        self.audit.append(dict(date=date,sleeve=self.name,side="sell",asset=asset,amount=amount,reason=reason,tax_paid=paid))
        return amount-paid

    def mark(self, factor):
        if not np.isfinite(factor) or factor<=0: raise ValueError("Invalid proxy return factor.")
        for asset in self.positions: self.positions[asset]*=factor

    def allocate(self, targets, date, reason):
        # Tax reduces investable capital; iterate surplus sales until targets
        # are self-financing. Never trim cost basis without recording a sale.
        cash=0.
        for _ in range(200):
            total=self.value+cash; sold=False
            for asset,current in list(self.positions.items()):
                surplus=current-total*targets.get(asset,0.)
                if surplus>max(total,1.)*1e-12:
                    cash+=self.sell(asset,surplus,date,reason); sold=True
            if not sold: break
        else: raise ValueError("Tax-aware proxy allocation did not converge.")
        total=self.value+cash
        deficits={a:max(0.,total*w-self.positions.get(a,0.)) for a,w in targets.items()}
        needed=sum(deficits.values())
        for asset,amount in deficits.items():
            self.buy(asset,cash*amount/needed if needed else 0.,date,reason)


def reset_sleeves(books, weights, targets, date, contribution):
    # DCA is new money, never a taxable gain. Deposit to each current holding
    # before resets; any subsequent real reductions are explicitly taxed.
    for name,book in books.items():
        for asset,w in targets[name].items():
            book.buy(asset,contribution*weights[name]*w,date,"DCA")
    cash=0.
    for _ in range(200):
        total=sum(b.value for b in books.values())+cash; sold=False
        for name,book in books.items():
            surplus=book.value-total*weights[name]
            if surplus>max(total,1.)*1e-12:
                value=book.value
                for asset,current in list(book.positions.items()):
                    cash+=book.sell(asset,surplus*current/value,date,"monthly sleeve reset")
                sold=True
        if not sold: break
    else: raise ValueError("Tax-aware sleeve reset did not converge.")
    total=sum(b.value for b in books.values())+cash
    deficits={n:max(0.,total*weights[n]-b.value) for n,b in books.items()}
    needed=sum(deficits.values())
    for name,amount in deficits.items():
        budget=cash*amount/needed if needed else 0.
        for asset,w in targets[name].items(): books[name].buy(asset,budget*w,date,"monthly sleeve reset")


def run_synthetic_tax_portfolio(sleeves, initial, rate, start=None, end=None, monthly_contribution=0.):
    from .engine import run_backtest
    from .portfolio_backtest import PortfolioBacktestResult, run_portfolio_backtest
    from .backtest_options import validate_options
    validate_options(monthly_contribution,0.)
    if not np.isfinite(initial) or initial<=0: raise ValueError("Initial capital must be positive and finite.")
    if not np.isfinite(rate) or not 0<=rate<=1: raise ValueError("Invalid tax rate.")
    weights={n:float(w) for n,(w,_) in sleeves.items()}
    if not weights or any(not np.isfinite(w) or w<=0 for w in weights.values()) or abs(sum(weights.values())-1)>1e-9:
        raise ValueError("Proxy sleeve weights must be positive, finite and total 100%.")
    # Pre-tax uses the existing monthly blend untouched, including DCA.
    pre=run_portfolio_backtest(sleeves,initial,0.,False,rate,start,end,monthly_contribution)
    months=pre.common_index
    if not months.equals(pd.date_range(months[0],months[-1],freq="ME")):
        raise ValueError("Synthetic tax blends require consecutive complete calendar months.")
    if len({m.benchmark_asset for _,m in sleeves.values()})!=1:
        raise ValueError("Proxy sleeves must share a benchmark.")
    factors={}; periods={}
    for name,(_,model) in sleeves.items():
        if model.decisions.attrs.get("synthetic_tax_proxy"):
            frame=trade_factors(model.decisions.attrs["synthetic_source_path"])
            factors[name]=dict(tuple(frame.groupby(frame.index.to_period("M"))))
            benchmark_returns=model.monthly_prices[model.benchmark_asset].pct_change().loc[months]
        else:
            if model.daily_prices is not None or model.decisions.attrs.get("execution_frequency")=="daily":
                raise ValueError("Synthetic tax blends accept monthly proxies, not real daily sleeves.")
            periods[name]=run_backtest(model.decisions,model.monthly_prices,1.,benchmark_asset=model.benchmark_asset).monthly.loc[months]
            benchmark_returns=periods[name].benchmark_monthly_return
        if not np.allclose(benchmark_returns,pre.monthly.benchmark_monthly_return,rtol=1e-12,atol=1e-12):
            raise ValueError("Synthetic tax portfolio sleeves have inconsistent benchmark returns.")
    events=[]; audit=[]
    books={n:ProxyBook(n,True,rate,events,audit) for n in sleeves}
    sleeve_after=[]; values=[]; returns=[]; previous=initial
    for i,month in enumerate(months):
        for book in books.values(): book.holding_period=month
        boundary=month.to_period("M").start_time
        contribution=monthly_contribution if i else 0.
        targets={}
        for name in sleeves:
            if name in factors:
                days=factors[name].get(month.to_period("M"),pd.DataFrame())
                if days.empty: raise ValueError("Missing synthetic month.")
                targets[name]={days.old_asset.iloc[0]:1.}
            else:
                row=periods[name].loc[month]
                targets[name]=row.get("target_weights",{row.selected_asset:1.})
        if not i:
            for name,book in books.items():
                for asset,w in targets[name].items(): book.buy(asset,initial*weights[name]*w,month-pd.offsets.MonthEnd(1),"initial funding")
        else:
            current_targets={n:({a:v/b.value for a,v in b.positions.items() if v>0} if b.value else targets[n]) for n,b in books.items()}
            reset_sleeves(books,weights,current_targets,boundary,contribution)
        for name,book in books.items():
            if name in factors:
                days=factors[name][month.to_period("M")]
                for date,row in days.iterrows():
                    if sum(v for a,v in book.positions.items() if a!=row.old_asset)>max(book.value,1.)*1e-10:
                        raise ValueError("Synthetic book position differs from source execution path.")
                    book.mark(row.before_factor)
                    if row.old_asset!=row.new_asset:
                        cash=book.sell(row.old_asset,book.value,date,row.execution)
                        book.buy(row.new_asset,cash,date,row.execution)
                    book.mark(row.after_factor)
            else:
                book.allocate(targets[name],boundary,"monthly proxy allocation")
                book.mark(1+pre.sleeve_returns.loc[month,name])
        value=sum(b.value for b in books.values())
        values.append(value); returns.append(value/(previous+contribution)-1); previous=value
        sleeve_after.append({n:b.value for n,b in books.items()})
    monthly=pre.monthly.copy()
    monthly["after_tax_value"]=values; monthly["after_tax_monthly_return"]=returns
    monthly["contribution"]=[0.]+[monthly_contribution]*(len(months)-1)
    ledger=pd.DataFrame(events,columns=EVENT_COLUMNS).sort_values("date",kind="stable")
    monthly["tax_paid"]=ledger.groupby("holding_period").tax_paid.sum().reindex(months,fill_value=0.) if not ledger.empty else 0.
    reset_events=ledger.loc[ledger.reason=="monthly sleeve reset"] if not ledger.empty else ledger
    monthly["portfolio_reset_tax"]=reset_events.groupby("holding_period").tax_paid.sum().reindex(months,fill_value=0.) if not reset_events.empty else 0.
    return PortfolioBacktestResult(monthly,pre.sleeve_returns,months,ledger,
                                  sleeve_nav=pd.DataFrame(sleeve_after,index=months),audit=pd.DataFrame(audit).sort_values("date",kind="stable"))


def run_synthetic_tax_single(daily, prices, initial, start, end, benchmark, contribution, rate, path):
    from .engine import BacktestResult
    from .synthetic_history import run_synthetic_nav_backtest
    if not np.isfinite(rate) or not 0<=rate<=1: raise ValueError("Invalid tax rate.")
    pre=run_synthetic_nav_backtest(daily,prices,initial,start,end,benchmark,contribution)
    factors=trade_factors(path).loc[pre.daily.index]
    events=[]; audit=[]
    book=ProxyBook("A-RVol synthetic",True,rate,events,audit)
    anchor_date=daily.index[daily.index<factors.index[0]][-1]
    book.buy(factors.old_asset.iloc[0],initial,anchor_date,"initial funding at prior-month anchor")
    values=[]; returns=[]; previous=initial
    for date,row in factors.iterrows():
        book.holding_period=date.to_period("M").to_timestamp("M")
        flow=pre.daily.loc[date,"contribution"]
        book.buy(row.old_asset,flow,date,"DCA before daily return")
        book.mark(row.before_factor)
        if row.old_asset!=row.new_asset:
            cash=book.sell(row.old_asset,book.value,date,row.execution)
            book.buy(row.new_asset,cash,date,row.execution)
        book.mark(row.after_factor)
        values.append(book.value); returns.append(book.value/(previous+flow)-1); previous=book.value
    observed=pre.daily.copy()
    observed["after_tax_value"]=values; observed["after_tax_daily_return"]=returns
    monthly=pre.monthly.copy()
    end_values=observed.after_tax_value.groupby(observed.index.to_period("M")).last()
    month_returns=observed.after_tax_daily_return.groupby(observed.index.to_period("M")).apply(lambda r:(1+r).prod()-1)
    monthly["after_tax_value"]=end_values.to_numpy(); monthly["after_tax_monthly_return"]=month_returns.to_numpy()
    ledger=pd.DataFrame(events,columns=EVENT_COLUMNS)
    monthly["tax_paid"]=ledger.groupby("holding_period").tax_paid.sum().reindex(monthly.index,fill_value=0.) if not ledger.empty else 0.
    return BacktestResult(monthly,pd.DataFrame(audit),ledger,observed)
