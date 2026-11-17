"""Explain one frozen native night using independently reconstructed modal algebra.
Not an algorithm candidate: exact-output comparison is required before attribution.
"""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import sys,json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;R2=BASE/'round2_waveform_10n'
sys.path.insert(0,str(BASE/'round3_physics_failure/tools'))
from failure_audit import read,ms,span
OUT=ROOT/'reports';OUT.mkdir(parents=True,exist_ok=True)
TZ=timezone(timedelta(hours=8));DEVICE='780639298317';TARGET='YD1102';NIGHT='2026-11-06'

def w3(t,x):
    out=np.full_like(x,np.nan);buf=np.full((3,x.shape[1]),np.nan);count=np.zeros(x.shape[1],int)
    for k,row in enumerate(x):
        if k and t[k]-t[k-1]>180000:count[:]=0
        valid=np.isfinite(row);count[~valid]=0
        for j in np.flatnonzero(valid):
            if count[j]==0:buf[0,j]=row[j];count[j]=1;out[k,j]=row[j]
            elif count[j]==1:buf[1,j]=row[j];count[j]=2;out[k,j]=(buf[0,j]+buf[1,j])*.5
            elif count[j]==2:buf[2,j]=row[j];count[j]=3;out[k,j]=np.median(buf[:,j])
            else:buf[:,j]=[buf[1,j],buf[2,j],row[j]];out[k,j]=np.median(buf[:,j])
    return out

def night_data(t,x,night):
    start=ms(night+' 22:00');ref=(t>=start)&(t<start+3600000);learn=(t>=start)&(t<start+4*3600000)
    b=np.nanmean(x[ref],axis=0);b[np.isfinite(x[ref]).sum(axis=0)<10]=np.nan
    z=x[learn]-b;ok=np.isfinite(z);a=np.where(ok,z,0);s=a.T@a;n=ok.astype(float).T@ok.astype(float)
    return dict(night=night,b=b,ref=x[ref],S=s,N=n,n_frames=int(np.count_nonzero(ok.any(axis=1))))

def model(t,x,names):
    hist=[night_data(t,x,f'2026-11-{d:02d}') for d in [3,4,5]]
    s=sum(h['S'] for h in hist);n=sum(h['N'] for h in hist);nf=sum(h['n_frames'] for h in hist)
    c=np.divide(s,n,out=np.zeros_like(s),where=n>1);u=np.diag(n)>=.8*nf
    base=u&np.array([not name.startswith(('YJ','ZJ')) for name in names]);sd=np.sqrt(np.maximum(np.diag(c),0))
    learn=base&(sd<=3*np.median(sd[base]))
    if learn.sum()<5:learn=base.copy()
    while True:
        L=np.flatnonzero(learn);eig,v=np.linalg.eigh(c[np.ix_(L,L)]);eig=eig[::-1];v=v[:,::-1]
        bad=np.any(v[:,:3]**2>.5,axis=1)
        if not bad.any() or len(L)-bad.sum()<5:break
        learn[L[bad]]=False
    # Native diagnostic establishes all 51 rows learned for this device/night.
    assert u.all() and learn.all() and len(names)==51
    A=v[:,:3];assert eig[2]>1e-12*eig[0]
    tonight=night_data(t,x,NIGHT)
    return A,tonight,c,hist,eig

def solve(z,A,exclude=()):
    active=np.isfinite(z);active[list(exclude)]=False
    if active.sum()<5:return None
    first=active.copy();v=np.linalg.solve(A[active].T@A[active],A[active].T@z[active])
    drop=active&(np.abs(np.nan_to_num(z)-A@v)>2.5)
    if drop.any():
        active[drop]=False
        if active.sum()<5:return None
        v=np.linalg.solve(A[active].T@A[active],A[active].T@z[active])
    return v,active,drop

