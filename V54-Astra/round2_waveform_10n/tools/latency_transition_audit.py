"""Fixed 07/08 transition windows and actual per-profile full-gate exits."""
from datetime import datetime,timedelta
import json
import numpy as np
import pandas as pd
from latency_analyze import ROOT,ROUND,TZ,read_result,clean

def run():
    variants=['current','no_w3','current_fade07','current_fade08','current_end08','no_w3_end08','no_w3_tau05_end08']
    rows=[];exits=[];checks=dict(fade07_active_finite_value_mismatches=0,fade07_active_finite_mask_mismatches=0)
    for source in sorted((ROOT/'data').glob('*/*/input.npz')):
        line,device=source.parent.parent.name,source.parent.name
        raw=np.load(source,allow_pickle=False);ts=raw['timestamp'];x=raw['x'];names=raw['names']
        current=read_result(ROUND/'results/current'/line/device/'output.bin')['x']
        for variant in variants:
            base=ROUND/'results'/variant/line/device;out=read_result(base/'output.bin')['x'];status=pd.read_csv(base/'status.csv')
            assert np.array_equal(status.timestamp,ts);gate=status.gate_x.to_numpy()
            for day in range(6,16):
                night=f'2026-11-{day:02d}';morning=datetime.fromisoformat(night).replace(tzinfo=TZ)+timedelta(days=1)
                if variant=='current_fade07':
                    start=morning-timedelta(minutes=40);stop=morning+timedelta(hours=7)
                    active=(ts>=int(start.timestamp()*1000))&(ts<int(stop.timestamp()*1000))
                    finite=np.isfinite(current[active])&np.isfinite(out[active])
                    checks['fade07_active_finite_value_mismatches']+=int(np.count_nonzero(current[active][finite]!=out[active][finite]))
                    checks['fade07_active_finite_mask_mismatches']+=int(np.count_nonzero(np.isfinite(current[active])!=np.isfinite(out[active])))
                for label,anchor in [('boundary07',7),('boundary08',8)]:
                    start=morning+timedelta(hours=anchor,minutes=-10);stop=morning+timedelta(hours=anchor,minutes=30)
                    mask=(ts[1:]>=int(start.timestamp()*1000))&(ts[1:]<int(stop.timestamp()*1000))&(np.diff(ts)<=90000)
                    indices=np.flatnonzero(mask)+1
                    for j,name in enumerate(names):
                        valid=np.isfinite(x[indices,j])&np.isfinite(x[indices-1,j])&np.isfinite(out[indices,j])&np.isfinite(out[indices-1,j]);idx=indices[valid]
                        row=dict(variant=variant,line=line,device=device,marker=str(name),night=night,window=label,
                                 available_step_pairs=len(idx),expected_step_pairs=40,eligible=len(idx)>=32)
                        if len(idx):
                            dx=x[idx,j]-x[idx-1,j];dy=out[idx,j]-out[idx-1,j];worst=int(np.argmax(np.abs(dy)))
                            row.update(max_abs_raw_step_px=float(np.max(np.abs(dx))),max_abs_output_step_px=float(np.max(np.abs(dy))),
                                       max_abs_output_minus_raw_step_px=float(np.max(np.abs(dy-dx))),
                                       output_step_ge1_count=int(np.count_nonzero(np.abs(dy)>=1)),
                                       output_step_ge1_raw_lt02_count=int(np.count_nonzero((np.abs(dy)>=1)&(np.abs(dx)<.2))),
                                       worst_time=datetime.fromtimestamp(int(ts[idx[worst]])/1000,TZ).isoformat(),
                                       worst_raw_step_px=float(dx[worst]),worst_output_step_px=float(dy[worst]))
                        rows.append(row)
                transition=np.flatnonzero((gate[:-1]>=1)&(gate[1:]<1)&(np.diff(ts)<=90000))+1
                for i in transition:
                    when=datetime.fromtimestamp(int(ts[i])/1000,TZ)
                    if not (morning+timedelta(hours=6)<=when<morning+timedelta(hours=9)):continue
                    for j,name in enumerate(names):
                        if not all(np.isfinite(z) for z in [x[i,j],x[i-1,j],out[i,j],out[i-1,j]]):continue
                        exits.append(dict(variant=variant,line=line,device=device,marker=str(name),night=night,time=when.isoformat(),
                                          gate_before=float(gate[i-1]),gate_after=float(gate[i]),raw_step_px=float(x[i,j]-x[i-1,j]),output_step_px=float(out[i,j]-out[i-1,j])))
    reports=ROUND/'reports';frame=pd.DataFrame(rows);frame.to_csv(reports/'latency_transition_point_nights.csv',index=False,encoding='utf-8-sig')
    exitframe=pd.DataFrame(exits);exitframe.to_csv(reports/'latency_transition_exit_events.csv',index=False,encoding='utf-8-sig')
    summary=[]
    for (variant,window),allrows in frame.groupby(['variant','window']):
        data=allrows[allrows.eligible]
        summary.append(clean(dict(variant=variant,window=window,nominal_point_nights=len(allrows),eligible_point_nights=len(data),
             insufficient_point_nights=int((~allrows.eligible).sum()),
             pointnight_max_step_median_px=data.max_abs_output_step_px.median(),pointnight_max_step_p95_px=data.max_abs_output_step_px.quantile(.95),
             maximum_step_px=data.max_abs_output_step_px.max(),pointnights_any_step_ge1=int((data.output_step_ge1_count>0).sum()),
             total_steps_ge1=int(data.output_step_ge1_count.sum()),total_steps_ge1_raw_lt02=int(data.output_step_ge1_raw_lt02_count.sum()))))
    exit_summary=[]
    for variant,data in exitframe.groupby('variant'):
        exit_summary.append(clean(dict(variant=variant,pointnight_exits=len(data),median_abs_output_step_px=data.output_step_px.abs().median(),
             p95_abs_output_step_px=data.output_step_px.abs().quantile(.95),maximum_abs_output_step_px=data.output_step_px.abs().max(),
             steps_ge1=int((data.output_step_px.abs()>=1).sum()),steps_ge1_raw_lt02=int(((data.output_step_px.abs()>=1)&(data.raw_step_px.abs()<.2)).sum()))))
    result=dict(checks=checks,windows='06:50–07:30 and 07:50–08:30, original samples; >=32/40 valid 1-minute transitions for window eligibility.',
                missing='Left 11/06 night absent. Entire dataset ends 11/16 08:00; final night 08 exit/08:20 tail cannot be evaluated. No silent substitution.',
                pointnight_windows=summary,actual_gate_exit=exit_summary)
    (reports/'latency_transition_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    pd.DataFrame(summary).to_csv(reports/'latency_transition_summary.csv',index=False,encoding='utf-8-sig')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':run()
