"""Original portfolio-comparison orchestration, without identical-range reruns."""
import numpy as np
import pandas as pd
from haa.comparison import ComparisonResult
from haa.portfolio_backtest import run_portfolio_backtest
from haa.mixed_portfolio import run_mixed_portfolio
from .performance import span


def compare_portfolios(portfolios, initial, fee=0., taxed=False, tax_rate=.25, start=None, end=None, drift=False, monthly_contribution: float = 0.):
    if not drift:
        from haa.portfolio_comparison import compare_portfolios as original
        with span("backtest_seconds"):
            return original(portfolios,initial,fee,taxed,tax_rate,start,end,drift=False,monthly_contribution=monthly_contribution)
    if len(portfolios)<2: raise ValueError("Select at least two portfolios.")
    inputs=[m for sleeves in portfolios.values() for _,m in sleeves.values()]
    currencies={m.execution_currency for m in inputs}
    if len(currencies)!=1 or not currencies.issubset({"USD","ILS"}):
        raise ValueError("Portfolio comparisons require one shared execution currency (USD or ILS); mixed currencies need historical FX conversion, which is not supported.")
    if len({m.benchmark_asset for m in inputs})!=1: raise ValueError("All compared portfolios must share the same benchmark.")
    if not drift and any(m.decisions.attrs.get("execution_frequency")=="daily" for m in inputs):
        raise ValueError("A-RVol comparisons require initial weights / daily valuation, not monthly resets.")
    engine=run_mixed_portfolio if drift else run_portfolio_backtest
    with span("backtest_seconds"):
        preliminary={name:engine(sleeves,initial,fee,taxed,tax_rate,start,end,monthly_contribution=monthly_contribution) for name,sleeves in portfolios.items()}
    common=None
    for result in preliminary.values():common=result.common_index if common is None else common.intersection(result.common_index)
    common=pd.DatetimeIndex(common).sort_values()
    if common.empty:raise ValueError("The selected portfolios have no shared executable history.")
    if drift:
        from haa.market_sessions import us_equity_sessions, tase_equity_sessions
        sessions=tase_equity_sessions if currencies=={"ILS"} else us_equity_sessions
        expected=sessions(str(common[0].date()),str(common[-1].date()))
    else:
        expected=common
        months=common.to_period("M")
        if months.has_duplicates or not months.equals(pd.period_range(months[0],months[-1],freq="M")):
            raise ValueError("Shared monthly comparison history contains missing or duplicate holding periods.")
    results={}
    for name,sleeves in portfolios.items():
        prior=preliminary[name]
        if prior.common_index.equals(expected):results[name]=prior
        else:
            with span("backtest_seconds"):results[name]=engine(sleeves,initial,fee,taxed,tax_rate,common[0],common[-1],monthly_contribution=monthly_contribution)
    for result in results.values():
        if not result.common_index.equals(expected):raise ValueError("Portfolio histories contain gaps or unequal execution periods; comparison refused.")
        first=next(iter(results.values()))
        observations=result.daily if drift else result.monthly
        reference=first.daily if drift else first.monthly
        if not np.allclose(observations.benchmark_value,reference.benchmark_value,rtol=1e-12):
            raise ValueError("Compared portfolios have inconsistent benchmark histories.")
    availability=pd.DataFrame([{"Portfolio":name,"Tested from":r.common_index[0],"Tested through":r.common_index[-1],"Observations":len(r.common_index)} for name,r in results.items()])
    return ComparisonResult(results,expected,availability)
