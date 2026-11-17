"""Read-only reference/coherence audit of frozen 2026-11-12 left-line X outputs.
No native execution, time shifting, gain fitting, or generated corrected values.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import csv, hashlib, json, math, re, struct, warnings
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent
OUT = ROOT / 'reports'
TZ = timezone(timedelta(hours=8))
def ms(s): return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
REF = (ms('2026-11-12 22:00'), ms('2026-11-12 23:00'))
SHIFT = (ms('2026-11-13 03:00'), ms('2026-11-13 06:00'))
WINDOWS = {'23_07': (REF[1], ms('2026-11-13 07:00')),
           '22_08': (REF[0], ms('2026-11-13 08:00'))}
def mask(t, bounds): return (t >= bounds[0]) & (t < bounds[1])
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def clean(v):
    if isinstance(v, dict): return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [clean(x) for x in v]
    if isinstance(v, np.ndarray): return clean(v.tolist())
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating, float)): return float(v) if math.isfinite(v) else None
    return v
def scalar_stats(v):
    z = np.asarray(v); z = z[np.isfinite(z)]
    if not len(z): return {'n': 0, 'range': None, 'p95p05': None, 'mean': None, 'median': None}
    return dict(n=len(z), range=float(np.ptp(z)), p95p05=float(np.quantile(z,.95)-np.quantile(z,.05)),
                mean=float(np.mean(z)), median=float(np.median(z)))
def corr(a, b):
    q = np.isfinite(a) & np.isfinite(b)
    if q.sum() < 10 or np.std(a[q]) < 1e-10 or np.std(b[q]) < 1e-10: return None
    return float(np.corrcoef(a[q],b[q])[0,1])
def binned(t, v, bounds):
    # Fixed absolute 15-minute bins, for low-frequency descriptive correlation only.
    out=[]
    for a in range(bounds[0], bounds[1], 15*60000):
        z=v[(t>=a)&(t<a+15*60000)];z=z[np.isfinite(z)]
        out.append(float(np.median(z)) if len(z)>=10 else np.nan)
    return np.array(out)
def pair(t,a,b,bounds):
    q=mask(t,bounds)&np.isfinite(a)&np.isfinite(b)
    aa=binned(t,a,bounds);bb=binned(t,b,bounds)
    return dict(paired_frames=int(q.sum()),r=corr(a[q],b[q]),
                paired_15min_bins=int((np.isfinite(aa)&np.isfinite(bb)).sum()),r_15min=corr(aa,bb),
                r_15min_increments=corr(np.diff(aa),np.diff(bb)),
                difference=scalar_stats((a-b)[q]),
                difference_03_06=scalar_stats((a-b)[mask(t,SHIFT)&np.isfinite(a)&np.isfinite(b)]))
def common(matrix, columns):
    if not columns: return np.full(len(matrix), np.nan)
    v=matrix[:,columns];need=math.ceil(.8*len(columns))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning); c=np.nanmedian(v,axis=1)
    c[np.isfinite(v).sum(axis=1)<need]=np.nan
    return c
def write_csv(p, rows):
    with p.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(clean(rows))
def fmt(v): return '—' if v is None else f'{v:.3f}'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    devices=[];points=[];pairs=[];packed={}
    for src in sorted((BASE/'data/left').glob('*/input.npz')):
        d=np.load(src);names=[str(x) for x in d['names']]
        targets=[j for j,n in enumerate(names) if re.match(r'^ZD(42|43|44|45|46|47)\d+$',n)]
        if not targets: continue
        dev=src.parent.name;t=d['timestamp'];allsel=mask(t,WINDOWS['22_08']);t=t[allsel]
        raw=d['x'][allsel];online=d['online_x'][allsel];roi=d['roi'][allsel]
        op=BASE/'round2_waveform_10n/results/current_fade07/left'/dev/'output.bin'
        with op.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
        native=np.memmap(op,dtype=np.dtype([('timestamp','<i8'),('xy','<f8',(2,m))]),mode='r',offset=8,shape=(n,))
        assert m==len(names) and np.array_equal(native['timestamp'],d['timestamp'])
        result=np.asarray(native['xy'][allsel,0]);assert np.array_equal(np.isfinite(raw),np.isfinite(result))
        published=result.copy();outside=~mask(t,WINDOWS['23_07']);published[outside]=raw[outside]
        series={'raw':raw,'database_calX':online,'native_Astra':result,'published_Astra':published}
        references=[j for j,nm in enumerate(names) if 'J' in nm]
        xj=[j for j in references if 'XJ' in names[j]]
        js=[j for j in references if j not in xj]
        others=[j for j,nm in enumerate(names) if j not in targets and j not in references]
        groups={'target_42_47':targets,'other_ordinary':others,'J_reference':js,'XJ':xj}
        record=dict(device=dev,markers=m,targets=[names[j] for j in targets],references=[names[j] for j in references],
                    groups={k:[names[j] for j in v] for k,v in groups.items()},frames_22_08=len(t),
                    input_sha256=sha(src),output_sha256=sha(op),windows={})
        status_path=op.with_name('status.csv')
        with status_path.open(encoding='utf8') as f:
            status=[s for s in csv.DictReader(f) if WINDOWS['23_07'][0]<=int(s['timestamp'])<WINDOWS['23_07'][1]]
        record['status_23_07']=dict(frames=len(status),states={s:sum(v['state_x']==s for v in status) for s in sorted(set(v['state_x'] for v in status))},
            histories=sorted(set(int(v['history_x']) for v in status)),modes=sorted(set(int(v['modes_x']) for v in status)),
            corrected_min=min(int(v['corrected_x']) for v in status),corrected_max=max(int(v['corrected_x']) for v in status),sha256=sha(status_path))
        packed[dev+'_timestamp']=t;packed[dev+'_names']=np.array(names)
        for label,mat in series.items(): packed[dev+'_'+label]=mat
        for window,bounds in WINDOWS.items():
            active=mask(t,bounds);ref=mask(t,REF);late=mask(t,SHIFT)
            eligible=[j for j in range(m) if np.isfinite(raw[active,j]).sum()>=.8*active.sum() and np.isfinite(raw[ref,j]).sum()>=10]
            eligible_groups={k:[j for j in v if j in eligible] for k,v in groups.items()}
            wrec=dict(frames=int(active.sum()),eligible_groups={k:[names[j] for j in v] for k,v in eligible_groups.items()},series={})
            for label,mat in series.items():
                # Every series/point uses its OWN 22-23 mean; diagnostic only.
                baseline=np.array([np.nanmean(mat[ref,j]) if np.isfinite(mat[ref,j]).sum()>=10 else np.nan for j in range(m)])
                centered=mat-baseline
                cs={k:common(centered,idx) for k,idx in eligible_groups.items()}
                group_stats={k:dict(window=scalar_stats(v[active]),delta_03_06_mean=scalar_stats(v[late])['mean']) for k,v in cs.items()}
                comparisons={k:pair(t,cs['target_42_47'],v,bounds) for k,v in cs.items() if k!='target_42_47'}
                pair_rs=[];pair_bin_rs=[]
                idx=eligible_groups['target_42_47']
                for ia,j in enumerate(idx):
                    for k in idx[ia+1:]:
                        p=pair(t,centered[:,j],centered[:,k],bounds)
                        if p['r'] is not None:pair_rs.append(p['r'])
                        if p['r_15min'] is not None:pair_bin_rs.append(p['r_15min'])
                reference_comparisons={names[j]+' vs '+names[k]:pair(t,centered[:,j],centered[:,k],bounds)
                                       for j in xj for k in js}
                if js and xj:
                    reference_comparisons['XJ vs J_reference']=pair(t,cs['XJ'],cs['J_reference'],bounds)
                wrec['series'][label]=dict(group_stats=group_stats,group_comparisons=comparisons,
                    xj_reference_comparisons=reference_comparisons,
                    target_pairwise_r_summary=scalar_stats(pair_rs),target_pairwise_r_15min_summary=scalar_stats(pair_bin_rs))
                for j in targets+references:
                    refstats=scalar_stats(mat[ref,j]);late_stats=scalar_stats(mat[late,j]);stats=scalar_stats(mat[active,j])
                    rows=dict(device=dev,window=window,series=label,marker=names[j],role='target' if j in targets else 'XJ' if j in xj else 'J',
                              eligible=j in eligible,frames=stats['n'],range=stats['range'],p95p05=stats['p95p05'],
                              baseline_mean_22_23=refstats['mean'],baseline_frames=refstats['n'],late_frames=late_stats['n'],
                              delta_03_06_mean=(late_stats['mean']-refstats['mean']) if late_stats['mean'] is not None and refstats['mean'] is not None else None,
                              delta_03_06_median=(late_stats['median']-refstats['median']) if late_stats['median'] is not None and refstats['median'] is not None else None)
                    points.append(rows)
                    if j in targets:
                        for refname,rv in [(names[k],centered[:,k]) for k in references]+[(k,cs[k]) for k in ['other_ordinary','J_reference'] if eligible_groups[k]]:
                            p=pair(t,centered[:,j],rv,bounds)
                            pairs.append(dict(device=dev,window=window,series=label,marker=names[j],reference=refname,
                                paired_frames=p['paired_frames'],r=p['r'],paired_15min_bins=p['paired_15min_bins'],r_15min=p['r_15min'],
                                difference_range=p['difference']['range'],difference_p95p05=p['difference']['p95p05']))
                for key,c in cs.items(): packed[dev+'_'+window+'_'+label+'_'+key]=c
            # Compare algorithm residual shape with raw; no fitted time or gain.
            wrec['raw_to_output']={}
            for label,mat in series.items():
                if label=='raw':continue
                wrec['raw_to_output'][label]={names[j]:pair(t,raw[:,j],mat[:,j],bounds) for j in targets+references}
            record['windows'][window]=wrec
        devices.append(record)
    # Same-name observations across cameras: each has own reference; no pixel subtraction across devices.
    cross=[]
    for i,a in enumerate(devices):
        for b in devices[i+1:]:
            an=packed[a['device']+'_names'].tolist();bn=packed[b['device']+'_names'].tolist()
            shared=sorted(set(a['targets']+a['references'])&set(b['targets']+b['references']))
            ta=packed[a['device']+'_timestamp'];tb=packed[b['device']+'_timestamp']
            for name in shared:
                for label in ['raw','database_calX','native_Astra','published_Astra']:
                    va=packed[a['device']+'_'+label][:,an.index(name)];vb=packed[b['device']+'_'+label][:,bn.index(name)]
                    ba=scalar_stats(va[mask(ta,REF)])['mean'];bb=scalar_stats(vb[mask(tb,REF)])['mean']
                    if ba is None or bb is None:continue
                    aa=binned(ta,va-ba,WINDOWS['23_07']);zz=binned(tb,vb-bb,WINDOWS['23_07'])
                    cross.append(dict(device_a=a['device'],device_b=b['device'],marker=name,series=label,
                                      paired_15min_bins=int((np.isfinite(aa)&np.isfinite(zz)).sum()),r_15min=corr(aa,zz),
                                      delta_a_03_06=scalar_stats(va[mask(ta,SHIFT)])['mean']-ba,
                                      delta_b_03_06=scalar_stats(vb[mask(tb,SHIFT)])['mean']-bb))
    report=dict(night='2026-11-12',reference_window='22:00-23:00 per-point and per-series mean',
                shift_window='2026-11-13 03:00-06:00',profile='current_fade07',
                correlation='Pearson; 15-minute absolute bin medians with >=10 finite samples/bin; no lag/gain fitting',
                grouping='Fixed per-window roster: >=80% raw coverage and >=10 valid reference frames; per-frame group median requires >=80% fixed donors',
                limits='Descriptive pixel-domain coherence, not camera geometry, physical cause or total-station alignment. Same names across cameras are not subtracted.',
                devices=devices,cross_camera_same_name=cross)
    (OUT/'reference_trend_audit.json').write_text(json.dumps(clean(report),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    write_csv(OUT/'reference_trend_audit.points.csv',points)
    write_csv(OUT/'reference_trend_audit.pairs.csv',pairs)
    write_csv(OUT/'reference_trend_audit.cross_camera.csv',cross)
    np.savez_compressed(OUT/'reference_trend_audit.timeseries.npz',**packed)
    # Compact readout for independent interpretation; narrative report is separate.
    for d in devices:
        print('DEVICE',d['device'],'targets',len(d['targets']),'refs',d['references'])
        w=d['windows']['23_07']
        for label in ['raw','database_calX','native_Astra']:
            s=w['series'][label]
            print(label,'target',s['group_stats']['target_42_47'],
                  'r15_target_pairs',s['target_pairwise_r_15min_summary']['median'],
                  'comparisons',{k:v['r_15min'] for k,v in s['group_comparisons'].items()})
    print('WROTE',str(OUT/'reference_trend_audit.json'))

if __name__=='__main__':main()
