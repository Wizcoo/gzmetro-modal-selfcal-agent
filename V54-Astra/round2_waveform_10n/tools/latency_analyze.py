"""Independent ten-night waveform audit; original timestamps, no output shifting.

Example: python latency_analyze.py --variant current
Results are diagnostic raw-waveform agreement, not physical-accuracy acceptance.
"""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import argparse, json, struct, time
import numpy as np
import pandas as pd
from latency_metrics import compute_metrics, self_test

ROUND=Path(__file__).resolve().parents[1]
ROOT=ROUND.parent
TZ=timezone(timedelta(hours=8))

def read_result(path):
    with path.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    dtype=np.dtype([('timestamp','<i8'),('x','<f8',(m,)),('y','<f8',(m,))])
    assert path.stat().st_size==8+n*dtype.itemsize,str(path)
    return np.memmap(path,mode='r',offset=8,dtype=dtype,shape=(n,))

def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,(np.integer,)):return int(value)
    if isinstance(value,(np.bool_,)):return bool(value)
    if isinstance(value,(float,np.floating)):return float(value) if np.isfinite(value) else None
    return value

def summarize(frame):
    rows=[]
    for (variant,window),allrows in frame.groupby(['variant','window']):
        eligible=allrows[allrows.eligible.astype(bool)]
        lag=eligible[eligible.lag_interpretable.fillna(False).astype(bool)]
        resolved=eligible[eligible.lag_resolved.fillna(False).astype(bool)]
        event=eligible[eligible.event_timing_interpretable.fillna(False).astype(bool)]
        row=dict(variant=variant,window=window,nominal_point_nights=len(allrows),eligible_point_nights=len(eligible),
                 absent_point_nights=int((allrows.observed_frames==0).sum()),low_coverage_point_nights=int((~allrows.eligible).sum()),
                 lag_interpretable_count=len(lag),lag_uninterpretable_count=len(eligible)-len(lag),lag_resolved_count=len(resolved),
                 event_interpretable_count=len(event))
        for metric in ['raw_p95p5_px','output_p95p5_px','raw_p2p_px','output_p2p_px','native_corr_zero','slow_corr_zero','slow_corr_best','slope_direction_agreement','slope_output_flat_fraction']:
            row[metric+'_median']=eligible[metric].median()
        for metric in ['output_p95p5_px','output_p2p_px']:
            for target in [1,2]:row[metric+f'_le{target}_rate']=float((eligible[metric]<=target).mean())
        row['slow_corr_zero_ge08_count']=int((eligible.slow_corr_zero>=.8).sum())
        row['slow_corr_zero_ge08_rate_all_eligible']=float((eligible.slow_corr_zero>=.8).mean())
        for label,selection in [('interpretable',lag),('resolved',resolved)]:
            row[label+'_lag_median_min']=selection.slow_best_lag_min.median()
            row[label+'_lag_p05_min']=selection.slow_best_lag_min.quantile(.05)
            row[label+'_lag_p95_min']=selection.slow_best_lag_min.quantile(.95)
            row[label+'_lag_ge1_rate']=float((selection.slow_best_lag_min>=1).mean()) if len(selection) else None
            row[label+'_abs_lag_le1_rate']=float((selection.slow_best_lag_min.abs()<=1).mean()) if len(selection) else None
            row[label+'_corr_gain_median']=selection.slow_lag_gain.median()
        for metric in ['event_recall','event_precision','event_signed_median_min','event_abs_p90_min']:
            row[metric+'_median_interpretable']=event[metric].median()
        rows.append(clean(row))
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--variant',default='current');p.add_argument('--windows',default='active_2320_07,night_22_08')
    p.add_argument('--first-night',default='2026-11-06');p.add_argument('--last-night',default='2026-11-15')
    p.add_argument('--results-root',type=Path);p.add_argument('--device');a=p.parse_args()
    self_test();started=time.time();rows=[];source_paths=[]
    results=a.results_root or ROUND/'results'/a.variant
    days=[];day=datetime.fromisoformat(a.first_night).replace(tzinfo=TZ);last=datetime.fromisoformat(a.last_night).replace(tzinfo=TZ)
    while day<=last:days.append(day);day+=timedelta(days=1)
    for source in sorted((ROOT/'data').glob('*/*/input.npz')):
        line,device=source.parent.parent.name,source.parent.name
        if a.device and device!=a.device:continue
        output_path=results/line/device/'output.bin';output=read_result(output_path)
        raw=np.load(source,allow_pickle=False);ts=raw['timestamp'];x=raw['x'];names=raw['names']
        assert np.array_equal(ts,output['timestamp']);assert x.shape==output['x'].shape
        source_paths.append(dict(line=line,device=device,raw=str(source),output=str(output_path)))
        for day in days:
            night=day.strftime('%Y-%m-%d')
            windows=[('active_2320_07',day+timedelta(hours=23,minutes=20),day+timedelta(days=1,hours=7),460),
                     ('night_22_08',day+timedelta(hours=22),day+timedelta(days=1,hours=8),600)]
            for window,start,stop,expected in windows:
                if window not in a.windows.split(','):continue
                use=(ts>=int(start.timestamp()*1000))&(ts<int(stop.timestamp()*1000));st=ts[use]
                raw_window=x[use];out_window=output['x'][use]
                for j,name in enumerate(names):
                    rawj=raw_window[:,j];outj=out_window[:,j];valid=np.isfinite(rawj)&np.isfinite(outj);count=int(valid.sum())
                    row=dict(variant=a.variant,line=line,device=device,marker=str(name),night=night,window=window,
                             expected_frames=expected,observed_frames=len(st),valid_pairs=count,eligible=count>=.8*expected)
                    if count>=30:
                        row.update(compute_metrics(st,rawj,outj))
                        row['raw_p2p_px']=float(np.ptp(rawj[valid]));row['output_p2p_px']=float(np.ptp(outj[valid]))
                    rows.append(row)
        print(f'{a.variant} {line}/{device}: {len(rows)} point-night-window rows, {time.time()-started:.1f}s',flush=True)
    frame=pd.DataFrame(rows)
    for col in ['lag_interpretable','lag_resolved','event_timing_interpretable']:frame[col]=frame[col].fillna(False).astype(bool)
    reports=ROUND/'reports';reports.mkdir(exist_ok=True)
    target=reports/f'latency_{a.variant}_point_nights.csv';frame.to_csv(target,index=False,encoding='utf-8-sig')
    summary=dict(variant=a.variant,period=[a.first_night,a.last_night],time_zone='UTC+08:00',
                 scope='Ten calendar nights. Left line 2026-11-06 has no data and is not substituted; no interpolation.',
                 interpretation='Raw observations are not physical truth. Do not use lag-optimized correlation as waveform acceptance.',
                 lag_sign='Positive means output later than raw; minute-grid pairs only; duplicate-minute bins excluded.',
                 elapsed_seconds=time.time()-started,sources=source_paths,summary=summarize(frame))
    (reports/f'latency_{a.variant}_summary.json').write_text(json.dumps(clean(summary),indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    print(json.dumps(summary['summary'],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
