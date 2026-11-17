"""Final-chain metrics for the historical regression energy policy.

Unlike analyze_results.py this does not assume an output budget, signed-output
projection, or event locks, and it does not read diagnostic.bin. Run only after
the exact native source and matching replay outputs have been frozen.
"""
from pathlib import Path
import argparse, json
import numpy as np
import pandas as pd
from analyze_results import ROOT, ms, local, read_result, stats, summarize, dump

POLICY='historical_regression_energy'

def expected_w3(ts,raw):
    """Independent original causal W3, plus final wrapper's global >3min reset."""
    output=np.full_like(raw,np.nan);m=raw.shape[1]
    b0=np.zeros(m);b1=np.zeros(m);b2=np.zeros(m);count=np.zeros(m,dtype=np.uint8)
    for k,time in enumerate(ts):
        if k and time-ts[k-1]>180000:
            count[:]=0;b0[:]=0;b1[:]=0;b2[:]=0
        value=raw[k];finite=np.isfinite(value)
        count[~finite]=0
        first=finite&(count==0);second=finite&(count==1);third=finite&(count==2);full=finite&(count==3)
        output[k,first]=value[first];b0[first]=value[first]
        output[k,second]=.5*(b0[second]+value[second]);b1[second]=value[second]
        b2[third]=value[third]
        b0[full]=b1[full];b1[full]=b2[full];b2[full]=value[full]
        mature=third|full
        output[k,mature]=np.maximum(np.minimum(b0[mature],b1[mature]),np.minimum(np.maximum(b0[mature],b1[mature]),b2[mature]))
        count[first]=1;count[second]=2;count[third]=3
    return output

