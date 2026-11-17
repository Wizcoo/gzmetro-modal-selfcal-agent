"""Measure full-gate entry/exit discontinuities at original acquisition times."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from latency_analyze import ROOT,ROUND,read_result,clean

def run():
    rows=[]
    variants=['current','no_w3','no_s1','no_s2','no_temporal','modal_only']
    for source in sorted((ROOT/'data').glob('*/*/input.npz')):
        line,device=source.parent.parent.name,source.parent.name
        raw=np.load(source,allow_pickle=False);ts=raw['timestamp'];x=raw['x'];names=raw['names']
        base=ROUND/'results/current'/line/device
        status=pd.read_csv(base/'status.csv');assert np.array_equal(status.timestamp,ts)
        gate=status.gate_x.to_numpy();local=pd.to_datetime(ts,unit='ms',utc=True).tz_convert('Asia/Shanghai')
        night_dates=(local-pd.Timedelta(hours=12)).strftime('%Y-%m-%d')
        outputs={v:read_result(ROUND/'results'/v/line/device/'output.bin')['x'] for v in variants}
        for event,mask in [('enter_full_gate',(gate[1:]>=1)&(gate[:-1]<1)),('exit_full_gate',(gate[1:]<1)&(gate[:-1]>=1))]:
            indices=np.flatnonzero(mask)+1
            for i in indices:
                if not ('2026-11-06'<=night_dates[i]<='2026-11-15'):continue
                if ts[i]-ts[i-1]>90000:continue
                for j,name in enumerate(names):
                    if not (np.isfinite(x[i,j]) and np.isfinite(x[i-1,j])):continue
                    raw_step=float(x[i,j]-x[i-1,j])
                    for v,out in outputs.items():
                        if not (np.isfinite(out[i,j]) and np.isfinite(out[i-1,j])):continue
                        out_step=float(out[i,j]-out[i-1,j])
                        row=dict(variant=v,line=line,device=device,marker=str(name),night=night_dates[i],event=event,time=str(local[i]),
                                 previous_gate=float(gate[i-1]),gate=float(gate[i]),raw_step_px=raw_step,output_step_px=out_step,
                                 output_minus_raw_step_px=out_step-raw_step,amplified_step=abs(out_step)>abs(raw_step)+.1)
                        if v=='current':
                            for alt in ['no_s1','no_s2']:
                                row['current_minus_'+alt+'_before_px']=float(out[i-1,j]-outputs[alt][i-1,j])
                                row['current_minus_'+alt+'_after_px']=float(out[i,j]-outputs[alt][i,j])
                        rows.append(row)
    frame=pd.DataFrame(rows);frame.to_csv(ROUND/'reports/latency_boundary_point_events.csv',index=False,encoding='utf-8-sig')
    summaries=[]
    for (v,event),data in frame.groupby(['variant','event']):
        row=dict(variant=v,event=event,events=len(data),median_abs_raw_step_px=data.raw_step_px.abs().median(),
                 median_abs_output_step_px=data.output_step_px.abs().median(),p95_abs_output_step_px=data.output_step_px.abs().quantile(.95),
                 p99_abs_output_step_px=data.output_step_px.abs().quantile(.99),maximum_abs_output_step_px=data.output_step_px.abs().max(),
                 output_step_ge1_count=int((data.output_step_px.abs()>=1).sum()),
                 output_step_ge1_raw_step_lt02_count=int(((data.output_step_px.abs()>=1)&(data.raw_step_px.abs()<.2)).sum()),
                 amplified_step_gt_raw_plus01_count=int(data.amplified_step.sum()))
        if v=='current':
            for alt in ['no_s1','no_s2']:
                row['current_minus_'+alt+'_before_abs_p95_px']=data['current_minus_'+alt+'_before_px'].abs().quantile(.95)
                row['current_minus_'+alt+'_after_abs_max_px']=data['current_minus_'+alt+'_after_px'].abs().max()
        summaries.append(clean(row))
    summary=dict(note='Per marker per gate transition; not independent physical events. Output-minus-raw step conflates gating with denoising. Current vs no_s1/no_s2 have identical W3/core configuration; their full-gate differences vanish at exit, directly identifying switched-off postprocessing.',
                 rows=summaries)
    (ROUND/'reports/latency_boundary_summary.json').write_text(json.dumps(clean(summary),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':run()
