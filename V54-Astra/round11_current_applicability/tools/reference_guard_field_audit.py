"""Fixed reference gate shadow on frozen native output; never runs/changes native code."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from collections import Counter
import json,struct,warnings
import numpy as np
from reference_activity_guard import apply_reference_activity_guard

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=ROOT/'reports';TZ=timezone(timedelta(hours=8))
DATES=[f'2026-11-{i:02d}' for i in range(6,16)]
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def stats(a,t,lo):
    a=np.asarray(a);v=a[np.isfinite(a)]
    if not len(v):return dict(n=0,range=None,qspan=None,jump=None,late=None)
    ok=np.isfinite(a[1:])&np.isfinite(a[:-1])&(np.diff(t)<=180000)
    late=a[(t>=lo+4*3600000)&(t<lo+7*3600000)];late=late[np.isfinite(late)]
    return dict(n=len(v),range=float(np.ptp(v)),qspan=float(np.quantile(v,.95)-np.quantile(v,.05)),
        jump=float(np.max(np.abs(np.diff(a))[ok])) if ok.any() else None,late=float(np.median(late)) if len(late) else None)
def aggregate(rows):
    rows=[r for r in rows if r['eligible']]
    d=dict(eligible=len(rows))
    for key in ['base','shadow']:
        d[key]=dict(le1=sum(r[key]['range']<=1+1e-9 for r in rows),
            role_pass=sum(r[key]['range']<=r['limit']+1e-9 for r in rows),
            range_above_raw_by_0p1=sum(r[key]['range']>r['raw']['range']+.1 for r in rows),
            range_median=float(np.median([r[key]['range'] for r in rows])) if rows else None)
    d.update(better_than_base_by_0p1=sum(r['delta_range']<-.1 for r in rows),worse_than_base_by_0p1=sum(r['delta_range']>.1 for r in rows),
        new_cross1=sum(r['base']['range']<=1+1e-9 and r['shadow']['range']>1+1e-9 for r in rows),
        new_role_failure=sum(r['base']['range']<=r['limit']+1e-9 and r['shadow']['range']>r['limit']+1e-9 for r in rows))
    return d
def main():
    rows=[];devices=[];representatives={};OUT.mkdir(parents=True,exist_ok=True)
    for source in sorted((BASE/'data').glob('*/*/input.npz')):
        line,dev=source.parts[-3:-1]
        with np.load(source) as z:ts=z['timestamp'];names=z['names'];raw=z['x'];y=z['y']
        p=BASE/'round2_waveform_10n/results/current_fade07'/line/dev/'output.bin'
        with p.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
        native=np.memmap(p,dtype=np.dtype([('timestamp','<i8'),('xy','<f8',(2,m))]),offset=8,mode='r',shape=(n,))
        base=native['xy'][:,0,:]
        assert np.array_equal(ts,native['timestamp']) and m==len(names)
        g=apply_reference_activity_guard(ts,names,raw,y,base);shadow=g['x']
        assert np.array_equal(np.isfinite(shadow),np.isfinite(base))
        scopes=np.zeros(n,bool)
        for night in DATES:
            lo=ms(night+'T23:00');take=(ts>=lo)&(ts<lo+8*3600000);scopes|=take;t=ts[take]
            bsel=(ts>=lo-3600000)&(ts<lo)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',RuntimeWarning);ref=np.nanmedian(raw[bsel],axis=0) if bsel.any() else np.full(m,np.nan)
            status=dict(Counter(g['status'][take].tolist()))
            for j,name in enumerate(names):
                name=str(name);role='XJ' if 'XJ' in name else 'J' if name.startswith(('YJ','ZJ')) else 'ordinary'
                a,b,c=[stats(x[take,j]-ref[j],t,lo) for x in [raw,base,shadow]]
                eligible=min(a['n'],b['n'],c['n'])>=384
                row=dict(case_id=f'{line}/{dev}/{night}/{name}',line=line,device=dev,night=night,marker=name,role=role,limit=2 if role=='ordinary' else 1,
                    eligible=eligible,raw=a,base=b,shadow=c,raw_quiet=bool(eligible and a['range']<=1+1e-9),
                    delta_range=c['range']-b['range'] if eligible else None,delta_jump=c['jump']-b['jump'] if eligible else None,
                    guard_applied_frames=int(g['guard_applied'][take].sum()),status_frames=status)
                rows.append(row)
                if (dev=='780638327479' and night=='2026-11-12' and name in ['ZXJ6','ZD4703','ZJ7']) or (dev=='780638349768' and night=='2026-11-14' and name=='ZD4404'):
                    representatives[row['case_id']]={**row,'ts':t.tolist(),'raw_series':raw[take,j].tolist(),'base_series':base[take,j].tolist(),'shadow_series':shadow[take,j].tolist(),'gain':g['gain'][take].tolist()}
        devices.append(dict(line=line,device=dev,j_names=g['j_names'],status_frames=dict(Counter(g['status'][scopes].tolist())),night_summaries=[x for x in g['night_summaries'] if x['night'] in DATES],masks_equal=True))
        np.savez_compressed(OUT/f'reference_guard_{line}_{dev}.npz',timestamp=ts,names=names,shadow_x=shadow,gain=g['gain'],status=g['status'],activity_r=g['activity_r'],valid_j_count=g['valid_j_count'])
        print('AUDIT_OK',line,dev,len(g['j_names']),flush=True)
    primary=[r for r in rows if r['role']!='XJ']
    report=dict(method='Frozen native current_fade07 final X plus isolated causal reference-activity overlay. No native replay or physical truth for field data.',
        window='2026-11-06..15 [23:00,next07:00)',summary={'all':aggregate(rows),'ordinary_J':aggregate(primary),'quiet_ordinary_J':aggregate([r for r in primary if r['raw_quiet']]),'quiet_all':aggregate([r for r in rows if r['raw_quiet']])},
        config=g['config'],devices=devices,largest_regressions=sorted([r for r in rows if r['eligible']],key=lambda r:r['delta_range'],reverse=True)[:20],
        largest_new_jumps=sorted([r for r in rows if r['eligible']],key=lambda r:r['delta_jump'],reverse=True)[:20],representatives=representatives,points=rows)
    (OUT/'reference_guard_field_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=True),encoding='utf8')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2),flush=True)
    print('TOP_RANGE',[(r['case_id'],r['base']['range'],r['shadow']['range']) for r in report['largest_regressions'][:5]],flush=True)
    print('TOP_JUMP',[(r['case_id'],r['base']['jump'],r['shadow']['jump']) for r in report['largest_new_jumps'][:5]],flush=True)
if __name__=='__main__':main()
