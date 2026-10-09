#!/usr/bin/env python3
"""
A-RVol sleeve v5 generator  --  independent reconstruction of the sleeve rules AS SPECIFIED BY DANIEL
(the app's repo "taa-signals" was NOT readable by the author of this script, so every rule below is taken from
the written spec relayed from Daniel's Codex review; interpretations are marked  [INTERP-n]  and can be toggled).

INPUT DATA (daily, Yahoo Finance chart API, downloaded automatically into ./data_cache/, or put your own CSVs there
with columns date,open,high,low,close,adj):
  ^NDX  (Nasdaq-100 price index; open from 2001 is a real open, before 2001 Yahoo "open" is mostly the prior close)
  ^GSPC (S&P 500 price index, only used before 1988-01)
  ^SP500TR (S&P 500 total return index, from 1988-01)
  ^IRX  (13-week T-bill yield, percent; synthetic cash and financing)
  HYG, LQD (credit gate, from 2007-04; before that the gate is OFF)
  optional reference only: QLD, TQQQ adj close (not used in NAV)
OUTPUT: arvol_synthetic_daily.txt / arvol_synthetic_monthly.txt (CSV with a '#' comment header).
USAGE:  python3 arvol_v4.py [--outdir DIR] [--start 1986-11-03]
Everything is USD, pre-tax, no commissions.

SIGNALS (evaluated at the CLOSE of day t, only data <= t used):
  RVol   = stdev of the last 15 NDX daily log returns * sqrt(252)
  VR     = RVol / mean(RVol over the last 252 days)
  Trend  = CSPX / SMA200(CSPX) - 1   where CSPX = S&P 500 TR (SP500TR; GSPC price before 1988) minus 0.07%/yr
  Credit = (HYG/LQD) / (HYG/LQD 20 days ago) - 1 using ADJUSTED (dividend-adjusted) closes ; gate fires if Credit < -4% (only from 2007-05-09)
  Donchian = NDX <= lowest NDX close of last 40 days AND RVol >= 20%
STATE MACHINE (start DEF at the start date):
  DEF  -> QLD   if RVol<25% and VR<1.10 and Trend>-1.5%                       (DEF can ONLY enter QLD, never TQQQ)
  QLD  -> TQQQ  if RVol<14% and VR<0.90 and Trend>+3%
  TQQQ -> QLD   if RVol>18% or VR>1.25 or Trend<-3%                            (ONLY these three; no credit/Donchian/36%/1.40 triggers)
  QLD  -> DEF   ordinary exit: RVol>36% or VR>1.40 or Trend<-3% or Credit<-4%, or Donchian
  Donchian lock: starts when QLD->DEF happens because of Donchian ONLY             [INTERP-1: if an ordinary exit also fires the same
                 day, the ordinary exit takes priority and NO lock starts]
                 while locked: stay DEF. Release when NDX >= 1.03 x lowest NDX close of last 5 days (including today)
                 or 20 sessions have passed; release goes DIRECTLY to QLD regardless of ordinary exit conditions (the app owner's ruling).
                 [INTERP-2 (release blocked when an ordinary exit is active that day) was considered and REJECTED by the app owner; it can be
                 re-enabled for comparison with --interp2 but is NOT the default.]
  A Donchian lock can never start while already in DEF/cash.
EXECUTION: signal at close t -> trade at the NEXT trading day's OPEN (t+1) from 2001-01-02 (first year with real NDX opens);
           before 2001-01-02 -> next-day CLOSE (flag column).  Position cannot jump DEF->TQQQ: if the target is TQQQ while held
           DEF, the trade goes to QLD first (safety clamp; cannot trigger because the machine itself never skips QLD).
RETURNS (synthetic, USD): fund return on a non-trade day = L x NDX close-to-close return - (L-1) x IRX/252 - 0.95%/252 (QLD L=2, TQQQ L=3);
           cash = IRX/252.  Trade day with open execution = (1 + L_old x overnight) x (1 + L_new x intraday) - 1 + carry_new, where
           carry/fee of the day is charged to the position held at the close [assumption].
"""
import argparse, io, json, os, subprocess, sys
import numpy as np, pandas as pd

TER_SP = 0.0007; FEE_LEV = 0.0095; OPEN_FROM = pd.Timestamp('2001-01-02')
L = {'DEF': 0, 'QLD': 2, 'TQQQ': 3}