def evaluate(t,x,A,tonight,target,exclude=(),with_contributions=False):
    b=tonight['b'];ref=tonight['ref'];cbar=np.zeros(x.shape[1]);count=np.zeros(x.shape[1]);refcon=np.zeros(x.shape[1]);refcount=0
    for row in ref:
        z=row-b;s=solve(z,A,exclude)
        if s is None:continue
        v,active,_=s;ok=np.isfinite(z);cbar[ok]+=(A@v)[ok];count[ok]+=1
        if with_contributions and ok[target]:
            weights=A[target]@np.linalg.solve(A[active].T@A[active],A[active].T)
            refcon[active]+=weights*z[active];refcount+=1
    cbar=np.divide(cbar,count,out=np.zeros_like(cbar),where=count>0)
    start=ms(NIGHT+' 22:00');sel=(t>=start)&(t<start+10*3600000);st=t[sel];fed=x[sel]
    core=fed.copy();con=np.zeros_like(fed);removed=np.zeros_like(fed,bool);support=np.zeros(len(st),int)
    for k,row in enumerate(fed):
        h=(st[k]-start)/3600000+22;gate=min(1,max(0,(h-23)/(1/3))) if h<31 else max(0,1-(h-31)/(1/3))
        if gate<=0:continue
        z=row-b;s=solve(z,A,exclude)
        if s is None:continue
        v,active,drop=s;valid=np.isfinite(z);core[k,valid]-=gate*((A@v-cbar)[valid]);removed[k]=drop;support[k]=active.sum()
        if with_contributions:
            weights=A[target]@np.linalg.solve(A[active].T@A[active],A[active].T)
            con[k,active]=weights*z[active]
            con[k]=(con[k]-refcon/max(1,refcount))*gate
    return dict(timestamp=st,fed=fed,core=core,contributions=con,removed=removed,support=support,cbar=cbar)

def stats(v):
    v=v[np.isfinite(v)];return {'range':float(np.ptp(v)),'p95p5':float(np.diff(np.quantile(v,[.05,.95]))[0]),'variance':float(np.var(v))}

