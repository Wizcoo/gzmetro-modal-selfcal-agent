"""23:00-07:00 numerical range and XJ/common-trend diagnostics, frozen outputs only."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import sys,json,struct,hashlib,warnings
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;R2=BASE/'round2_waveform_10n'
OUT=ROOT/'reports';OUT.mkdir(parents=True,exist_ok=True)
TZ=timezone(timedelta(hours=8));PROFILE='current_fade07'

def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def iso(t):return datetime.fromtimestamp(int(t)/1000,TZ).isoformat(sep=' ',timespec='milliseconds')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def read(p):
    with p.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    dtype=np.dtype([('timestamp','<i8'),('xy','<f8',(2,m))]);assert p.stat().st_size==8+n*dtype.itemsize
    return np.memmap(p,dtype=dtype,mode='r',offset=8,shape=(n,))
def span(v,q=None):
    a=np.asarray(v);a=a[np.isfinite(a)]
    if not len(a):return np.nan
    return float(np.ptp(a)) if q is None else float(np.diff(np.quantile(a,q))[0])
def role(s):return 'XJ' if 'XJ' in s else 'J_fixed' if 'J' in s else 'ordinary'
def correlation(a,b):
    good=np.isfinite(a)&np.isfinite(b);a=a[good];b=b[good]
    if len(a)<3 or np.std(a)<1e-10 or np.std(b)<1e-10:return np.nan
    return float(np.corrcoef(a,b)[0,1])
def directions(t,a,b,k=5):
    if len(t)<=k:return (0,np.nan)
    da=a[k:]-a[:-k];db=b[k:]-b[:-k];dt=(t[k:]-t[:-k])/60000
    good=np.isfinite(da)&np.isfinite(db)&(dt>=k-.5)&(dt<=k+.5)&(abs(da)>1e-9)&(abs(db)>1e-9)
    return int(good.sum()),float(np.mean(np.sign(da[good])==np.sign(db[good]))) if good.any() else np.nan

def main():
    rows=[];xj=[];checks=[];special_traces={};pools=[]
    for source in sorted((BASE/'data').glob('*/*/input.npz')):
        line,dev=source.parent.parent.name,source.parent.name
        with np.load(source) as d:ts=d['timestamp'];names=[str(n) for n in d['names']];raw=d['x'];cal=d['online_x']
        output=R2/'results'/PROFILE/line/dev/'output.bin';native=read(output);new=native['xy'][:,0,:]
        assert np.array_equal(ts,native['timestamp']) and np.array_equal(np.isfinite(raw),np.isfinite(new))
        checks.append(dict(line=line,device=dev,input_sha256=sha(source),output_sha256=sha(output),markers=len(names),frames=len(ts),timestamps_match=True,finite_masks_match=True))
        ordinary=np.array([i for i,n in enumerate(names) if role(n)=='ordinary'],int)
        for day in range(6,16):
            night=f'2026-11-{day:02d}';t0=ms(night+' 23:00');end=t0+480*60000;sel=(ts>=t0)&(ts<end);t=ts[sel]
            for label,data in [('raw',raw[sel]),(PROFILE,new[sel])]:
                for j,name in enumerate(names):
                    v=data[:,j];r=raw[sel,j];n=int(np.isfinite(v).sum());eligible=n>=384;limit=2. if role(name)=='ordinary' else 1.
                    p2p=span(v);p95=span(v,[.05,.95]);rp=span(r);rq=span(r,[.05,.95])
                    rows.append(dict(profile=label,line=line,device=dev,marker=name,role=role(name),night=night,window='23_07',valid=n,expected=480,eligible=eligible,limit=limit,p2p=p2p,p95p5=p95,raw_p2p=rp,raw_p95p5=rq,
                        pass1=bool(eligible and p2p<=1+1e-9),pass_class=bool(eligible and p2p<=limit+1e-9),material_amplification=bool(eligible and p95-rq>max(.05,.1*rq)),quiet_raw1=bool(eligible and rp<=1+1e-9),quiet_broken1=bool(eligible and rp<=1+1e-9 and p2p>1+1e-9)))
                if not len(t):continue
                baseline=t<t0+30*60000
                eligible_peers=ordinary[np.isfinite(data[baseline][:,ordinary]).sum(axis=0)>=24]
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',RuntimeWarning)
                    baselines=np.nanmedian(data[baseline],axis=0)
                pool_names=[names[i] for i in eligible_peers];minimum=max(3,int(np.ceil(.8*len(eligible_peers))))
                centered=data[:,eligible_peers]-baselines[eligible_peers]
                support=np.isfinite(centered).sum(axis=1)
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',RuntimeWarning)
                    common=np.nanmedian(centered,axis=1) if len(eligible_peers) else np.full(len(t),np.nan)
                common[support<minimum]=np.nan
                pools.append(dict(profile=label,line=line,device=dev,night=night,baseline='23:00-23:30 median per marker; >=24 finite of expected30',peer_names='|'.join(pool_names),peer_count=len(pool_names),minimum_valid_peers=minimum,common_valid=int(np.isfinite(common).sum())))
                for j,name in enumerate(names):
                    if role(name)!='XJ':continue
                    count=int(np.isfinite(data[baseline,j]).sum())
                    target=data[:,j]-baselines[j] if count>=24 else np.full(len(t),np.nan)
                    diff=target-common;paired=np.isfinite(target)&np.isfinite(common)
                    n5,d5=directions(t,target,common,5);n1,d1=directions(t,target,common,1)
                    peer_corr=[correlation(target,centered[:,k]) for k in range(centered.shape[1])]
                    finite_corr=np.array(peer_corr)[np.isfinite(peer_corr)]
                    rec=dict(profile=label,line=line,device=dev,marker=name,night=night,window='23_07',valid=int(np.isfinite(data[:,j]).sum()),eligible=int(np.isfinite(data[:,j]).sum())>=384,
                        target_baseline_valid=count,peer_count=len(pool_names),minimum_valid_peers=minimum,paired_samples=int(paired.sum()),paired_coverage=len(t) and float(paired.sum()/480),
                        target_range=span(target),common_range=span(common),relative_range=span(diff),target_p95p5=span(target,[.05,.95]),common_p95p5=span(common,[.05,.95]),relative_p95p5=span(diff,[.05,.95]),
                        correlation=correlation(target,common),five_min_direction_pairs=n5,five_min_direction_agreement=d5,one_min_direction_pairs=n1,one_min_direction_agreement=d1,
                        peer_corr_median=float(np.median(finite_corr)) if len(finite_corr) else np.nan,peer_corr_q25=float(np.quantile(finite_corr,.25)) if len(finite_corr) else np.nan,peer_corr_q75=float(np.quantile(finite_corr,.75)) if len(finite_corr) else np.nan,
                        target_gt1=bool(span(target)>1),relative_gt1_descriptive=bool(span(diff)>1),relative_range_reduction=float(1-span(diff)/span(target)) if span(target)>1e-9 else np.nan)
                    xj.append(rec)
                    if (line,dev,name,night) in [('left','780638327479','ZXJ6','2026-11-09'),('left','780637798298','ZXJ4','2026-11-07')]:
                        key=f'{line}_{dev}_{name}_{night}'
                        if key not in special_traces:special_traces[key]=dict(timestamp=[iso(v) for v in t],timestamp_ms=t,raw_x=raw[sel,j],database_calX=cal[sel,j],new_x=new[sel,j])
                        for k,v in [('baseline',np.full(len(t),baselines[j])),('centered_xj',target),('centered_peer_median',common),('relative_xj_minus_median',diff),('valid_peer_count',support)]:special_traces[key][label+'_'+k]=v
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore',RuntimeWarning)
                            q25,q75=np.nanquantile(centered,[.25,.75],axis=1)
                        q25[support<minimum]=np.nan;q75[support<minimum]=np.nan
                        special_traces[key][label+'_peer_q25']=q25;special_traces[key][label+'_peer_q75']=q75
            print(line,dev,night,flush=True)
    data=pd.DataFrame(rows);data.to_csv(OUT/'window_xj_point_nights.csv',index=False,encoding='utf-8-sig')
    def aggregate(g):
        eligible=g[g.eligible]
        return dict(nominal=len(g),eligible=len(eligible),passed=int(eligible.pass_class.sum()),pass1=int(eligible.pass1.sum()),failed=int((~eligible.pass_class).sum()),pass_pct=float(100*eligible.pass_class.mean()),pass1_pct=float(100*eligible.pass1.mean()),material_amplification=int(eligible.material_amplification.sum()),quiet_raw1=int(eligible.quiet_raw1.sum()),quiet_broken1=int(eligible.quiet_broken1.sum()),p2p_median=float(eligible.p2p.median()),p2p_max=float(eligible.p2p.max()))
    for suffix,keys in [('summary',['profile']),('by_night',['profile','night']),('by_role',['profile','role']),('by_device',['profile','line','device']),('by_device_night',['profile','line','device','night'])]:
        out=[]
        for kk,g in data.groupby(keys):
            if not isinstance(kk,tuple):kk=(kk,)
            out.append(dict(zip(keys,kk))|aggregate(g))
        pd.DataFrame(out).to_csv(OUT/f'window_xj_{suffix}.csv',index=False,encoding='utf-8-sig')
    x=pd.DataFrame(xj);x.to_csv(OUT/'window_xj_common_diagnostics.csv',index=False,encoding='utf-8-sig');pd.DataFrame(pools).to_csv(OUT/'window_xj_common_pools.csv',index=False,encoding='utf-8-sig')
    for key,values in special_traces.items():pd.DataFrame(values).to_csv(OUT/f'window_xj_trace_{key}.csv',index=False,encoding='utf-8-sig')
    scope=data[(data.profile==PROFILE)&(data.line=='left')&(data.device=='780637798298')&(data.night=='2026-11-07')]
    scope.to_csv(OUT/'window_xj_user_case_left798298_1107.csv',index=False,encoding='utf-8-sig')
    jsonout={'window':'23:00 inclusive to next07:00 exclusive UTC+08:00','period':'2026-11-06 to 2026-11-15 night starts','nominal':5240,'expected_per_night':480,'raw_and_native_masks_identical':True,'sources':checks,
        'xj_policy':'Absolute1px is descriptive only after user accepts common-trend XJ motion. No new pass label or threshold assigned from coherence.',
        'common_method':'Per-marker median of first30 minutes (>=24/30 valid) subtracted once for display only; ordinary peers exclude all J/XJ; peer roster frozen per night; frame median needs >=80% of roster and>=3. No per-target gain, regression, time shift or temporal smoothing.',
        'limitations':['Not geometry adjustment; unscaled equal-pixel residual is descriptive.','Changing finite subset inside fixed roster may affect median; support retained.','23:00-23:30 baseline is offline visualization only, not a new causal online correction.','Correlation/direction agreement is observational evidence, not physical truth or a pass rule.']}
    (OUT/'window_xj_verification.json').write_text(json.dumps(jsonout,ensure_ascii=False,indent=2),encoding='utf8')
    print(pd.read_csv(OUT/'window_xj_summary.csv').to_string(index=False))
    print(x[(x.device.isin(['780638327479','780637798298']))&((x.night=='2026-11-09')|(x.night=='2026-11-07'))].to_string(index=False))

if __name__=='__main__':main()
