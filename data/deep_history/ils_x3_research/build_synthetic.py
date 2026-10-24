"""Reproducible generator for SYNTHETIC ILS x3 research series.
Usage: python build_synthetic.py raw_inputs.xlsx OUTDIR
Reads only raw_inputs.xlsx (sheets are verbatim downloads, see README sheet of outputs). No network.
RESEARCH-ONLY scenarios; not the funds' actual rules (emergency reset unknown)."""
import sys, os, numpy as np, pandas as pd
RAW=sys.argv[1] if len(sys.argv)>1 else 'raw_inputs.xlsx'; OUT=sys.argv[2] if len(sys.argv)>2 else '.'
os.makedirs(OUT,exist_ok=True)
def sh(n,col='value'):
    d=pd.read_excel(RAW,sheet_name=n,index_col=0,parse_dates=True).sort_index()
    assert d.index.is_unique, f'duplicate dates in {n}: {list(d.index[d.index.duplicated()][:5])}'   # fail loudly, never drop silently
    x=d if col is None else d[col]
    nn_=int(x.isna().sum().sum() if col is None else x.isna().sum())
    if nn_: print(f'NOTE {n}: {nn_} missing value(s) at', list((x[x.isna().any(axis=1)] if col is None else x[x.isna()]).index.date), '-> forward-filled (only allowed for usd_13wk_bill)'); assert n=='usd_13wk_bill'; x=x.ffill()
    return x
ta=sh('ta125_137_tr'); mk=sh('makam_800_tr'); ndx=sh('ndx_price_NDX'); xg=sh('xndx_gross_tr'); nn=sh('xndxnnr_official_ntr'); fx=sh('usdils_boi'); tb=sh('usd_13wk_bill','coupon_equiv_13wk')   # decimal, e.g. 0.0414
ayr=sh('REAL_ayalon_5117684',None)['Sell Price']; mtr=sh('REAL_mtf_1187079',None)['close_agorot']
cal=ta.index[ta.index>='2003-12-31']                     # TASE trading days of index 137
days=np.r_[0,np.diff(cal.values).astype('timedelta64[D]').astype(int)]   # calendar days per step (weekend/holiday gaps)
# --- NTR: official XNDXNNR from 2011-10-10, before that Nasdaq's published rule (70% of dividend return reinvested)
rg=xg.pct_change(); rp=ndx.pct_change(); rder=(rp+0.7*(rg-rp)).dropna()
cum=(1+rder).cumprod(); first=nn.index[0]; der=cum*nn.iloc[0]/cum.loc[first]
ntr=pd.concat([der[der.index<first],nn]).sort_index()
def asof(s,dates,strict=False):
    pos=s.index.searchsorted(dates,side='left' if strict else 'right')-1
    assert (pos>=0).all(); res=pd.Series(s.values[pos],index=dates); used=s.index[pos]
    assert (used<dates).all() if strict else (used<=dates).all()      # NO LOOKAHEAD audit
    res.attrs['used']=used; return res
def engine(r,rf,days,lev,reset=None,band=None,fee=0.0,em_thr=None):
    """Fixed-notional replication. NAV earns rf on all NAV; notional N earns excess (r-rf); N drifts with the index
    between resets (borrowed amount N-NAV evolves, it is NOT held at 200%). Fee accrues daily by calendar days.
    NAV<=0 => ruin: NAV floored at 0 and flagged (never reached in the primary scenarios; asserted below)."""
    nav=1.0;N=lev;out=[1.0];expo=[lev];ruin=False;base=1.0;cumi=1.0;nem=0
    for i in range(1,len(r)):
        nav=nav*(1+rf[i])+N*(r[i]-rf[i])-fee*days[i]/365*nav; N*=1+r[i]; cumi*=1+r[i]
        if nav<=0: nav=0.0; ruin=True
        e=N/nav if nav>0 else np.inf
        do=(reset is not None and reset[i]) or (band is not None and not(band[0]<=e<=band[1]))
        em=(em_thr is not None and cumi/base-1<=-em_thr and not (reset is not None and reset[i]))
        if (do or em) and nav>0:
            N=lev*nav; base=cumi; nem+=bool(em)
        out.append(nav); expo.append(e)
    return np.array(out),np.array(expo),ruin,nem
