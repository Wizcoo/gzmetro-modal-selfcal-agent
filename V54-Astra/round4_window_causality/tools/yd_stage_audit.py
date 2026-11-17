"""Read-only stage reconstruction from frozen native ablations; no DLL execution."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import json,struct,hashlib,sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;R2=BASE/'round2_waveform_10n'
REPORT=ROOT/'reports';PLOT=ROOT/'plots'
REPORT.mkdir(parents=True,exist_ok=True);PLOT.mkdir(parents=True,exist_ok=True)
TZ=timezone(timedelta(hours=8));DEV='780639298317';TARGET='YD1102'
PROFILES=['current','current_fade07','no_w3','no_s1','no_s2','modal_only','no_temporal']

def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def iso(ts):return datetime.fromtimestamp(int(ts)/1000,TZ).isoformat(sep=' ',timespec='milliseconds')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):
    with p.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    return np.memmap(p,dtype=[('timestamp','<i8'),('xy','<f8',(2,m))],mode='r',offset=8,shape=(n,))
def error(a,b):
    assert np.array_equal(np.isfinite(a),np.isfinite(b))
    return float(np.nanmax(abs(a-b)))
def w3(ts,raw):
    p=raw.shape[1];count=np.zeros(p,int);buffer=np.zeros((p,3));out=np.empty_like(raw)
    for k,t in enumerate(ts):
        if k and t-ts[k-1]>180000:count[:]=0;buffer[:]=0
        v=raw[k];valid=np.isfinite(v);out[k]=np.nan;count[~valid]=0
        first=valid&(count==0);second=valid&(count==1);third=valid&(count==2);later=valid&(count>=3)
        buffer[first,0]=v[first];out[k,first]=v[first]
        buffer[second,1]=v[second];out[k,second]=.5*(buffer[second,0]+buffer[second,1])
        buffer[third,2]=v[third]
        buffer[later,:2]=buffer[later,1:];buffer[later,2]=v[later]
        take=third|later;a=buffer[take,0];b=buffer[take,1];c=buffer[take,2]
        out[k,take]=np.maximum(np.minimum(a,b),np.minimum(np.maximum(a,b),c));count[valid]=np.minimum(count[valid]+1,3)
    return out
def inverse_s1(ts,y,gate):
    core=y.copy()
    for k in range(1,len(ts)):
        dt=ts[k]-ts[k-1]
        if gate[k]<1 or dt>180000 or dt<0:continue
        ok=np.isfinite(y[k])&np.isfinite(y[k-1]);a=1-np.exp(-dt/60000/1.5)
        core[k,ok]=y[k-1,ok]+(y[k,ok]-y[k-1,ok])/a
    return core
def forward_s1(ts,x,gate):
    out=x.copy()
    for k in range(1,len(ts)):
        dt=ts[k]-ts[k-1]
        if gate[k]<1 or dt>180000 or dt<0:continue
        ok=np.isfinite(x[k])&np.isfinite(out[k-1]);a=1-np.exp(-dt/60000/1.5)
        out[k,ok]=out[k-1,ok]+a*(x[k,ok]-out[k-1,ok])
    return out
def uppermedian(a):
    a=np.asarray(a);a=a[np.isfinite(a)]
    return float(np.sort(a)[len(a)//2]) if len(a) else np.nan
def forward_s2(ts,x,gate):
    out=x.copy();inside=False;night=-1;frames=[];baseline=None;rolling=[]
    common=np.full(len(ts),np.nan);smooth=common.copy();nvalid=np.zeros(len(ts),int)
    for k,t in enumerate(ts):
        if k and t-ts[k-1]>180000:inside=False;night=-1;frames=[];baseline=None;rolling=[]
        if gate[k]<1:inside=False;continue
        nid=(t+8*3600000-12*3600000)//86400000
        if not inside or nid!=night:inside=True;night=nid;frames=[];baseline=None;rolling=[]
        if baseline is None:
            frames.append(x[k].copy())
            if len(frames)>=30:
                a=np.asarray(frames);baseline=np.array([uppermedian(a[:,j]) if np.isfinite(a[:,j]).sum()>=10 else np.nan for j in range(x.shape[1])])
            continue
        d=x[k]-baseline;nvalid[k]=np.isfinite(d).sum()
        if nvalid[k]==0:continue
        common[k]=uppermedian(d);rolling.append(common[k]);rolling=rolling[-15:];smooth[k]=uppermedian(rolling)
        out[k]-=.55*smooth[k]
    return out,common,smooth,nvalid

def stats(name,v,t,mask):
    val=v[mask];tt=t[mask];ok=np.isfinite(val);a=val[ok];times=tt[ok]
    return dict(name=name,n=int(len(a)),minimum=float(a.min()),maximum=float(a.max()),p2p=float(np.ptp(a)),p95p5=float(np.diff(np.quantile(a,[.05,.95]))[0]),
        std=float(a.std()),minimum_time=iso(times[np.argmin(a)]),maximum_time=iso(times[np.argmax(a)]))

def main():
    source=BASE/f'data/right/{DEV}/input.npz'
    with np.load(source) as d:ts=d['timestamp'];names=d['names'];raw=d['x'];cal=d['online_x'];roi=d['roi']
    j=list(names).index(TARGET);native={};configs={};provenance=[]
    for p in PROFILES:
        folder=R2/f'results/{p}/right/{DEV}';d=read(folder/'output.bin');assert np.array_equal(ts,d['timestamp'])
        native[p]=np.asarray(d['xy'][:,0,:]);configs[p]=json.loads((folder/'output.bin.config.json').read_text(encoding='utf8'))
        provenance.append({'profile':p,'sha256':sha(folder/'output.bin'),'config':configs[p]})
    status=pd.read_csv(R2/f'results/current/right/{DEV}/status.csv');assert np.array_equal(ts,status.timestamp)
    for p in ['no_s1','no_s2']:
        st=pd.read_csv(R2/f'results/{p}/right/{DEV}/status.csv')
        assert np.array_equal(status[['timestamp','history_x','modes_x','gate_x']],st[['timestamp','history_x','modes_x','gate_x']])
    gate=status.gate_x.to_numpy();filtered=w3(ts,raw);core=inverse_s1(ts,native['no_s2'],gate)
    s2,common,smooth,support=forward_s2(ts,core,gate)
    check={'s1_forward_from_no_s1_vs_native_current_max_abs':error(forward_s1(ts,native['no_s1'],gate),native['current']),
           's1_inverse_forward_vs_native_no_s2_max_abs':error(forward_s1(ts,core,gate),native['no_s2']),
           's2_forward_from_recovered_core_vs_native_no_s1_max_abs':error(s2,native['no_s1']),
           'full_pipeline_vs_native_current_max_abs':error(forward_s1(ts,s2,gate),native['current'])}
    assert max(check.values())<1e-10,check
    t0=ms('2026-11-06 22:00');end=ms('2026-11-07 08:00');night=(ts>=t0)&(ts<end)
    np.savez_compressed(REPORT/'yd_stage_core.npz',timestamp=ts[night],names=names,core_x=core[night],w3_x=filtered[night],raw_x=raw[night],post_s2_x=s2[night],current_x=native['current'][night],gate=gate[night])
    values={'raw':raw[:,j],'database_calX':cal[:,j],'W3_input':filtered[:,j],'same_history_modal_core':core[:,j],'same_history_after_S2':s2[:,j],**{p:a[:,j] for p,a in native.items()}}
    windows={'22_08':night,'23_07':(ts>=ms('2026-11-06 23:00'))&(ts<ms('2026-11-07 07:00')),'2320_07':(ts>=ms('2026-11-06 23:20'))&(ts<ms('2026-11-07 07:00'))}
    metrics=[]
    for window,mask in windows.items():
        for name,v in values.items():metrics.append({'window':window,**stats(name,v,ts,mask)})
    pd.DataFrame(metrics).to_csv(REPORT/'yd_stage_metrics.csv',index=False,encoding='utf-8-sig')
    df=pd.DataFrame({'timestamp':ts[night],'time':[iso(t) for t in ts[night]],'gate':gate[night],'history':status.history_x.to_numpy()[night],
        'valid_input_count':np.isfinite(raw[night]).sum(axis=1),'roi_target':roi[night,j],**{name:v[night] for name,v in values.items()},
        'delta_W3':(filtered-raw)[night,j],'delta_modal':(core-filtered)[night,j],'delta_S2':(s2-core)[night,j],
        'delta_S1':(native['current']-s2)[night,j],'S2_common':common[night],'S2_rolling_upper_median':smooth[night],'S2_valid_points':support[night]})
    assert np.nanmax(abs(df.current-(df.raw+df.delta_W3+df.delta_modal+df.delta_S2+df.delta_S1)))<1e-12
    df.to_csv(REPORT/'yd_stage_trace.csv',index=False,encoding='utf-8-sig')
    # Time blocks describe persistent component contribution, not a new acceptance rule.
    blocks=[]
    for col in ['delta_modal','delta_S2','delta_S1']:
        active=windows['23_07'][night]&np.isfinite(df[col])&(abs(df[col])>=.25)
        starts=np.flatnonzero(active&~np.r_[False,active[:-1]]);ends=np.flatnonzero(active&~np.r_[active[1:],False])
        for start,stop in zip(starts,ends):
            block=df.iloc[start:stop+1]
            blocks.append({'component':col,'start':block.time.iloc[0],'end':block.time.iloc[-1],'frames':len(block),'median_delta':float(block[col].median()),'maximum_abs_delta':float(abs(block[col]).max()),'threshold_for_diagnostic_only':.25})
    pd.DataFrame(blocks).to_csv(REPORT/'yd_stage_persistent_component_blocks.csv',index=False,encoding='utf-8-sig')
    eventrows=[]
    for window,mask in windows.items():
        a=df[mask[night]]
        for col in ['raw','same_history_modal_core','same_history_after_S2','current','delta_modal','delta_S2','delta_S1']:
            for kind,i in [('min',a[col].idxmin()),('max',a[col].idxmax())]:
                row=df.loc[i].to_dict();eventrows.append({'window':window,'extreme_of':col,'kind':kind,**row})
    pd.DataFrame(eventrows).to_csv(REPORT/'yd_stage_extreme_decomposition.csv',index=False,encoding='utf-8-sig')
    out={'target':TARGET,'device':DEV,'night':'2026-11-06','native_executed':False,'method':'invert S1 from native no_s2; apply source-exact S2/S1; compare all 19250 frames x 51 markers',
        'frames':len(ts),'markers':len(names),'reconstruction_checks':check,'source_input_sha256':sha(source),'native_sources':provenance,
        'profile_semantics':{'modal_only':'W3 off, S2 off, S1 off; independent raw-fed history, NOT same-history current core','no_temporal':'W3 off, S1 off, S2 on','no_w3':'W3 off, S2 on, S1 on','no_s1':'W3 on, S2 on, S1 off','no_s2':'W3 on, S2 off, S1 on'},
        'metrics':metrics,'note':'Component additions exactly sum pointwise; range and percentile spans are not additive. Different W3 profiles include different historical learning.'}
    (REPORT/'yd_stage_verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'checks':check,'23_07':[m for m in metrics if m['window']=='23_07']},ensure_ascii=True),flush=True)

if __name__=='__main__':main()
