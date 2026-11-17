"""Development-period-only causal guard prototypes; never a deployable replay.

Uses the exact frozen v2 proposal/core availability as input. Only 11/05-11
outputs are computed or persisted; no 11/12-15 prototype outputs are made.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from analyze_results import ROOT, ms, read_result, stats, local

VARIANTS=['A_locks','B_no_locks','C_increment_locks','D_rate_010','E_rate_025']

def evaluate_device(path):
    data=np.load(path,allow_pickle=False)
    names=data['names']; ts=data['timestamp']; raw=data['x']
    line,device=path.parent.parent.name,path.parent.name
    dest=ROOT/'results/astra'/line/device/'output.bin'
    actual=read_result(dest); old=read_result(ROOT/'results/baseline'/line/device/'output.bin')
    diag=read_result(Path(str(dest)+'.diagnostic.bin'),True)
    assert np.array_equal(ts,diag['timestamp'])
    targets=np.array([1.0 if 'J' in str(n).upper() else 2.0 for n in names])
    rows=[]
    for day in range(5,12):
        night=f'2026-11-{day:02d}'
        start,stop=ms(night+' 22:00'),ms(f'2026-11-{day+1:02d} 08:00')
        ix=np.flatnonzero((ts>=start)&(ts<stop))
        if not len(ix):continue
        vals=raw[ix]; out={v:vals.copy() for v in VARIANTS}
        lo=np.full(len(names),np.inf); hi=np.full(len(names),-np.inf)
        prior_raw=np.full(len(names),np.nan); prior_c=np.zeros(len(names))
        prior_ts=np.zeros(len(names),dtype=np.int64)
        rate_states={name:np.zeros(len(names)) for name in ['D_rate_010','E_rate_025']}
        gap_bypass=np.zeros_like(vals,dtype=bool)
        for k,j in enumerate(ix):
            v=raw[j]; finite=np.isfinite(v)
            lo[finite]=np.minimum(lo[finite],v[finite]);hi[finite]=np.maximum(hi[finite],v[finite])
            span=np.maximum(0,hi-lo)
            t=np.clip((span-targets/2)/(targets/2),0,1)
            gain=0.10+(0.98-0.10)*t*t*(3-2*t)
            b=diag['reference'][j]; proposal=diag['proposal'][j]; flags=diag['flags'][j]
            d=v-b
            # gain participates in the budget; hard-coded 0.98 here would defeat quiet-night adaptation.
            budget=np.minimum(8.0,gain*np.maximum(0,np.abs(d)-0.05))
            valid=finite&np.isfinite(b)&np.isfinite(proposal)&((flags&5)==0)
            desired=np.where(valid&((v-proposal)*d>0),np.copysign(np.minimum(np.abs(v-proposal),budget),d),0)
            desired[~np.isfinite(desired)]=0
            locks=(flags&96)!=0
            ca=np.where(locks,0,desired)
            out['A_locks'][k,finite]=v[finite]-ca[finite]
            out['B_no_locks'][k,finite]=v[finite]-desired[finite]
            dr=v-prior_raw
            dr[~np.isfinite(dr)]=0
            dc=ca-prior_c
            dc=np.minimum(np.maximum(dc,np.minimum(0,dr)),np.maximum(0,dr))
            cc=prior_c+dc
            cc=np.where(d>=0,np.minimum(np.maximum(cc,0),budget),np.maximum(np.minimum(cc,0),-budget))
            cc=np.where(valid&~locks,cc,0)
            cc[~np.isfinite(cc)]=0
            out['C_increment_locks'][k,finite]=v[finite]-cc[finite]
            dt=np.where(prior_ts>0,(ts[j]-prior_ts)/60000.0,0)
            gap=(prior_ts>0)&(dt>3)
            gap_bypass[k]=gap
            for variant,rate in [('D_rate_010',0.10),('E_rate_025',0.25)]:
                pc=rate_states[variant]
                dc=desired-pc
                dc=np.minimum(np.maximum(dc,np.minimum(0,dr)),np.maximum(0,dr))
                dc=np.minimum(np.maximum(dc,-rate*dt),rate*dt)
                candidate=pc+dc
                # Same ordering as C; this projection can override the rate cap
                # when a step crosses the old reference. Synthetic cases expose it.
                candidate=np.where(d>=0,np.minimum(np.maximum(candidate,0),budget),np.maximum(np.minimum(candidate,0),-budget))
                candidate=np.where(valid&~gap,candidate,0)
                candidate[~np.isfinite(candidate)]=0
                out[variant][k,finite]=v[finite]-candidate[finite]
                rate_states[variant]=candidate
            prior_raw[finite]=v[finite];prior_c=cc
            prior_ts[finite]=ts[j]
        for window,wstart,wend,expected in [
            ('night_22_08',start,stop,600),
            ('active_2320_07',ms(night+' 23:20'),ms(f'2026-11-{day+1:02d} 07:00'),460)]:
            localidx=np.flatnonzero((ts[ix]>=wstart)&(ts[ix]<wend))
            for marker,name in enumerate(names):
                common=np.isfinite(vals[localidx,marker])&np.isfinite(old['x'][ix[localidx],marker])
                kk=localidx[common]
                if len(kk)<0.8*expected:continue
                rr=vals[kk,marker]; oo=old['x'][ix[kk],marker]
                rs,os=stats(rr),stats(oo)
                for variant in VARIANTS:
                    yy=out[variant][kk,marker]; ss=stats(yy)
                    ff=diag['flags'][ix[kk],marker]
                    mandatory=((ff&5)!=0)|~np.isfinite(diag['reference'][ix[kk],marker])
                    if variant in ['A_locks','C_increment_locks']:mandatory|=(ff&96)!=0
                    if variant in ['D_rate_010','E_rate_025']:mandatory|=gap_bypass[kk,marker]
                    mandatory_range=float(np.ptp(rr[mandatory])) if mandatory.sum()>1 else 0.0
                    witness={}
                    if mandatory.any():
                        positions=np.flatnonzero(mandatory)
                        low=positions[np.argmin(rr[positions])]; high=positions[np.argmax(rr[positions])]
                        witness=dict(mandatory_min_raw_px=float(rr[low]),mandatory_max_raw_px=float(rr[high]),
                            mandatory_min_time=local(ts[ix[kk[low]]]),mandatory_max_time=local(ts[ix[kk[high]]]),
                            mandatory_min_flags=int(ff[low]),mandatory_max_flags=int(ff[high]))
                    rawpass=rs['p2p']<=targets[marker]+1e-10
                    oldpass=os['p2p']<=targets[marker]+1e-10
                    newpass=ss['p2p']<=targets[marker]+1e-10
                    rows.append(dict(line=line,device=device,marker=str(name),night=night,window=window,variant=variant,
                        frames=len(kk),target_px=float(targets[marker]),raw_spread_px=rs['p95p5'],v54_spread_px=os['p95p5'],prototype_spread_px=ss['p95p5'],
                        raw_range_px=rs['p2p'],v54_range_px=os['p2p'],prototype_range_px=ss['p2p'],
                        raw_target_pass=rawpass,v54_target_pass=oldpass,prototype_target_pass=newpass,
                        prototype_broke_raw_target=rawpass and not newpass,
                        v54_broke_raw_target=rawpass and not oldpass,
                        recovered_v54_raw_target_failure=rawpass and not oldpass and newpass,
                        lost_v54_repair=not rawpass and oldpass and not newpass,
                        material_spread_worsening=ss['p95p5']-rs['p95p5']>max(0.05,0.10*rs['p95p5']),
                        raw_quiet=rs['p95p5']<=0.5,
                        mandatory_raw_range_px=mandatory_range,target_impossible_given_bypass=mandatory_range>targets[marker]+1e-10,
                        **witness,
                        max_abs_correction_px=float(np.max(np.abs(rr-yy))),
                        lock_fraction=float(np.mean((diag['flags'][ix[kk],marker]&96)!=0))))
    print('PROTOTYPE',line,device,'rows',len(rows),flush=True)
    return rows

def main():
    rows=[]
    for path in sorted((ROOT/'data').glob('*/*/input.npz')):
        rows.extend(evaluate_device(path))
    df=pd.DataFrame(rows)
    df.to_csv(ROOT/'reports/metrics_prototypes_diagnostic.csv',index=False,encoding='utf-8-sig')
    proof=df[df.target_impossible_given_bypass & df.variant.isin(['A_locks','B_no_locks'])]
    proof[['line','device','marker','night','window','variant','target_px','mandatory_raw_range_px',
           'mandatory_min_raw_px','mandatory_min_time','mandatory_min_flags',
           'mandatory_max_raw_px','mandatory_max_time','mandatory_max_flags']].to_csv(
               ROOT/'reports/metrics_bypass_lower_bound_evidence.csv',index=False,encoding='utf-8-sig')
    summaries=[]
    for key,g in df.groupby(['variant','window']):
        v,w=key
        summaries.append(dict(variant=v,window=w,point_nights=len(g),
            **{k:int(g[k].sum()) for k in ['raw_target_pass','v54_target_pass','prototype_target_pass','prototype_broke_raw_target','v54_broke_raw_target','recovered_v54_raw_target_failure','lost_v54_repair','material_spread_worsening','target_impossible_given_bypass']},
            quiet_point_nights=int(g.raw_quiet.sum()),quiet_material_worsening=int(g.loc[g.raw_quiet,'material_spread_worsening'].sum()),
            max_abs_correction_px=float(g.max_abs_correction_px.max()),
            raw_median_spread_px=float(g.raw_spread_px.median()),prototype_median_spread_px=float(g.prototype_spread_px.median())))
    known=df[(df.window=='active_2320_07')&(df.line=='right')&(((df.device=='780639346578')&(df.marker=='YD2603')&df.night.isin(['2026-11-05','2026-11-06','2026-11-07']))|((df.device=='780639298317')&(df.marker=='YD1102')&df.night.isin(['2026-11-05','2026-11-06'])))]
    definition={
        'period':'2026-11-05 through 2026-11-11 only; no later-period outputs computed',
        'unit':'pixel',
        'gain':'Causal raw max-min accumulated since 22:00; gain 0.10 below target/2, 0.98 above target, smoothstep between; target ordinary2/J1 px',
        'budget':'min(8, gain*max(0, abs(raw-reference)-0.05)); no 60-minute activity cap; 8 px is exploration only',
        'A_locks':'Keep original v2 event locks; same-sign proposal and no reference crossing; no additional slew',
        'B_no_locks':'Ignore original event locks; unsafe effect upper bound, not deployable',
        'C_increment_locks':'A plus delta-correction between 0 and delta-raw (ordered by sign), then project to current signed budget; core bypass/event locks/window exit override increment constraint',
        'D_rate_010':'C without permanent locks; delta-correction also limited to +/-0.10 px/min times actual dt; gap>3 min raw for that frame and correction reset; signed budget projection follows rate clipping and may override it',
        'E_rate_025':'D with 0.25 px/min, sensitivity only',
        'scope':'Python decision-layer prototypes over frozen exact C++ proposal, not final exact C++ algorithm replays or physical validation'}
    report=dict(definition=definition,summary=summaries,known_overcorrection=json.loads(known.to_json(orient='records')),synthetic_steps=synthetic_steps())
    (ROOT/'reports/metrics_prototypes_diagnostic.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(summaries,indent=2),flush=True)

def synthetic_steps():
    results=[]
    for rate in [0.10,0.25]:
        for label,before,previous_c,step in [('positive_from_zero',0,0,3),('negative_from_zero',0,0,-3),
                ('cross_reference_down',2,.8,-3),('cross_reference_up',-2,-.8,3),('positive_with_correction',2,.8,3)]:
            after=before+step; pc=previous_c; pr=before; outputs=[]
            for k in range(21):
                raw=after; budget=min(8,.98*max(0,abs(raw)-.05)); desired=np.copysign(min(abs(raw),budget),raw)
                dr=raw-pr; dc=float(np.clip(desired-pc,min(0,dr),max(0,dr))); dc=float(np.clip(dc,-rate,rate))
                candidate=pc+dc; candidate=float(np.clip(candidate,0,budget) if raw>=0 else np.clip(candidate,-budget,0))
                outputs.append(raw-candidate);pc=candidate;pr=raw
            observed=outputs[0]-(before-previous_c)
            results.append(dict(case=label,rate_px_per_min=rate,raw_step_px=step,initial_correction_px=previous_c,
                corrected_initial_step_px=observed,minimum_required_magnitude_px=abs(step)-rate,
                initial_step_retention_pass=abs(observed)>=abs(step)-rate-1e-12,
                following_20_frame_drift_px=float(np.ptp(outputs[1:])),
                following_20_frames_stable=bool(np.ptp(outputs[1:])<1e-12)))
    return results

if __name__=='__main__':main()