def main():
    with np.load(BASE/f'data/right/{DEVICE}/input.npz') as d:t=d['timestamp'];raw=d['x'];names=d['names']
    j=list(names).index(TARGET);fed=w3(t,raw);a,tonight,c,hist,eig=model(t,fed,names);replay=evaluate(t,fed,a,tonight,j,with_contributions=True)
    # Independent unfiltered construction can be checked directly against native modal_only.
    ar,tr,cr,hr,er=model(t,raw,names);plain=evaluate(t,raw,ar,tr,j)
    n=read(R2/f'results/modal_only/right/{DEVICE}/output.bin');sel=(t>=ms(NIGHT+' 22:00'))&(t<ms('2026-11-07 08:00'))
    error=float(np.nanmax(abs(plain['core']-n['xy'][sel,0])))
    assert error<1e-8, error
    independent=np.load(OUT/'yd_stage_core.npz')
    assert np.array_equal(independent['timestamp'],replay['timestamp'])
    w3_error=float(np.nanmax(abs(independent['core_x']-replay['core'])))
    assert w3_error<1e-8,w3_error
    st=replay['timestamp'];mask=(st>=ms(NIGHT+' 23:20'))&(st<ms('2026-11-07 07:00'))
    newwindow=(st>=ms(NIGHT+' 23:00'))&(st<ms('2026-11-07 07:00'))
    target_fed=replay['fed'][:,j];core=replay['core'][:,j];corr=target_fed-core
    assert np.nanmax(abs(replay['contributions'].sum(axis=1)-corr))<1e-9
    rows=[]
    for k,name in enumerate(names):
        cc=replay['contributions'][:,k]
        rows.append({'marker':str(name),'loading_squared':float(np.sum(a[k]**2)),'target_projection_weight':float(a[j]@a[k]),'fed_range':span(replay['fed'][mask,k]),'contribution_std':float(np.std(cc[mask])),'contribution_p95p5':stats(cc[mask])['p95p5'],'rejected_frames':int(replay['removed'][mask,k].sum())})
    ranked=pd.DataFrame(rows).sort_values('contribution_std',ascending=False)
    ranked.to_csv(OUT/'yd_influence_contributors.csv',index=False,encoding='utf-8-sig')
    loo=[]
    for k,name in enumerate(names):
        other=evaluate(t,fed,a,tonight,j,exclude=[k])['core'][:,j]
        loo.append({'removed_donor':str(name),**stats(other[mask]),'max_core_change':float(np.nanmax(abs(other[mask]-core[mask]))),'rms_core_change':float(np.sqrt(np.nanmean((other[mask]-core[mask])**2)))})
    pd.DataFrame(loo).sort_values('rms_core_change',ascending=False).to_csv(OUT/'yd_influence_leave_one.csv',index=False,encoding='utf-8-sig')
    largest=list(ranked.sort_values('fed_range',ascending=False).marker)
    groups=[]
    for count in [1,3,5]:
        ids=[list(names).index(v) for v in largest[:count]]
        other=evaluate(t,fed,a,tonight,j,exclude=ids)['core'][:,j]
        groups.append({'removed_largest_amplitude_donors':largest[:count],**stats(other[mask]),'rms_core_change':float(np.sqrt(np.nanmean((other[mask]-core[mask])**2)))})
    xf=target_fed[mask];cf=corr[mask];ok=np.isfinite(xf)&np.isfinite(cf);xf=xf[ok];cf=cf[ok]
    varx=float(np.var(xf));varc=float(np.var(cf));cov=float(np.mean((xf-xf.mean())*(cf-cf.mean())))
    perhist=[]
    beta=a@a[j]
    for h in hist:
        C=np.divide(h['S'],h['N'],out=np.zeros_like(c),where=h['N']>1);pred=float(beta@C@beta);cross=float(C[j]@beta);observed=float(C[j,j])
        perhist.append({'night':h['night'],'frames':h['n_frames'],'raw_energy':observed,'predicted_energy':pred,'cross_energy':cross,'residual_energy':observed+pred-2*cross,'q':cross/pred})
    np.savez_compressed(OUT/'yd_influence_reconstruction.npz',timestamp=st,names=names,raw=raw[sel],fed=replay['fed'],core=replay['core'],contributions=replay['contributions'],rejected=replay['removed'],A=a,C=c,b=tonight['b'],cbar=replay['cbar'])
    crossed=[]
    crossvalues={}
    for hist_label,model_a in [('raw_history',ar),('w3_history',a)]:
        for input_label,inp,base in [('raw_live',raw,tr),('w3_live',fed,tonight)]:
            vals=evaluate(t,inp,model_a,base,j)['core'][:,j]
            crossed.append({'history':hist_label,'live_input':input_label,'window_23_07':stats(vals[newwindow]),'window_2320_07':stats(vals[mask])})
            crossvalues[hist_label+'_'+input_label]=vals
    pd.DataFrame({'timestamp_ms':st,**crossvalues}).to_csv(OUT/'yd_influence_crossed_history_live.csv',index=False)
    singular=np.linalg.svd(ar.T@a,compute_uv=False)
    report={'scope':'Independent NumPy modal reconstruction; fixed historical model donor interventions, not a deployment candidate or native rerun',
      'target':TARGET,'night':NIGHT,'history_dates':[h['night'] for h in hist],'historical_all_51_learned':True,'unfiltered_all_point_native_max_error':error,
      'w3_core_native_max_error':w3_error,'crossed_history_live_intervention':crossed,'modal_subspace_principal_angles_deg':np.degrees(np.arccos(np.clip(singular,-1,1))).tolist(),
      'target_history_covariance_diagonal':float(c[j,j]),'target_explained_energy':float(np.sum(a[j]**2*eig[:3])),'target_loading_norm':float(np.linalg.norm(a[j])),
      'historical_energy_definition':'raw_energy means W3 historical input second moment about each 22-23 baseline, not unfiltered raw variance; frozen 11/06 model evaluated on prior sufficient statistics',
      'historical_target_energy':perhist,'active_2320_07':{'fed':stats(xf),'core':stats(core[mask]),'raw':stats(raw[sel, j][mask]),'correction':stats(cf),'cov_fed_correction':cov,'variance_identity_lhs':float(np.var(core[mask][np.isfinite(core[mask])])-varx),'variance_identity_rhs':varc-2*cov,'donor_rejections':int(replay['removed'][mask].sum()),'frames_with_rejection':int(replay['removed'][mask].any(axis=1).sum())},
      'largest_donor_interventions':groups,'largest_leave_one_changes':sorted(loo,key=lambda r:-r['rms_core_change'])[:8]}
    (OUT/'yd_influence_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