def yahoo(sym, cache='data_cache'):
    os.makedirs(cache, exist_ok=True); fn = os.path.join(cache, sym.replace('^', '') + '.csv')
    if not os.path.exists(fn) and os.path.exists(fn[:-4] + '.txt'): fn = fn[:-4] + '.txt'   # data files may be shipped as .txt
    if not os.path.exists(fn):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym.replace('^','%5E')}?period1=470000000&period2=2000000000&interval=1d"
        raw = subprocess.check_output(['curl', '-s', '-m', '60', '-A', 'Mozilla/5.0', url])
        j = json.loads(raw)['chart']['result'][0]; q = j['indicators']['quote'][0]
        adj = j['indicators'].get('adjclose', [{}])[0].get('adjclose', q['close'])
        df = pd.DataFrame({'open': q['open'], 'high': q['high'], 'low': q['low'], 'close': q['close'], 'adj': adj},
                          index=pd.to_datetime(j['timestamp'], unit='s').normalize())
        df.index.name = 'date'; df.to_csv(fn)
    return pd.read_csv(fn, index_col=0, parse_dates=True)

def build_inputs(start):
    gs = yahoo('^GSPC'); cal = gs.index[gs.index >= '1985-10-01']          # calendar = S&P trading days
    ndx = yahoo('^NDX'); ndx_c = ndx.close.reindex(cal).ffill(); ndx_o = ndx.open.reindex(cal)
    irx = (yahoo('^IRX').close / 100).reindex(cal).ffill(); rf = irx / 252
    sp = yahoo('^SP500TR').close.reindex(cal); spret = sp.pct_change()
    gret = gs.close.reindex(cal).pct_change()
    spr = spret.where(sp.notna().cumsum() > 1, gret).fillna(0.)            # price-only S&P before 1988 (flag)
    cspx = (1 + spr - TER_SP / 252).cumprod()
    hyg = yahoo('HYG').adj.reindex(cal); lqd = yahoo('LQD').adj.reindex(cal)   # v5: ADJUSTED (dividend-adjusted) prices, matching the app
    return cal, ndx_c, ndx_o, rf, cspx, hyg, lqd

def signals(cal, ndx_c, cspx, hyg, lqd):
    lr = np.log(ndx_c / ndx_c.shift(1)); rv = lr.rolling(15).std() * np.sqrt(252); vr = rv / rv.rolling(252).mean()
    tr = cspx / cspx.rolling(200).mean() - 1
    ratio = hyg / lqd; cr = ratio / ratio.shift(20) - 1
    return rv, vr, tr, cr, ndx_c.rolling(40).min(), ndx_c.rolling(5).min()

def machine(cal, ndx_c, ind, start, interp1=True, interp2=False):
    rv, vr, tr, cr, lo40, lo5 = ind
    state = 'DEF'; lock = None; S = {}
    for d in cal[cal >= pd.Timestamp(start)]:
        if np.isnan(vr[d]) or np.isnan(tr[d]): raise RuntimeError('indicators not ready at ' + str(d))
        R, V, T, C = rv[d], vr[d], tr[d], cr[d]
        cg = (not np.isnan(C)) and C < -0.04
        ordinary = R > .36 or V > 1.4 or T < -.03 or cg
        don = (ndx_c[d] <= lo40[d]) and R >= .20
        if lock is not None:                                   # locked: stay DEF until release
            lock += 1
            if ndx_c[d] >= 1.03 * lo5[d] or lock >= 20:
                lock = None
                state = 'DEF' if (interp2 and ordinary) else 'QLD'   # release goes DIRECTLY to QLD (unless INTERP-2)
        else:
            if state == 'TQQQ':
                if R > .18 or V > 1.25 or T < -.03: state = 'QLD'
            elif state == 'QLD':
                if ordinary or don:
                    state = 'DEF'
                    if don and not (interp1 and ordinary): lock = 0
                elif R < .14 and V < .9 and T > .03: state = 'TQQQ'
            else:
                if R < .25 and V < 1.1 and T > -.015: state = 'QLD'
        S[d] = state
    return pd.Series(S)

