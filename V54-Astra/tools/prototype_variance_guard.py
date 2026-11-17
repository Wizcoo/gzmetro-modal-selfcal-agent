"""Diagnostic-only 60-minute centered covariance scaling prototype.

Reads the frozen native crossnight_energy proposal, never changes source code.
No later-period candidate outputs are calculated or saved.
"""
from collections import deque
import json
import numpy as np
import pandas as pd
from analyze_results import ROOT, ms, read_result, stats

def window_guard(ts,raw,proposal,enabled):
    n,m=raw.shape;output=proposal.copy();alphas=np.ones_like(raw)
    count=np.zeros(m);sx=np.zeros(m);sc=np.zeros(m);sxx=np.zeros(m);scc=np.zeros(m);sxc=np.zeros(m)
    history=deque()
    for k,time in enumerate(ts):
        finite=np.isfinite(raw[k])&np.isfinite(proposal[k])
        x=np.where(finite,raw[k],0.0);c=np.where(finite,raw[k]-proposal[k],0.0);good=finite.astype(float)
        values=(good,x,c,x*x,c*c,x*c)
        for accum,v in zip([count,sx,sc,sxx,scc,sxc],values):accum+=v
        history.append((time,values))
        while history and history[0][0]<time-3600000:
            _,old=history.popleft()
            for accum,v in zip([count,sx,sc,sxx,scc,sxc],old):accum-=v
        denom=np.maximum(count,1)
        varx=np.maximum(0,sxx/denom-(sx/denom)**2)
        varc=np.maximum(0,scc/denom-(sc/denom)**2)
        cov=sxc/denom-sx*sc/denom**2
        vary=np.maximum(0,varx+varc-2*cov)
        alpha=np.ones(m)
        change=(count>=10)&finite&enabled[k]&(vary>varx+1e-12*np.maximum(1,varx))&(varc>1e-12)
        alpha[change]=np.clip(2*cov[change]/varc[change],0,1)
        # A constant correction has varc=0 and stays unchanged, including raw platforms.
        output[k,finite]=raw[k,finite]-alpha[finite]*c[finite]
        alphas[k]=alpha
    return output,alphas