# ---- Ayalon-style TA-125 x3
r=ta.reindex(cal).pct_change().fillna(0).values
rf=mk.reindex(cal).ffill().pct_change().fillna(0).values   # Makam TR return over the same step (realised, no lookahead)
FEE_A=0.0185+0.0004
A_band,eA,ruinA,_=engine(r,rf,days,3,None,(2.8,3.2),FEE_A)
A_day,_,_,_=engine(r,rf,days,3,np.ones(len(cal),bool),None,FEE_A)
# ---- MTF-style Nasdaq x3 monthly
I=asof(ntr,cal,strict=True)                                # last US close strictly before the TASE date
rI=I.pct_change().fillna(0).values
rfu=asof(tb,cal,strict=True).values*days/365               # bill rate known the day before
fxv=asof(fx,cal).values                                    # BoI representative rate same TASE day
mon=pd.Series(cal.to_period('M'),index=cal); last=(mon!=mon.shift(-1)).values
FEE_M=0.0135+0.0003
M_usd,eM,ruinM,_=engine(rI,rfu,days,3,last,None,FEE_M)
assert not ruinA and not ruinM and (M_usd>0).all() and (A_band>0).all(), 'ruin/negative NAV'
M_ils=M_usd*fxv/fxv[0]
M_day,_,_,_=engine(rI,rfu,days,3,np.ones(len(cal),bool),None,FEE_M); M_day_ils=M_day*fxv/fxv[0]
sens=[]
for thr in [None,0.10,0.15,0.20]:
    s,_,ru,n=engine(rI,rfu,days,3,last,None,FEE_M,thr); s=pd.Series(s*fxv/fxv[0],index=cal)
    sens.append(dict(scenario='monthly reset only (primary)' if thr is None else f'ILLUSTRATIVE emergency reset at {int(thr*100)}% index fall from last reset',emergency_resets=n,ruin=ru,CAGR=s.iloc[-1]**(365.25/(cal[-1]-cal[0]).days)-1,maxDD_daily=(s/s.cummax()-1).min(),min_month_return=s.resample('ME').last().pct_change().min()))
D=pd.DataFrame({'TA125_TR_index':ta.reindex(cal).values,'Makam800_TR_index':mk.reindex(cal).ffill().values,'NTR_used_prev_US_close':I.values,'USDILS_BoI':fxv,
 'SYN_TA125x3_band':A_band,'SYN_TA125x3_exposure':eA,'SYN_TA125x3_dailyreset_sens':A_day,
 'SYN_Nasdaq100x3_monthly_ILS':M_ils,'SYN_Nasdaq100x3_exposure':eM,'SYN_Nasdaq100x3_dailyreset_ILS_sens':M_day_ils},index=cal)
D['NTR_US_source_date']=I.attrs['used']; D['NTR_source']=np.where(I.attrs['used']<first,'derived by Nasdaq rule','official XNDXNNR'); D['REAL_Ayalon_sell']=ayr.reindex(cal); D['REAL_MTF_close']=mtr.reindex(cal)
def mret(s): m=s.dropna().groupby(s.dropna().index.to_period('M')).last(); return m.pct_change().dropna()
MR=pd.DataFrame({'SYN_TA125x3_band':mret(D.SYN_TA125x3_band),'SYN_TA125x3_dailyreset_sens':mret(D.SYN_TA125x3_dailyreset_sens),'SYN_Nasdaq100x3_monthly_ILS':mret(D.SYN_Nasdaq100x3_monthly_ILS),
 'SYN_Nasdaq100x3_dailyreset_ILS_sens':mret(D.SYN_Nasdaq100x3_dailyreset_ILS_sens),'BENCH_TA125_TR_ILS_1x':mret(D.TA125_TR_index),'BENCH_NasdaqNTR_ILS_1x':mret(pd.Series(I.values*fxv,index=cal))}).loc['2004-01':'2026-09']
MR['REAL_Ayalon5117684']=mret(D.REAL_Ayalon_sell); MR['REAL_MTF1187079']=mret(D.REAL_MTF_close)
MR.index=MR.index.to_timestamp('M')
def tidy(c,fn,df=MR):
    x=df[c].dropna(); pd.DataFrame({'year':x.index.year,'month':x.index.month,'nominalReturn':x.values.round(8)}).to_csv(os.path.join(OUT,fn),index=False)