def run_path(cal, ndx_c, ndx_o, rf, S, open_exec=True):
    days = list(S.index); nav = 100.; held = 'DEF'; rows = []
    prev_sig = None
    for i, d in enumerate(days):
        if i == 0: rows.append((d, 'DEF', 0., nav, 'DEF', 'START')); continue
        sig = S[days[i - 1]]                                   # signal from the previous close
        tgt = 'QLD' if (held == 'DEF' and sig == 'TQQQ') else sig   # clamp: DEF can never jump to TQQQ
        pc = ndx_c[days[i - 1]]; k = rf[d]; rday = ndx_c[d] / pc - 1
        carry = lambda p: k if p == 'DEF' else -((L[p] - 1) * k + FEE_LEV / 252)
        if open_exec and d >= OPEN_FROM:
            ron = ndx_o[d] / pc - 1; rid = ndx_c[d] / ndx_o[d] - 1
            if tgt != held: r = (1 + L[held] * ron) * (1 + L[tgt] * rid) - 1 + carry(tgt); basis = 'NEXT_OPEN_TRADE_TODAY'
            else: r = L[held] * rday + carry(held); basis = 'NEXT_OPEN_regime_no_trade'
            new = tgt
        else:                                                  # pre-2001 fallback: trade at today's close (signal was yesterday's close)
            r = L[held] * rday + carry(held); basis = 'NEXT_CLOSE_FALLBACK_pre2001_no_real_NDX_open'; new = tgt
        nav *= 1 + r; rows.append((d, held, r, nav, new, basis)); held = new
    return pd.DataFrame(rows, columns=['date', 'pos_before', 'ret', 'nav', 'pos_end', 'exec']).set_index('date')

def stats(nav):
    y = (nav.index[-1] - nav.index[0]).days / 365.25; c = (nav.iloc[-1] / nav.iloc[0]) ** (1 / y) - 1
    top = nav.cummax(); dd = nav / top - 1; mx = 0; sd = None
    for d, v in (nav < top).items():
        if v: sd = sd or d; mx = max(mx, (d - sd).days)
        else: sd = None
    return round(c * 100, 2), round(dd.min() * 100, 1), mx

HEADER = """# A-RVol sleeve v5. RULES PER DANIEL'S APP OWNER RULING (Codex review), implemented from the written spec, NOT from the app code (repo taa-signals not readable). Not the author's original rules, not BestFolio. Independent reconstruction. REPLACES v4.
# USD, PRE-TAX, NO commissions. NAV=100 on {start}. Engine DAILY. Signal at close t, trade NEXT-DAY OPEN from 2001-01-02, NEXT-DAY CLOSE before (exec column; Yahoo ^NDX opens before 2001 are mostly the previous close, i.e. not real opens).
# RULES: see the docstring of the generating script arvol_v4.py (attached separately). Summary: DEF->QLD if RVol<25% & VR<1.10 & Trend>-1.5% (DEF enters ONLY via QLD); QLD->TQQQ if RVol<14% & VR<0.90 & Trend>+3%; TQQQ->QLD if RVol>18% or VR>1.25 or Trend<-3% (only these); QLD->DEF if RVol>36% or VR>1.40 or Trend<-3% or Credit(HYG/LQD 20d)<-4% or Donchian (NDX<=40d low & RVol>=20%); Donchian lock only when Donchian is the sole exit reason [INTERP-1], stay DEF until NDX>=3% above 5d low or 20 sessions, then DIRECTLY to QLD regardless of ordinary exit conditions (app owner's ruling; the alternative 'stay DEF if an ordinary exit is active' [INTERP-2] was considered and REJECTED).
# CHANGES v5 vs v4: (a) release always goes to QLD (INTERP-2 removed from the default path); (b) credit gate computed on ADJUSTED HYG/LQD closes (v4 used unadjusted closes).
# CHANGES v4 vs v3: (1) TQQQ->QLD no longer fires on credit gate, Donchian, RVol>36%/VR>1.40 specific triggers; (2) machine starts DEF at the start date and cannot jump DEF->TQQQ (v3 could, via a pre-start state); (3) ordinary defensive exits take priority over Donchian locking [INTERP-1/2].
# POSITION = position held DURING the day before any trade at that day's open; position_end_of_day = after the trade. Trade-day return = old position overnight x new position open->close.
# PROXIES/FLAGS: QLD/TQQQ SYNTHETIC for the whole file (L x NDX price return - (L-1) x T-bill/252 - 0.95%/yr; real funds launched 2006-06-21 / 2010-02-11, flag REAL_FUND_EXISTED_SERIES_STILL_MODELED_*; no real prices spliced). Cash = synthetic T-bill from ^IRX (not BIL). NDX = price index. Trend input S&P 500 TR (price index before 1988) minus 0.07%. Credit gate (adjusted HYG/LQD) only from 2007-05-09. Model runs ~1.3 pt/yr (QLD) and ~2.2 pt/yr (TQQQ) BELOW real fund returns in the overlap. real_fund_adj_return_REFERENCE_ONLY is not used in nav. 1994-start variant = same path, NAV rebased to 100 on 1994-01-03.
"""