def main():
    rows=[]
    for path in sorted((ROOT/'data').glob('*/*/input.npz')):
        d=np.load(path,allow_pickle=False);ts,names,raw=d['timestamp'],d['names'],d['x']
        line,dev=path.parent.parent.name,path.parent.name
        base=read_result(ROOT/'results/baseline'/line/dev/'output.bin')
        folder=ROOT/'experiments/crossnight_energy/results'/line/dev
        source=read_result(folder/'output.bin');status=pd.read_csv(folder/'status.csv')
        assert np.array_equal(source['timestamp'],status.timestamp.to_numpy())
        common,ri,si=np.intersect1d(ts,source['timestamp'],return_indices=True)
        assert len(common)==len(source),(line,dev,'proposal timestamp missing from original input')
        assert source['x'].shape[1]==raw.shape[1]
        ts=common;raw=raw[ri];base=base[ri];source=source[si];status=status.iloc[si]
        core=(status.gate_x.to_numpy()>0)&(status.modes_x.to_numpy()!=0)&(status.state_x.to_numpy()!='DEGRADED_FRAME')
        for day in range(5,12):
            night=f'2026-11-{day:02d}'
            a,b=ms(night+' 22:00'),ms(f'2026-11-{day+1:02d} 08:00')
            ix=np.flatnonzero((ts>=a)&(ts<b))
            if not len(ix):continue
            values,alpha=window_guard(ts[ix],raw[ix],source['x'][ix],core[ix])
            for window,start,end,expected in [('night_22_08',a,b,600),('active_2320_07',ms(night+' 23:20'),ms(f'2026-11-{day+1:02d} 07:00'),460)]:
                localidx=np.flatnonzero((ts[ix]>=start)&(ts[ix]<end))
                for j,name in enumerate(names):
                    good=np.isfinite(raw[ix[localidx],j])&np.isfinite(base['x'][ix[localidx],j])&np.isfinite(values[localidx,j])
                    kk=localidx[good]
                    if len(kk)<.8*expected:continue
                    rawv,oldv,srcv,newv=raw[ix[kk],j],base['x'][ix[kk],j],source['x'][ix[kk],j],values[kk,j]
                    ss=[stats(v) for v in [rawv,oldv,srcv,newv]];target=1.0 if 'J' in str(name).upper() else 2.0
                    passed=[s['p2p']<=target+1e-10 for s in ss]
                    row=dict(line=line,device=dev,marker=str(name),night=night,window=window,target_px=target,frames=len(kk),
                        raw_target_pass=passed[0],v54_target_pass=passed[1],crossnight_target_pass=passed[2],prototype_target_pass=passed[3],
                        broke_raw_target=passed[0] and not passed[3],lost_v54_repair=not passed[0] and passed[1] and not passed[3],
                        lost_crossnight_target=passed[2] and not passed[3],
                        material_spread_worsening=ss[3]['p95p5']-ss[0]['p95p5']>max(.05,.1*ss[0]['p95p5']),
                        crossnight_material_worsening=ss[2]['p95p5']-ss[0]['p95p5']>max(.05,.1*ss[0]['p95p5']),
                        raw_quiet=ss[0]['p95p5']<=.5,scaled_fraction=float(np.mean(alpha[kk,j]<1-1e-12)),min_alpha=float(np.min(alpha[kk,j])))
                    for label,s in zip(['raw','v54','crossnight','prototype'],ss):
                        row[label+'_spread_px']=s['p95p5'];row[label+'_range_px']=s['p2p']
                    rows.append(row)
        print('VARIANCE_PROTOTYPE',line,dev,flush=True)
    df=pd.DataFrame(rows);df.to_csv(ROOT/'reports/metrics_variance_prototype_diagnostic.csv',index=False,encoding='utf-8-sig')
    groups=[]
    keys=['raw_target_pass','v54_target_pass','crossnight_target_pass','prototype_target_pass','broke_raw_target','lost_v54_repair','lost_crossnight_target','material_spread_worsening','crossnight_material_worsening']
    for window,g in df.groupby('window'):
        groups.append(dict(window=window,point_nights=len(g),**{k:int(g[k].sum()) for k in keys},
            quiet_point_nights=int(g.raw_quiet.sum()),quiet_material_worsening=int(g.loc[g.raw_quiet,'material_spread_worsening'].sum()),
            point_nights_scaled=int((g.scaled_fraction>0).sum()),max_scaled_fraction=float(g.scaled_fraction.max())))
    specific=df[(df.line=='right')&(df.device=='780639298317')&(df.marker=='YD1102')&df.night.isin(['2026-11-05','2026-11-06'])]
    report=dict(definition='60-minute causal raw/correction centered covariance; alpha=clip(2cov/varcorr,0,1) only if proposal variance exceeds raw and at least10 valid pairs; constant correction retains alpha1; gate>0 and core-ready frames only; diagnostic period11/05-11 only',
        summary=groups,known_remaining_overcorrection=json.loads(specific.to_json(orient='records')),synthetic=synthetic())
    (ROOT/'reports/metrics_variance_prototype_diagnostic.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    print(json.dumps(groups,indent=2),flush=True)

def synthetic():
    t=np.arange(180,dtype=np.int64)*60000+1793872800000;raw=np.ones((180,1));enabled=np.ones(180,dtype=bool)
    results=[]
    for name,c in [('constant_correction',np.full((180,1),.8)),
                   ('varying_then_constant_correction',np.r_[.8+.1*np.sin(np.arange(30)),np.full(150,.8)].reshape(-1,1)),
                   ('constant_then_varying_correction',np.r_[np.full(60,.8),.8+.1*np.sin(np.arange(120))].reshape(-1,1))]:
        proposal=raw-c;output,alpha=window_guard(t,raw,proposal,enabled)
        results.append(dict(case=name,raw_range_px=0,proposal_range_px=float(np.ptp(proposal)),
            output_range_px=float(np.ptp(output)),output_range_after_warmup_px=float(np.ptp(output[10:])),
            max_output_jump_px=float(np.max(np.abs(np.diff(output[:,0])))),min_alpha=float(alpha.min()),max_alpha=float(alpha.max()),
            platform_preserved=bool(np.ptp(output[10:])<1e-10)))
    return results

if __name__=='__main__':main()