tidy('SYN_TA125x3_band','synthetic_ta125x3_ils_monthly_returns.csv'); tidy('SYN_Nasdaq100x3_monthly_ILS','synthetic_nasdaq100x3_ils_monthly_returns.csv')
tidy('BENCH_TA125_TR_ILS_1x','bench_ta125_tr_ils_monthly_returns.csv'); tidy('BENCH_NasdaqNTR_ILS_1x','bench_nasdaq100_ntr_ils_monthly_returns.csv')
# ---- validation vs real, monthly, with uncertainty
rng=np.random.default_rng(0)
def val(syn,real,start,name):
    j=MR[[syn,real]].loc[start:].dropna(); n=len(j); d=j[syn]-j[real]
    ann=lambda x:(1+x).prod()**(12/len(x))-1
    gap=ann(j[syn])-ann(j[real])
    bs=[]; b=3; nb=int(np.ceil(n/b))
    for _ in range(2000):
        ix=np.concatenate([np.arange(s,s+b) for s in rng.integers(0,n-b+1,nb)])[:n]; jj=j.iloc[ix]; bs.append(ann(jj[syn])-ann(jj[real]))
    return dict(case=name,months=n,syn_CAGR=ann(j[syn]),real_CAGR=ann(j[real]),gap_pp_per_yr=gap*100,gap_boot95_lo=np.percentile(bs,2.5)*100,gap_boot95_hi=np.percentile(bs,97.5)*100,
      mean_monthly_diff_pp=d.mean()*100,tstat_mean_diff=d.mean()/(d.std()/np.sqrt(n)),monthly_corr=j[syn].corr(j[real]),mean_abs_diff_pp=d.abs().mean()*100,max_abs_diff_pp=d.abs().max()*100)
V=pd.DataFrame([val('SYN_TA125x3_band','REAL_Ayalon5117684','2013-01','Ayalon band, 2013-01+'),val('SYN_TA125x3_band','REAL_Ayalon5117684','2014-01','Ayalon band, 2014-01+ (excl. launch year)'),
 val('SYN_TA125x3_dailyreset_sens','REAL_Ayalon5117684','2014-01','Ayalon daily-reset sens., 2014-01+'),
 val('SYN_Nasdaq100x3_monthly_ILS','REAL_MTF1187079','2022-08','MTF monthly reset, 2022-08+'),val('SYN_Nasdaq100x3_dailyreset_ILS_sens','REAL_MTF1187079','2022-08','MTF daily-reset sens., 2022-08+')])
# standalone reset-at-launch validation (engine restarted at 3x on the fund's first day; no 2003 history in the leverage state)
def sim_from(kind,start):
    k=cal>=pd.Timestamp(start); c=cal[k]; dy=days[k].copy(); dy[0]=0
    if kind=='A': a,_,_,_=engine(r[k],rf[k],dy,3,None,(2.8,3.2),FEE_A); return pd.Series(a,index=c)
    a,_,_,_=engine(rI[k],rfu[k],dy,3,last[k],None,FEE_M); return pd.Series(a*fxv[k]/fxv[k][0],index=c)
def val2(sy,real,start,name):
    j=pd.concat({'s':sy,'r':real},axis=1).dropna().resample('ME').last().pct_change().dropna().loc[start:]; n=len(j); d=j.s-j.r
    ann=lambda x:(1+x).prod()**(12/len(x))-1
    return dict(case=name,months=n,syn_CAGR=ann(j.s),real_CAGR=ann(j.r),gap_pp_per_yr=(ann(j.s)-ann(j.r))*100,mean_monthly_diff_pp=d.mean()*100,tstat_mean_diff=d.mean()/(d.std()/np.sqrt(n)),monthly_corr=j.s.corr(j.r),mean_abs_diff_pp=d.abs().mean()*100,max_abs_diff_pp=d.abs().max()*100)
V2=pd.DataFrame([val2(sim_from('A','2012-12-30'),D.REAL_Ayalon_sell,'2013-01','STANDALONE reset-at-launch: Ayalon band, 2013-01+'),val2(sim_from('A','2012-12-30'),D.REAL_Ayalon_sell,'2014-01','STANDALONE reset-at-launch: Ayalon band, 2014-01+'),
 val2(sim_from('M','2022-07-05'),D.REAL_MTF_close,'2022-08','STANDALONE reset-at-launch: MTF monthly, 2022-08+')])
