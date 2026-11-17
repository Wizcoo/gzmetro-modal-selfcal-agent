"""Complete ten-calendar-night range audit; no model fitting or time shifts."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import argparse,json,struct
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
PARENT=ROOT.parent
TZ=timezone(timedelta(hours=8))
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def read(p):
    with p.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    dt=np.dtype([('timestamp','<i8'),('xy','<f8',(2,m))])
    assert p.stat().st_size==8+n*dt.itemsize
    return np.memmap(p,dtype=dt,mode='r',offset=8,shape=(n,))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--profiles',nargs='*');args=ap.parse_args()
    profiles=args.profiles or sorted(p.name for p in (ROOT/'results').iterdir() if p.is_dir())
    rows=[];coverage=[]
    for inp in sorted((PARENT/'data').glob('*/*/input.npz')):
        line,dev=inp.parent.parent.name,inp.parent.name
        data=np.load(inp);ts=data['timestamp'];raw=data['x'];names=data['names']
        result={'raw':raw}
        for prof in profiles:
            p=ROOT/'results'/prof/line/dev/'output.bin'
            if not p.exists():continue
            z=read(p);assert np.array_equal(ts,z['timestamp'])
            result[prof]=z['xy'][:,0,:]
        for day in range(6,16):
            date=f'2026-11-{day:02d}';t0=ms(date+' 22:00')
            for window,lo,hi,expected in [('full',0,600,600),('active',80,540,460)]:
                ix=(ts>=t0+lo*60000)&(ts<t0+hi*60000)
                count=ix.sum();coverage.append(dict(line=line,device=dev,night=date,window=window,frames=int(count),expected=expected))
                raw0=raw[ix];valid=np.isfinite(raw0)
                for prof,values in result.items():
                    x=values[ix];assert np.array_equal(valid,np.isfinite(x))
                    for j,name in enumerate(names):
                        v=x[:,j];v=v[np.isfinite(v)];r=raw0[:,j];r=r[np.isfinite(r)]
                        n=len(v);eligible=n>=.8*expected
                        p2p=float(np.ptp(v)) if n else np.nan
                        span=float(np.diff(np.quantile(v,[.05,.95]))[0]) if n else np.nan
                        rp2p=float(np.ptp(r)) if n else np.nan
                        rspan=float(np.diff(np.quantile(r,[.05,.95]))[0]) if n else np.nan
                        special='J' in str(name).upper();limit=1. if special else 2.
                        rows.append(dict(profile=prof,line=line,device=dev,marker=str(name),night=date,window=window,
                          valid=n,expected=expected,eligible=eligible,special_j=special,limit=limit,p2p=p2p,p95p5=span,raw_p2p=rp2p,raw_p95p5=rspan,
                          pass1=bool(eligible and p2p<=1+1e-9),pass2=bool(eligible and p2p<=2+1e-9),pass_class=bool(eligible and p2p<=limit+1e-9),
                          material_amplification=bool(eligible and span-rspan>max(.05,.1*rspan)),
                          quiet_raw_under1=bool(eligible and rp2p<=1+1e-9),quiet_broken1=bool(eligible and rp2p<=1+1e-9 and p2p>1+1e-9)))
        print(line,dev,flush=True)
    df=pd.DataFrame(rows);df.to_csv(ROOT/'reports/range_point_nights.csv',index=False)
    pd.DataFrame(coverage).to_csv(ROOT/'reports/range_coverage.csv',index=False)
    eligible=df[df.eligible];summary=[];bynight=[]
    def collect(keys,g):
        d=dict(zip(keys[0],keys[1]));d.update(n=len(g),pass1=int(g.pass1.sum()),pass2=int(g.pass2.sum()),pass_class=int(g.pass_class.sum()),
           p2p_median=float(g.p2p.median()),p2p_p95=float(g.p2p.quantile(.95)),p2p_max=float(g.p2p.max()),
           material_amplification=int(g.material_amplification.sum()),quiet_raw_under1=int(g.quiet_raw_under1.sum()),quiet_broken1=int(g.quiet_broken1.sum()))
        for k in ['pass1','pass2','pass_class']:d[k+'_pct']=100*d[k]/d['n']
        return d
    for k,g in eligible.groupby(['profile','window']):summary.append(collect((['profile','window'],k),g))
    for k,g in eligible.groupby(['profile','window','night']):bynight.append(collect((['profile','window','night'],k),g))
    pd.DataFrame(summary).to_csv(ROOT/'reports/range_summary.csv',index=False)
    pd.DataFrame(bynight).to_csv(ROOT/'reports/range_by_night.csv',index=False)
    (ROOT/'reports/range_summary.json').write_text(json.dumps(dict(period='2026-11-06 22:00 through 2026-11-16 08:00; ten calendar nights',
        windows=dict(full='22:00 inclusive to next 08:00 exclusive',active='23:20 inclusive to next 07:00 exclusive'),
        rule='Night max-min of finite ROI-valid x in pixel; >=80% expected samples; ordinary <=2, name containing J <=1; all-marker <=1 separately.',
        missing='Left entire 2026-11-06 night absent, retained as ineligible rows. No fill, substitution, or future-dependent correction.',summary=summary),ensure_ascii=False,indent=2),encoding='utf8')
    print(pd.DataFrame(summary).to_string(index=False))
if __name__=='__main__':main()
