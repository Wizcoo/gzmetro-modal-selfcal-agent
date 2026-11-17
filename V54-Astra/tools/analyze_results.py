"""Independent chronological replay metrics; no fitting in this script.

This checks optical output invariants, not physical truth. All report files are
written under reports/metrics*. Incomplete point-nights remain listed but are
excluded from aggregate comparisons. No missing samples are interpolated.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse, json, struct
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
FLAGS = dict(outside_window=1, no_reference=2, core_unavailable=4,
             reject_direction=8, limited_budget=16, step_lock=32,
             gap_lock=64, limited_rate=128, invalid_raw=256, deadband=512)

def ms(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)

def local(t):
    return datetime.fromtimestamp(int(t)/1000, TZ).isoformat(sep=' ')

def read_result(path, diagnostic=False):
    with path.open('rb') as f:
        m, n = struct.unpack('<II', f.read(8))
    fields = [('timestamp', '<i8')]
    fields += [(key, '<f8', (m,)) for key in (['reference', 'budget', 'proposal'] if diagnostic else ['x', 'y'])]
    if diagnostic:
        fields.append(('flags', '<u4', (m,)))
    dtype = np.dtype(fields)
    if path.stat().st_size != 8+n*dtype.itemsize:
        raise ValueError(f'Wrong binary length: {path}')
    return np.memmap(path, mode='r', offset=8, dtype=dtype, shape=(n,))

def stats(v):
    if not len(v):
        return dict(p95p5=None, p2p=None, std=None)
    q = np.quantile(v, [0.05, 0.95])
    return dict(p95p5=float(q[1]-q[0]), p2p=float(np.ptp(v)), std=float(np.std(v)))

def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

def analyze_device(path, args):
    line, device = path.parent.parent.name, path.parent.name
    basepath = ROOT/'results/baseline'/line/device/'output.bin'
    newpath = ROOT/'results/astra'/line/device/'output.bin'
    if not basepath.exists() or not newpath.exists():
        raise FileNotFoundError(f'Replay not complete: {line}/{device}')
    data = np.load(path, allow_pickle=False)
    ts, names, rawx, rawy = [data[k] for k in ['timestamp', 'names', 'x', 'y']]
    old, new = read_result(basepath), read_result(newpath)
    diag = read_result(Path(str(newpath)+'.diagnostic.bin'), True)
    status = pd.read_csv(newpath.parent/'status.csv')
    for a in [old['timestamp'], new['timestamp'], diag['timestamp'], status.timestamp.to_numpy()]:
        assert np.array_equal(a, ts), (line, device, 'time alignment differs')
    assert rawx.shape == old['x'].shape == new['x'].shape
    finite = np.isfinite(rawx)
    corr = rawx-new['x']
    reference, budget, flags = diag['reference'], diag['budget'], diag['flags']
    active = status.gate_x.to_numpy() > 0
    local_hour = ((ts+8*3600000)%86400000)/3600000.0
    night_hour = np.where(local_hour<12,local_hour+24,local_hour)
    protect_event = (night_hour>=23)&(night_hour<(31+20/60))
    reference_ok = finite & np.isfinite(reference)
    active_grid = np.broadcast_to(active[:, None], finite.shape)
    outside = np.broadcast_to(~active[:, None], finite.shape)
    tol = 1e-10
    checks, examples = {}, {}

    def check(key, bad):
        bad = np.asarray(bad)
        checks[key] = int(np.count_nonzero(bad))
        if checks[key]:
            pos = np.argwhere(bad)[:8]
            examples[key] = [dict(time=local(ts[k]), marker=str(names[j]), raw=float(rawx[k,j]) if finite[k,j] else None,
                                  astra=float(new['x'][k,j]) if np.isfinite(new['x'][k,j]) else None,
                                  flags=int(flags[k,j])) for k,j in pos]

    check('x_finite_mask_mismatch', finite != np.isfinite(new['x']))
    check('y_finite_mask_mismatch', np.isfinite(old['y']) != np.isfinite(new['y']))
    yf = np.isfinite(old['y']) & np.isfinite(new['y'])
    check('y_value_mismatch', yf & (old['y'] != new['y']))
    check('y_finite_bits_mismatch', yf & (old['y'].view('<u8') != new['y'].view('<u8')))
    check('output_nonfinite_from_valid_raw', finite & ~np.isfinite(new['x']))
    check('nonfinite_budget_for_valid_raw', finite & ~np.isfinite(budget))
    check('negative_budget', np.isfinite(budget) & (budget < -tol))
    check('correction_exceeds_reported_budget', finite & (np.abs(corr) > budget+tol))
    if args.hard_cap is not None:
        check('correction_exceeds_experimental_hard_cap', finite & (np.abs(corr) > args.hard_cap+tol))
    deviation = rawx-reference
    check('correction_away_from_reference', reference_ok & (corr*deviation < -tol))
    check('output_crosses_reference', reference_ok & ((new['x']-reference)*deviation < -tol))
    check('reference_distance_increased', reference_ok & (np.abs(new['x']-reference) > np.abs(deviation)+tol))
    check('outside_window_raw_changed', finite & outside & (new['x'] != rawx))
    check('no_reference_raw_changed', finite & ~np.isfinite(reference) & (new['x'] != rawx))
    locked = finite & ((flags & 96) != 0)
    check('locked_raw_changed', locked & (new['x'] != rawx))
    check('flagged_core_unavailable_raw_changed', finite & ((flags & 4) != 0) & (new['x'] != rawx))

    # Reconstruct event locks independently from valid raw samples and timestamps.
    # A new night starts at local noon, matching the algorithm's clock convention.
    night_ids = (ts + 8*3600000 - 12*3600000)//86400000
    missing_step = np.zeros_like(finite)
    missing_gap = np.zeros_like(finite)
    missing_persist = np.zeros_like(finite)
    expected_step_events = expected_gap_events = 0
    for j in range(len(names)):
        ids = np.flatnonzero(finite[:,j])
        if len(ids)<2:
            continue
        prior, now = ids[:-1], ids[1:]
        dt = (ts[now]-ts[prior])/60000.0
        same = night_ids[now] == night_ids[prior]
        eligible = same & protect_event[now]
        gaps = eligible & (dt >= args.gap_min if args.gap_inclusive else dt > args.gap_min)
        steps = eligible & ~gaps & (np.abs(rawx[now,j]-rawx[prior,j]) >= args.step_units)
        expected_gap_events += int(gaps.sum())
        expected_step_events += int(steps.sum())
        missing_gap[now[gaps],j] = (flags[now[gaps],j]&64)==0
        missing_step[now[steps],j] = (flags[now[steps],j]&32)==0
        for nid in np.unique(night_ids[ids]):
            these = ids[night_ids[ids]==nid]
            seen = np.bitwise_or.accumulate(flags[these,j]&96)
            missing_persist[these,j] = active[these] & ((flags[these,j]&seen)!=seen)
    check('raw_step_missing_lock', missing_step)
    check('raw_gap_missing_lock', missing_gap)
    check('lock_not_retained_in_same_night', missing_persist)

    rows = []
    for day in range(2,16):
        night = f'2026-11-{day:02d}'
        split = 'warmup' if day<=4 else ('diagnostic' if day<=11 else 'holdout')
        if args.split and split != args.split:
            continue
        for window, start, stop, expected in [
            ('night_22_08', ms(night+' 22:00'), ms(f'2026-11-{day+1:02d} 08:00'),600),
            ('active_2320_07', ms(night+' 23:20'), ms(f'2026-11-{day+1:02d} 07:00'),460)]:
            chosen = (ts>=start)&(ts<stop)
            ix = np.flatnonzero(chosen)
            for j, name in enumerate(names):
                good = finite[ix,j]&np.isfinite(old['x'][ix,j])&np.isfinite(new['x'][ix,j])
                ti = ix[good]
                raw = rawx[ti,j]
                v54 = old['x'][ti,j]
                astra = new['x'][ti,j]
                row = dict(line=line, device=device, marker=str(name), night=night, split=split, window=window,
                           recorded_frames=len(ix), valid_raw_frames=int(finite[ix,j].sum()), common_frames=len(ti),
                           expected_frames=expected, coverage_ratio=len(ti)/expected, eligible=len(ti)>=args.coverage*expected)
                for label, values in [('raw',raw),('v54',v54),('astra',astra)]:
                    for key, val in stats(values).items():
                        row[f'{label}_{key}_units']=val
                spread = row['raw_p95p5_units']
                row['category'] = 'missing' if spread is None else ('quiet' if spread<=0.5 else ('moderate' if spread<=2 else 'large'))
                row['target_range_units'] = 1.0 if 'J' in str(name).upper() else 2.0
                row['target_class'] = 'J_or_XJ' if 'J' in str(name).upper() else 'ordinary'
                if len(ti):
                    for label in ['raw','v54','astra']:
                        row[label+'_range_target_pass'] = row[label+'_p2p_units'] <= row['target_range_units']+1e-10
                    row['v54_broke_raw_range_target'] = row['raw_range_target_pass'] and not row['v54_range_target_pass']
                    row['astra_recovered_v54_range_failure'] = row['v54_broke_raw_range_target'] and row['astra_range_target_pass']
                    row['astra_broke_raw_range_target'] = row['raw_range_target_pass'] and not row['astra_range_target_pass']
                    row['astra_lost_v54_repair_target'] = (not row['raw_range_target_pass']) and row['v54_range_target_pass'] and not row['astra_range_target_pass']
                    row.update(v54_max_abs_correction_units=float(np.max(np.abs(raw-v54))),
                               astra_max_abs_correction_units=float(np.max(np.abs(raw-astra))),
                               astra_corrected_fraction=float(np.mean(np.abs(raw-astra)>1e-12)),
                               astra_lock_fraction=float(np.mean((flags[ti,j]&96)!=0)),
                               astra_no_reference_fraction=float(np.mean((flags[ti,j]&2)!=0)),
                               astra_core_unavailable_fraction=float(np.mean((flags[ti,j]&4)!=0)))
                    row['astra_p95p5_change_units']=row['astra_p95p5_units']-spread
                    row['v54_p95p5_change_units']=row['v54_p95p5_units']-spread
                    row['astra_material_worsening']=row['astra_p95p5_change_units']>max(0.05,0.10*spread)
                    row['v54_material_worsening']=row['v54_p95p5_change_units']>max(0.05,0.10*spread)
                    consecutive=np.diff(ts[ti])<=90000
                    for label, values in [('raw',raw),('v54',v54),('astra',astra)]:
                        delta=np.abs(np.diff(values))[consecutive]
                        row[label+'_max_contiguous_step_units']=float(delta.max()) if len(delta) else None
                rows.append(row)
    finite_corr = np.abs(corr[finite])
    device_summary=dict(line=line,device=device,frames=len(ts),markers=len(names),valid_x_cells=int(finite.sum()),
                        max_abs_correction_units=float(np.max(finite_corr)) if len(finite_corr) else None,
                        raw_step_events=expected_step_events,raw_gap_events=expected_gap_events,
                        flag_counts={key:int(np.count_nonzero(finite&((flags&value)!=0))) for key,value in FLAGS.items()},
                        checks=checks,violation_examples=examples)
    print('METRICS',line,device,'rows',len(rows),'violations',sum(checks.values()),flush=True)
    return rows,device_summary

def summarize(df):
    grouped=[]
    eligible=df[df.eligible].copy()
    for keys,g in eligible.groupby(['split','window','line','category']):
        row=dict(zip(['split','window','line','category'],keys));row['point_nights']=len(g)
        for label in ['raw','v54','astra']:
            row[label+'_median_spread_units']=float(g[label+'_p95p5_units'].median())
            row[label+'_mean_spread_units']=float(g[label+'_p95p5_units'].mean())
        row['astra_material_worsening']=int(g.astra_material_worsening.sum())
        row['v54_material_worsening']=int(g.v54_material_worsening.sum())
        row['astra_any_spread_increase']=int((g.astra_p95p5_change_units>1e-10).sum())
        row['astra_any_spread_decrease']=int((g.astra_p95p5_change_units < -1e-10).sum())
        row['astra_unchanged_spread']=len(g)-row['astra_any_spread_increase']-row['astra_any_spread_decrease']
        row['astra_max_abs_correction_units']=float(g.astra_max_abs_correction_units.max())
        row['astra_mean_corrected_fraction']=float(g.astra_corrected_fraction.mean())
        row['astra_mean_lock_fraction']=float(g.astra_lock_fraction.mean())
        for label in ['raw','v54','astra']:
            row[label+'_range_target_pass_count']=int(g[label+'_range_target_pass'].sum())
        for label in ['v54_broke_raw_range_target','astra_recovered_v54_range_failure','astra_broke_raw_range_target','astra_lost_v54_repair_target']:
            row[label]=int(g[label].sum())
        grouped.append(row)
    return grouped

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--hard-cap',type=float,default=1.0)
    parser.add_argument('--step-units','--step-mm',dest='step_units',type=float,default=2.0)
    parser.add_argument('--gap-min',type=float,default=3.0)
    parser.add_argument('--gap-inclusive',action='store_true')
    parser.add_argument('--coverage',type=float,default=0.8)
    parser.add_argument('--line');parser.add_argument('--device')
    parser.add_argument('--split',choices=['warmup','diagnostic','holdout'])
    args=parser.parse_args()
    all_rows=[];devices=[]
    for path in sorted((ROOT/'data').glob('*/*/input.npz')):
        if args.line and path.parent.parent.name!=args.line:continue
        if args.device and path.parent.name!=args.device:continue
        rows,summary=analyze_device(path,args);all_rows+=rows;devices.append(summary)
    if not devices:raise RuntimeError('No devices analyzed')
    df=pd.DataFrame(all_rows)
    dest=ROOT/'reports';dest.mkdir(exist_ok=True)
    suffix=('__'+args.line if args.line else '')+('__'+args.device if args.device else '')+('__'+args.split if args.split else '')
    df.to_csv(dest/('metrics_point_nights'+suffix+'.csv'),index=False,encoding='utf-8-sig')
    df[~df.eligible].to_csv(dest/('metrics_incomplete'+suffix+'.csv'),index=False,encoding='utf-8-sig')
    df[df.eligible & (df.astra_material_worsening==True)].sort_values('astra_p95p5_change_units',ascending=False).to_csv(
        dest/('metrics_regressions'+suffix+'.csv'),index=False,encoding='utf-8-sig')
    df[df.eligible & (df.astra_range_target_pass==False)].sort_values('astra_p2p_units',ascending=False).to_csv(
        dest/('metrics_range_failures'+suffix+'.csv'),index=False,encoding='utf-8-sig')
    df[df.eligible & (df.astra_lost_v54_repair_target==True)].sort_values('astra_p2p_units',ascending=False).to_csv(
        dest/('metrics_lost_v54_repairs'+suffix+'.csv'),index=False,encoding='utf-8-sig')
    groups=summarize(df)
    pd.DataFrame(groups).to_csv(dest/('metrics_groups'+suffix+'.csv'),index=False,encoding='utf-8-sig')
    totals={key:sum(d['checks'].get(key,0) for d in devices) for key in devices[0]['checks']}
    summary=dict(input_unit='pixel',unit_source='Explicit user confirmation in this chat, 2026-11-16; raw input x/y are pixel',parameters=vars(args),definitions={
        'windows':'Asia/Shanghai; 22:00 <= t < next08:00 and 23:20 <= t < next07:00',
        'split':'11/02-04 warmup, 11/05-11 diagnostic, 11/12-15 later-period review (internal label holdout); not a strict blind validation because one device v1 summary was previously viewed; no parameter fitting in this script',
        'category':'raw P95-P5 <=0.5 input units quiet; >0.5 and <=2 moderate; >2 large, separately in each window',
        'eligibility':'common finite raw/V54/Astra count >=80% nominal 600/460 minute frames; no interpolation',
        'material_worsening':'Astra P95-P5 minus raw > max(0.05 input units, 10% of raw spread)',
        'bounds':'Experimental correction budgets are pixel; these are separate from user nightly range targets and are not proof of physical truth',
        'range_target':'User target is full max-min <=2 pixel ordinary and <=1 pixel for J/XJ markers; J match includes any J in marker name',
        'rate':'rate limiting is soft; direction rejection, deadband, window exit and event bypass take precedence'},
        devices=devices,total_checks=totals,all_numerical_invariants_pass=not any(totals.values()),groups=groups,
        total_point_window_nights=len(df),eligible_point_window_nights=int(df.eligible.sum()),
        material_regressions=int((df.eligible&(df.astra_material_worsening==True)).sum()))
    dump(dest/('metrics_summary'+suffix+'.json'),summary)
    print(json.dumps({k:summary[k] for k in ['all_numerical_invariants_pass','total_point_window_nights','eligible_point_window_nights','material_regressions']}),flush=True)

if __name__=='__main__':main()