# daily diagnostics
dd=D[['SYN_Nasdaq100x3_monthly_ILS','REAL_MTF_close']].dropna().pct_change().dropna(); daily_corr_mtf=dd.corr().iloc[0,1]
da=D[['SYN_TA125x3_band','REAL_Ayalon_sell']].dropna().pct_change().dropna(); daily_corr_ay=da.corr().iloc[0,1]
V.attrs['daily']=(daily_corr_ay,daily_corr_mtf)
def stats(x): x=x.dropna();nav=pd.concat([pd.Series([1.0]),(1+x).cumprod().reset_index(drop=True)]);return dict(months=len(x),CAGR=(1+x).prod()**(12/len(x))-1,vol=x.std()*12**.5,worst_month=x.min(),maxDD_monthly=(nav/nav.cummax()-1).min())
ST=pd.DataFrame({c:stats(MR[c]) for c in MR.columns}).T
SE=pd.DataFrame(sens)
with pd.ExcelWriter(os.path.join(OUT,'synthetic_x3_results.xlsx'),engine='xlsxwriter') as w:
    mm=MR.copy(); mm.index=mm.index.strftime('%Y-%m'); mm.to_excel(w,sheet_name='Monthly_returns'); ST.to_excel(w,sheet_name='Stats'); V.to_excel(w,sheet_name='Validation',index=False); V2.to_excel(w,sheet_name='Validation_standalone',index=False);
    for c_,n_ in [('SYN_TA125x3_band','synthetic_ta125x3_ils'),('SYN_Nasdaq100x3_monthly_ILS','synthetic_nasdaq100x3_ils'),('BENCH_TA125_TR_ILS_1x','bench_ta125_tr_ils'),('BENCH_NasdaqNTR_ILS_1x','bench_nasdaq100_ntr_ils')]:
        x_=MR[c_].dropna(); pd.DataFrame({'year':x_.index.year,'month':x_.index.month,'nominalReturn':x_.values.round(8)}).to_excel(w,sheet_name=('csv_'+n_)[:31],index=False)
    SE.to_excel(w,sheet_name='MTF_emergency_sens',index=False)
    D2=D.copy(); D2.index=D2.index.strftime('%Y-%m-%d'); D2.to_excel(w,sheet_name='Daily')
D.to_csv(os.path.join(OUT,'synthetic_daily.csv'))
try:
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    fig,ax=plt.subplots(2,2,figsize=(14,9))
    def lvl(s): s=s.dropna(); return s/s.iloc[0]
    j=D[['SYN_TA125x3_band','SYN_TA125x3_dailyreset_sens','REAL_Ayalon_sell']].loc['2012-12-30':].dropna()
    for c,l,st in [('SYN_TA125x3_band','SYN band model','-'),('SYN_TA125x3_dailyreset_sens','SYN daily-reset model','--'),('REAL_Ayalon_sell','REAL Ayalon 5117684','-')]: ax[0,0].plot(lvl(j[c]),st,label=l,lw=1.6 if c.startswith('REAL') else 1)
    ax[0,0].set_yscale('log'); ax[0,0].set_title('TA-125 x3: real vs synthetic, from 2012-12-30 (log, ILS)'); ax[0,0].legend()
    j=D[['SYN_Nasdaq100x3_monthly_ILS','SYN_Nasdaq100x3_dailyreset_ILS_sens','REAL_MTF_close']].loc['2022-07-05':].dropna()
    for c,l,st in [('SYN_Nasdaq100x3_monthly_ILS','SYN monthly-reset model','-'),('SYN_Nasdaq100x3_dailyreset_ILS_sens','SYN daily-reset model','--'),('REAL_MTF_close','REAL MTF 1187079','-')]: ax[0,1].plot(lvl(j[c]),st,label=l,lw=1.6 if c.startswith('REAL') else 1)
    ax[0,1].set_yscale('log'); ax[0,1].set_title('Nasdaq-100 x3: real vs synthetic, from 2022-07-05 (log, ILS)'); ax[0,1].legend()
    for c,l in [('SYN_TA125x3_band','TA-125 x3 SYN'),('SYN_Nasdaq100x3_monthly_ILS','Nasdaq x3 SYN (no emergency reset)')]: ax[1,0].plot(D[c],label=l)
    ax[1,0].set_yscale('log'); ax[1,0].set_title('Full synthetic range 2003-12 to 2026-10 (RESEARCH ONLY)'); ax[1,0].legend()
    ax[1,1].axis('off'); ax[1,1].text(0,1,"ASSUMPTIONS (scenario, not the funds' rules)\n- Ayalon: 3x TA-125 TR, reset to 300% when exposure leaves 280-320%\n  (band official; reset target/timing assumed). Fees 1.89%/yr.\n- MTF: 3x Nasdaq NTR + 1x USD/ILS, reset at month end, fees 1.38%/yr.\n  Emergency reset UNKNOWN, none modelled (Oct-2008: -64% in a month).\n- NTR before 2011-10-10 derived by Nasdaq rule, not official.\n- Financing: Makam TR / US 13wk bill, no swap spread.\n- Nothing tuned. Real funds: Ayalon from 2012-12, MTF from 2022-07.\nMTF daily match is weak (corr {:.2f}); Ayalon daily corr {:.2f}.".format(daily_corr_mtf,daily_corr_ay),va='top',fontsize=10,family='monospace')
    plt.tight_layout(); plt.savefig(os.path.join(OUT,'validation_chart.png'),dpi=110)
except ImportError: print('matplotlib missing: chart skipped')
pd.set_option('display.width',250); print(ST.round(4).to_string()); print(V.round(3).to_string()); print(SE.round(4).to_string()); print(V2.round(3).to_string()); print('daily corr ayalon,mtf',daily_corr_ay,daily_corr_mtf)