def analyze_device(path,args):
    line,device=path.parent.parent.name,path.parent.name
    data=np.load(path,allow_pickle=False)
    ts,names,rawx,rawy=[data[k] for k in ['timestamp','names','x','y']]
    basepath=ROOT/'results/baseline'/line/device/'output.bin'
    newpath=ROOT/'results/astra'/line/device/'output.bin'
    old,new=read_result(basepath),read_result(newpath)
    status=pd.read_csv(newpath.parent/'status.csv')
    for vector in [old['timestamp'],new['timestamp'],status.timestamp.to_numpy()]:
        assert np.array_equal(ts,vector),(line,device,'unaligned timestamps')
    assert rawx.shape==old['x'].shape==new['x'].shape
    finite=np.isfinite(rawx);corr=rawx-new['x'];yf=np.isfinite(old['y'])&np.isfinite(new['y'])
    outside=np.broadcast_to((status.gate_x.to_numpy()<=0)[:,None],finite.shape)
    w3=expected_w3(ts,rawx)
    core_unavailable=(status.modes_x.to_numpy()==0)|(status.state_x.to_numpy()=='DEGRADED_FRAME')
    checks,examples={},{}
    def check(key,bad):
        bad=np.asarray(bad);checks[key]=int(bad.sum())
        if bad.any():
            entries=[]
            for k,j in np.argwhere(bad)[:8]:
                entries.append(dict(time=local(ts[k]),marker=str(names[j]),
                    raw=float(rawx[k,j]) if finite[k,j] else None,
                    astra=float(new['x'][k,j]) if np.isfinite(new['x'][k,j]) else None,
                    state=str(status.state_x.iloc[k]),gate=float(status.gate_x.iloc[k])))
            examples[key]=entries
    check('x_finite_mask_mismatch',finite!=np.isfinite(new['x']))
    check('output_nonfinite_from_valid_raw',finite&~np.isfinite(new['x']))
    check('y_finite_mask_mismatch',np.isfinite(old['y'])!=np.isfinite(new['y']))
    check('y_value_mismatch',yf&(old['y']!=new['y']))
    check('y_finite_bits_mismatch',yf&(old['y'].view('<u8')!=new['y'].view('<u8')))
    check('outside_window_expected_w3_mismatch',finite&outside&(new['x']!=w3))
    checks['nonincreasing_input_timestamps']=int(np.count_nonzero(np.diff(ts)<=0))
    checks['nonincreasing_output_timestamps']=int(np.count_nonzero(np.diff(new['timestamp'])<=0))
    checks['unexpected_rejected_frame_state_on_valid_replay']=int(status.state_x.isin(['BAD_INPUT','SKIP_BAD_TS','DISABLED']).sum())
    rows=[]
    for day in range(2,16):
        night=f'2026-11-{day:02d}'
        split='warmup' if day<=4 else ('diagnostic' if day<=11 else 'holdout')
        if args.split and split!=args.split:continue
        for window,start,stop,expected in [
            ('night_22_08',ms(night+' 22:00'),ms(f'2026-11-{day+1:02d} 08:00'),600),
            ('active_2320_07',ms(night+' 23:20'),ms(f'2026-11-{day+1:02d} 07:00'),460)]:
            ix=np.flatnonzero((ts>=start)&(ts<stop))
            for j,name in enumerate(names):
                good=finite[ix,j]&np.isfinite(old['x'][ix,j])&np.isfinite(new['x'][ix,j])
                ti=ix[good]
                raw,v54,astra=rawx[ti,j],old['x'][ti,j],new['x'][ti,j]
                row=dict(policy=POLICY,line=line,device=device,marker=str(name),night=night,split=split,window=window,
                    recorded_frames=len(ix),valid_raw_frames=int(finite[ix,j].sum()),common_frames=len(ti),
                    expected_frames=expected,coverage_ratio=len(ti)/expected,eligible=len(ti)>=args.coverage*expected,
                    target_range_units=1.0 if 'J' in str(name).upper() else 2.0,
                    target_class='J_or_XJ' if 'J' in str(name).upper() else 'ordinary')
                for label,values in [('raw',raw),('v54',v54),('astra',astra)]:
                    for key,value in stats(values).items():row[f'{label}_{key}_units']=value
                spread=row['raw_p95p5_units']
                row['category']='missing' if spread is None else ('quiet' if spread<=0.5 else ('moderate' if spread<=2 else 'large'))
                if len(ti):
                    for label in ['raw','v54','astra']:
                        row[label+'_range_target_pass']=row[label+'_p2p_units']<=row['target_range_units']+1e-10
                    row['v54_broke_raw_range_target']=row['raw_range_target_pass'] and not row['v54_range_target_pass']
                    row['astra_recovered_v54_range_failure']=row['v54_broke_raw_range_target'] and row['astra_range_target_pass']
                    row['astra_broke_raw_range_target']=row['raw_range_target_pass'] and not row['astra_range_target_pass']
                    row['astra_lost_v54_repair_target']=(not row['raw_range_target_pass']) and row['v54_range_target_pass'] and not row['astra_range_target_pass']
                    row.update(v54_max_abs_correction_units=float(np.max(np.abs(raw-v54))),
                        astra_max_abs_correction_units=float(np.max(np.abs(raw-astra))),
                        astra_corrected_fraction=float(np.mean(np.abs(raw-astra)>1e-12)),
                        astra_lock_fraction=0.0, # Not enabled by this policy; not an inferred observation.
                        astra_no_reference_fraction=None, # Status does not expose pointwise reference eligibility.
                        astra_core_unavailable_fraction=float(np.mean(core_unavailable[ti])),
                        astra_p95p5_change_units=row['astra_p95p5_units']-spread,
                        v54_p95p5_change_units=row['v54_p95p5_units']-spread)
                    row['astra_material_worsening']=row['astra_p95p5_change_units']>max(0.05,0.10*spread)
                    row['v54_material_worsening']=row['v54_p95p5_change_units']>max(0.05,0.10*spread)
                    contiguous=np.diff(ts[ti])<=90000
                    for label,values in [('raw',raw),('v54',v54),('astra',astra)]:
                        delta=np.abs(np.diff(values))[contiguous]
                        row[label+'_max_contiguous_step_units']=float(delta.max()) if len(delta) else None
                    passive=status.gate_x.to_numpy()[ti]<=0
                    mandatory=w3[ti,j][passive]
                    row['zero_gate_w3_range_units']=float(np.ptp(mandatory)) if len(mandatory)>1 else 0.0
                    row['target_impossible_given_zero_gate_w3']=row['zero_gate_w3_range_units']>row['target_range_units']+1e-10
                rows.append(row)
    dc=np.abs(corr[finite])
    summary=dict(policy=POLICY,line=line,device=device,frames=len(ts),markers=len(names),valid_x_cells=int(finite.sum()),
        max_abs_correction_units=float(np.max(dc)) if len(dc) else None,checks=checks,violation_examples=examples,
        event_locks_enabled=False,output_correction_cap_enabled=False,output_direction_projection_enabled=False,
        state_counts_x={str(k):int(v) for k,v in status.state_x.value_counts().items()},
        outside_window_raw_difference_cells=int(np.count_nonzero(finite&outside&(new['x']!=rawx))),
        invalid_timestamp_api_test='Not exercised by chronological replay; inspect separate native API tests')
    print('HISTORY_METRICS',line,device,'rows',len(rows),'violations',sum(checks.values()),flush=True)
    return rows,summary

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--line');parser.add_argument('--device')
    parser.add_argument('--split',choices=['warmup','diagnostic','holdout'])
    parser.add_argument('--coverage',type=float,default=0.8)
    parser.add_argument('--output-prefix',default='metrics')
    args=parser.parse_args()
    if args.output_prefix!=Path(args.output_prefix).name:raise ValueError('output-prefix must be a simple filename prefix')
    rows=[];devices=[]
    for path in sorted((ROOT/'data').glob('*/*/input.npz')):
        if args.line and path.parent.parent.name!=args.line:continue
        if args.device and path.parent.name!=args.device:continue
        rr,ss=analyze_device(path,args);rows+=rr;devices.append(ss)
    if not devices:raise RuntimeError('No devices analyzed')
    df=pd.DataFrame(rows)
    suffix=('__'+args.line if args.line else '')+('__'+args.device if args.device else '')+('__'+args.split if args.split else '')
    dest=ROOT/'reports';prefix=args.output_prefix
    def csv(kind,frame):frame.to_csv(dest/(prefix+'_'+kind+suffix+'.csv'),index=False,encoding='utf-8-sig')
    csv('point_nights',df);csv('incomplete',df[~df.eligible])
    csv('regressions',df[df.eligible&(df.astra_material_worsening==True)].sort_values('astra_p95p5_change_units',ascending=False))
    csv('range_failures',df[df.eligible&(df.astra_range_target_pass==False)].sort_values('astra_p2p_units',ascending=False))
    csv('lost_v54_repairs',df[df.eligible&(df.astra_lost_v54_repair_target==True)].sort_values('astra_p2p_units',ascending=False))
    csv('outside_window_w3_range_failures',df[df.eligible&(df.target_impossible_given_zero_gate_w3==True)])
    groups=summarize(df);csv('groups',pd.DataFrame(groups))
    keys=sorted(set(k for dev in devices for k in dev['checks']))
    totals={key:sum(dev['checks'].get(key,0) for dev in devices) for key in keys}
    summary=dict(policy=POLICY,input_unit='pixel',unit_source='Explicit user confirmation in this chat, 2026-11-16; raw x/y are pixel',
        parameters=vars(args),definitions={
            'windows':'Asia/Shanghai; 22:00 <= t < next08:00 and 23:20 <= t < next07:00',
            'split':'11/02-04 warmup; 11/05-11 diagnostic; 11/12-15 later-period review (internal label holdout), not strict blind validation because one device v1 summary was previously viewed',
            'category':'raw P95-P5 <=0.5 px quiet; >0.5 and <=2 moderate; >2 large, separately in each window',
            'eligibility':'common finite raw/V54/Astra count >=80% nominal 600/460 minute frames, no interpolation',
            'material_worsening':'Astra P95-P5 minus raw > max(0.05 px, 10% of raw spread)',
            'range_target':'Full max-min <=2 px ordinary, <=1 px for any marker containing J (J/XJ); target is not correction amplitude',
            'policy_scope':'Historical regression energy constraint; no total-output cap, no signed-output projection, no persistent event locks',
            'lock_column':'astra_lock_fraction is zero because locks are disabled under this policy',
            'unknown_reference':'Pointwise reference eligibility is not exposed by status.csv; astra_no_reference_fraction is blank',
            'numerical_checks':'Finite masks, Y exact equality/finite bit equality, zero-gate original causal W3 (second valid frame mean, third+ median, invalid point clears its buffer, global gap>3min clears all), aligned monotonic replay timestamps and rejected-state absence',
            'zero_gate_behavior':'The inherited all-time W3 remains enabled; zero gate does not mean raw X passthrough. Differences from raw are counted descriptively and are not violations.',
            'zero_gate_w3_bound':'zero_gate_w3_range_units is the range of actual mandated W3 outputs at gate0, not the earlier raw-bypass prototype bound',
            'not_claimed':'No physical truth guarantee, no future nightly target guarantee, no 2 px correction cap or step retention guarantee; invalid timestamp API paths require native tests',
            'historical_bound':'Pairwise historical moment matrices and the full-basis predictor are a surrogate; dynamic SolveV valid sets, cbar, W3, S2 and S1 require final-chain replay'},
        devices=devices,total_checks=totals,all_numerical_invariants_pass=not any(totals.values()),groups=groups,
        total_point_window_nights=len(df),eligible_point_window_nights=int(df.eligible.sum()),
        material_regressions=int((df.eligible&(df.astra_material_worsening==True)).sum()))
    dump(dest/(prefix+'_summary'+suffix+'.json'),summary)
    print(json.dumps({k:summary[k] for k in ['policy','all_numerical_invariants_pass','total_point_window_nights','eligible_point_window_nights','material_regressions']}),flush=True)

if __name__=='__main__':main()