def export(outdir, start, S, P, extra_ref=True):
    os.makedirs(outdir, exist_ok=True)
    d = P.copy(); nm = {'DEF': 'DEF(cash:synthetic T-bill)', 'QLD': 'QLD', 'TQQQ': 'TQQQ'}
    d['position'] = d.pos_before.map(nm); d['pos_end'] = d.pos_end.map(nm)
    def flag(h, dt):
        if h.startswith('DEF'): return 'SYN_CASH'
        k = 'QLD' if h == 'QLD' else 'TQQQ'
        real = dt >= (pd.Timestamp('2006-06-21') if k == 'QLD' else pd.Timestamp('2010-02-11'))
        return ('REAL_FUND_EXISTED_SERIES_STILL_MODELED_' if real else 'SYN_') + k
    d['flag'] = [flag(h, i) for i, h in zip(d.index, d.position)]
    d['credit_gate'] = np.where(d.index >= pd.Timestamp('2007-05-09'), 'ON', 'OFF_no_HYG_LQD_data')
    ref = pd.Series(np.nan, index=d.index)
    try:
        for k in ['QLD', 'TQQQ']:
            a = yahoo(k).adj.pct_change(); m = d.position.eq(k) & d.index.isin(a.index)
            ref[m] = a.reindex(d.index)[m]
    except Exception: pass
    d['ref'] = ref
    n94 = d.nav / d.nav[d.index >= pd.Timestamp('1994-01-03')].iloc[0] * 100
    d['nav94'] = np.where(d.index >= pd.Timestamp('1994-01-03'), n94, np.nan)
    cols = ['date', 'position', 'sleeve_return', 'nav', 'nav_1994start', 'position_end_of_day', 'exec', 'synthetic_flag', 'credit_gate', 'real_fund_adj_return_REFERENCE_ONLY']
    def write(path, x, fr):
        with open(path, 'w') as f:
            f.write(HEADER.format(start=start) + f"# frequency: {fr}\n" + ",".join(cols) + "\n")
            for dt, r in x.iterrows():
                f.write(f"{dt.date()},{r.position},{r.ret:.6f},{r.nav:.4f},{'' if np.isnan(r.nav94) else format(r.nav94, '.4f')},{r.pos_end},{r.exec},{r.flag},{r.credit_gate},{'' if np.isnan(r.ref) else format(r.ref, '.6f')}\n")
    me = d.groupby([d.index.year, d.index.month]).tail(1).copy()
    me['ret'] = d.nav.groupby([d.index.year, d.index.month]).last().pct_change().values; me.loc[me.index[0], 'ret'] = 0.; me['ref'] = np.nan
    write(os.path.join(outdir, 'arvol_synthetic_daily.txt'), d, 'daily (engine path)')
    write(os.path.join(outdir, 'arvol_synthetic_monthly.txt'), me, 'month-end rows of the daily file; sleeve_return = month-end to month-end NAV change; reference column blank')
    return d

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--outdir', default='.'); ap.add_argument('--start', default='1986-11-03')
    ap.add_argument('--no-interp1', action='store_true'); ap.add_argument('--interp2', action='store_true', help='NOT the default: rejected interpretation'); a = ap.parse_args()
    cal, ndx_c, ndx_o, rf, cspx, hyg, lqd = build_inputs(a.start); ind = signals(cal, ndx_c, cspx, hyg, lqd)
    S = machine(cal, ndx_c, ind, a.start, not a.no_interp1, a.interp2); P = run_path(cal, ndx_c, ndx_o, rf, S)
    d = export(a.outdir, a.start, S, P)
    print('1986-start (CAGR%, maxDD%, longest underwater days):', stats(P.nav))
    p94 = P[P.index >= '1994-01-03'].nav; print('1994-start:', stats(p94 / p94.iloc[0]))
