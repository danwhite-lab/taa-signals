import io,numpy as np,pandas as pd,random
def rd(p): return pd.read_csv(io.StringIO(''.join(l for l in open(p) if not l.startswith('#'))),index_col=0,parse_dates=True)
d=rd('out5/arvol_synthetic_daily.txt'); m=rd('out5/arvol_synthetic_monthly.txt')
C=lambda s: pd.read_csv(f'data_cache/{s}.csv',index_col=0,parse_dates=True)
gs=C('GSPC'); cal=gs.index[gs.index>='1985-10-01']
nd=C('NDX'); nc=nd.close.reindex(cal).ffill(); no=nd.open.reindex(cal)
rf=(C('IRX').close/100).reindex(cal).ffill()/252
sp=C('SP500TR').close.reindex(cal); r1=sp.pct_change(); r0=gs.close.reindex(cal).pct_change()
cs=(1+r1.where(sp.notna().cumsum()>1,r0).fillna(0)-0.0007/252).cumprod()
hy=C('HYG').adj.reindex(cal); lq=C('LQD').adj.reindex(cal)   # v5: adjusted prices
print('== 1 consistency'); print('rows',len(d),'dupes',d.index.duplicated().sum(),'missing',len(set(cal[cal>=d.index[0]])-set(d.index)),'nav rel err',((100*(1+d.sleeve_return).cumprod()-d.nav).abs()/d.nav).max())
Lm={'DEF(cash:synthetic T-bill)':0,'QLD':2,'TQQQ':3}; mx=0;nanc=0
for i,(t,r) in enumerate(d.iterrows()):
    if i==0: continue
    pc=nc.shift(1)[t]; k=rf[t]; Lo,Ln=Lm[r.position],Lm[r.position_end_of_day]
    car=lambda L_: k if L_==0 else -((L_-1)*k+0.0095/252)
    if r.exec=='NEXT_OPEN_TRADE_TODAY': e=(1+Lo*(no[t]/pc-1))*(1+Ln*(nc[t]/no[t]-1))-1+car(Ln)
    else: e=Lo*(nc[t]/pc-1)+car(Lo)
    if np.isnan(e): nanc+=1
    else: mx=max(mx,abs(e-r.sleeve_return))
print('independent return recompute max diff',mx,'nan rows',nanc)
print('exec',d.exec.value_counts().to_dict(),'open before 2001:',d[d.index<'2001-01-02'].exec.str.startswith('NEXT_OPEN').sum())
print('DEF->TQQQ jumps in file (position -> position_end):',((d.position.str.startswith('DEF'))&(d.position_end_of_day=='TQQQ')).sum())
pb=d.position; pe=d.position_end_of_day; print('held pos continuity (pos_end[d-1]==pos[d]):',(pe.shift(1).iloc[1:]==pb.iloc[1:]).all())
print('flags',d.synthetic_flag.value_counts().to_dict(),'credit ON from',d[d.credit_gate=='ON'].index.min().date())
me=d.groupby([d.index.year,d.index.month]).tail(1); print('== 5 monthly: dates',(m.index==me.index).all(),'nav',np.allclose(m.nav,me.nav),'pos',(m.position.values==me.position.values).all(),'ret diff',(m.nav.pct_change().fillna(0)-m.sleeve_return).abs().max())
print('== 2 independent state machine (fresh code)')
lr=np.log(nc/nc.shift(1)); rv=lr.rolling(15).std()*np.sqrt(252); vr=rv/rv.rolling(252).mean(); tr=cs/cs.rolling(200).mean()-1
ra=hy/lq; cr=ra/ra.shift(20)-1; lo40=nc.rolling(40).min(); lo5=nc.rolling(5).min()
st='DEF'; lk=False; n=0; S={}; ev=[]; start=d.index[0]
for t in cal[cal>=start]:
    R,V,T=rv[t],vr[t],tr[t]; c=(not np.isnan(cr[t])) and cr[t]<-.04; ordx=(R>.36)|(V>1.4)|(T<-.03)|c; dn=(nc[t]<=lo40[t]) and R>=.2; old=st
    if lk:
        n+=1
        if nc[t]>=1.03*lo5[t] or n>=20: lk=False; st='QLD'; ev.append((t,'REL',st,bool(ordx)))   # v5: release ALWAYS to QLD
    else:
        if st=='TQQQ' and (R>.18 or V>1.25 or T<-.03): st='QLD'; ev.append((t,'T->Q',(R>.18,V>1.25,T<-.03,bool(c),bool(dn))))
        elif st=='QLD':
            if ordx or dn:
                st='DEF'
                if dn and not ordx: lk=True;n=0; ev.append((t,'LOCK',bool(ordx)))
            elif R<.14 and V<.9 and T>.03: st='TQQQ'
        elif st=='DEF' and R<.25 and V<1.1 and T>-.015: st='QLD'
    assert not (old=='DEF' and st=='TQQQ')
    S[t]=st
S=pd.Series(S).reindex(cal); s1=S.shift(1)
mp={'DEF(cash:synthetic T-bill)':'DEF','QLD':'QLD','TQQQ':'TQQQ'}
x=d.iloc[1:]; cl=x.exec.str.startswith('NEXT_CLOSE'); 
print('pos_end==S[d-1] mismatches',(x.position_end_of_day.map(mp)!=s1.reindex(x.index)).sum(),' (DEF->TQQQ clamp days would show here: 0 expected)')
print('pos_before==S[d-2] mismatches',(x.position.map(mp)!=S.shift(2).reindex(x.index).fillna('DEF')).sum(),'(first rows only)')
print('lock starts',sum(e[1]=='LOCK' for e in ev),'releases',sum(e[1]=='REL' for e in ev),'releases to QLD',sum(1 for e in ev if e[1]=='REL' and e[2]=='QLD'),'releases coinciding with active ordinary exit (still go to QLD)',sum(1 for e in ev if e[1]=='REL' and e[3]))
# no extra triggers: every TQQQ->QLD had one of 3 allowed conditions
print('TQQQ->QLD events',sum(e[1]=='T->Q' for e in ev),'all satisfy allowed triggers',all(any(e[2][:3]) for e in ev if e[1]=='T->Q'),'; events where ONLY credit/Donchian were true (must be none):',sum(1 for e in ev if e[1]=='T->Q' and not any(e[2][:3])))
# state_before every LOCK was QLD/TQQQ
print('LOCK starts preceded by non-DEF:',all(S.shift(1)[e[0]] in ('QLD','TQQQ') for e in ev if e[1]=='LOCK'))
# truncation look-ahead test
random.seed(2); bad=0
for _ in range(40):
    t=random.choice(cal[400:]); k=cal.get_loc(t); a=nc.iloc[:k+1]; l2=np.log(a/a.shift(1)); r2=l2.rolling(15).std()*np.sqrt(252); v2=r2/r2.rolling(252).mean(); c2=cs.iloc[:k+1]; t2=c2/c2.rolling(200).mean()-1
    bad+=not(np.isclose(r2.iloc[-1],rv[t]) and np.isclose(v2.iloc[-1],vr[t]) and np.isclose(t2.iloc[-1],tr[t]) and np.isclose(a.rolling(40).min().iloc[-1],lo40[t]))
print('look-ahead truncation failures /40',bad)
print('== 3 real vs synthetic (reference col, held QLD/TQQQ days)')
for k,Lv in [('QLD',2),('TQQQ',3)]:
    q=d[(d.position==k)&d.real_fund_adj_return_REFERENCE_ONLY.notna()&(d.exec!='NEXT_OPEN_TRADE_TODAY')]
    e=q.sleeve_return-q.real_fund_adj_return_REFERENCE_ONLY; print(k,'hold-day n',len(q),'corr',round(np.corrcoef(q.sleeve_return,q.real_fund_adj_return_REFERENCE_ONLY)[0,1],4),'mean model-real annualized pt',round(e.mean()*252*100,2),'TE %',round(e.std()*np.sqrt(252)*100,2))
