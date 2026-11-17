"""Explain frozen 11/12 outputs; no native execution and no algorithm/DB mutation."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from collections import Counter
import ast,hashlib,json,re,struct
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=ROOT/'reports';OUT.mkdir(parents=True,exist_ok=True)
TZ=timezone(timedelta(hours=8));NIGHT='2026-11-12';DEVICES=['780638310097','780638327479','780638349768']
PROFILES=['current','current_fade07','no_s1','no_s2','no_w3','modal_only','no_temporal']
HELPER=BASE/'round4_window_causality/tools/yd_stage_audit.py'
# Reuse the previously native-validated, source-exact stage functions only.
tree=ast.parse(HELPER.read_text(encoding='utf8'));wanted={'w3','inverse_s1','forward_s1','uppermedian','forward_s2','read','error'}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted],type_ignores=[]),str(HELPER),'exec'))
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def iso(t):return datetime.fromtimestamp(int(t)/1000,TZ).isoformat(sep=' ',timespec='milliseconds')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stats(v,t):
    ok=np.isfinite(v);v=v[ok];t=t[ok]
    if not len(v):return {'n':0}
    return {'n':len(v),'range':float(np.ptp(v)),'p95p5':float(np.diff(np.quantile(v,[.05,.95]))[0]),'mean':float(np.mean(v)),'median':float(np.median(v)),
            'minimum':float(v.min()),'maximum':float(v.max()),'minimum_time':iso(t[np.argmin(v)]),'maximum_time':iso(t[np.argmax(v)])}
def night_data(t,x,date):
    start=ms(date+' 22:00');ref=(t>=start)&(t<start+3600000);learn=(t>=start)&(t<start+4*3600000)
    ref_counts=np.isfinite(x[ref]).sum(axis=0);b=np.nanmean(x[ref],axis=0);b[ref_counts<10]=np.nan
    z=x[learn]-b;ok=np.isfinite(z);a=np.where(ok,z,0);n=ok.astype(float).T@ok.astype(float)
    return {'date':date,'b':b,'ref':x[ref],'ref_counts':ref_counts,'S':a.T@a,'N':n,'n_frames':int(ok.any(axis=1).sum())}
def gain_logs(dev,profile):
    p=BASE/'round2_waveform_10n/results'/profile/'left'/dev/'replay.log';nid=20769;rows={}
    for line in p.read_text(encoding='utf8').splitlines():
        if line.startswith(f'REG_ENERGY,{nid},'):
            z=line.split(',');rows[z[2]]={'support':int(z[3]),'minimum_q':float(z[4]),'gain':float(z[5]),'reason':z[6],'covered':int(z[7]),'invalid':int(z[8]),'uninformative':int(z[9]),'minimum_supported_coverage':float(z[10]),'log_line':line}
    return rows
def model(t,x,names,logs):
    hist=[night_data(t,x,f'2026-11-{d:02d}') for d in [9,10,11]]
    S=sum(h['S'] for h in hist);N=sum(h['N'] for h in hist);nf=sum(h['n_frames'] for h in hist)
    C=np.divide(S,N,out=np.zeros_like(S),where=N>1);use=np.diag(N)>=.8*nf;fit=np.array([n.startswith(('YJ','ZJ')) for n in names]);base=use&~fit
    sd=np.sqrt(np.maximum(np.diag(C),0));limit=3*np.median(sd[base]);learn=base&(sd<=limit);spread_drop=base&~learn
    if learn.sum()<5:learn=base.copy();spread_drop[:]=False
    guard_drop=np.zeros(len(names),bool)
    while True:
        L=np.flatnonzero(learn);w,V=np.linalg.eigh(C[np.ix_(L,L)]);w=w[::-1];V=V[:,::-1];bad=(V[:,:3]**2>.5).any(axis=1)
        if not bad.any() or len(L)-bad.sum()<5:break
        guard_drop[L[bad]]=True;learn[L[bad]]=False
    A=np.full((len(names),3),np.nan);A[L]=V[:,:3]
    for i in np.flatnonzero(use&~learn):A[i]=(C[i,L]@V[:,:3])/w[:3]
    for i in np.flatnonzero(use&~learn&~fit):
        assert names[i] in logs,('missing native gain log',names[i]);A[i]*=logs[names[i]]['gain']
    return {'A':A,'C':C,'use':use,'learn':learn,'fit_only':fit,'spread_drop':spread_drop,'guard_drop':guard_drop,'sd':sd,'spread_limit':limit,'eigenvalues':w,'hist':hist,'nf':nf,'coverage':np.diag(N)/nf}
def solve(z,model,exclude=()):
    A=model['A'];active=np.isfinite(z)&model['learn'];active[list(exclude)]=False
    if active.sum()<5:return None
    v=np.linalg.solve(A[active].T@A[active],A[active].T@z[active]);drop=active&(np.abs(np.nan_to_num(z)-np.nan_to_num(A@v))>2.5)
    if drop.any():
        active[drop]=False
        if active.sum()<5:return None
        v=np.linalg.solve(A[active].T@A[active],A[active].T@z[active])
    return v,active,drop
def evaluate(t,x,model,date=NIGHT,exclude=(),contribution_target=None):
    baseline=night_data(t,x,date);b=baseline['b'];A=model['A'];p=len(b);cbar=np.zeros(p);count=np.zeros(p);donor_ref=np.zeros(p);donor_count=0
    for row in baseline['ref']:
        z=row-b;s=solve(z,model,exclude)
        if s is None:continue
        v,active,_=s;ok=np.isfinite(z)&model['use'];cbar[ok]+=(A@v)[ok];count[ok]+=1
        if contribution_target is not None and ok[contribution_target]:
            weights=A[contribution_target]@np.linalg.solve(A[active].T@A[active],A[active].T)
            donor_ref[active]+=weights*z[active];donor_count+=1
    cbar=np.divide(cbar,count,out=np.zeros_like(cbar),where=count>0)
    lo=ms(date+' 22:00');sel=(t>=lo)&(t<lo+36000000);tt=t[sel];fed=x[sel];core=fed.copy();contrib=np.zeros_like(fed);drop=np.zeros_like(fed,bool);support=np.zeros(len(tt),int);prediction=np.full_like(fed,np.nan)
    for k,row in enumerate(fed):
        h=(tt[k]-lo)/3600000+22;gate=min(1,max(0,(h-23)*3)) if h<31 else max(0,1-(h-31)*3)
        if gate<=0:continue
        z=row-b;s=solve(z,model,exclude)
        if s is None:continue
        v,active,removed=s;valid=np.isfinite(z)&model['use'];pred=A@v-cbar;core[k,valid]-=gate*pred[valid];prediction[k,valid]=gate*pred[valid];drop[k]=removed;support[k]=active.sum()
        if contribution_target is not None:
            weights=A[contribution_target]@np.linalg.solve(A[active].T@A[active],A[active].T)
            contrib[k,active]=weights*z[active];contrib[k]=(contrib[k]-donor_ref/max(1,donor_count))*gate
    return {'t':tt,'fed':fed,'core':core,'prediction':prediction,'b':b,'cbar':cbar,'baseline':baseline,'drop':drop,'support':support,'contributions':contrib,'sel':sel}
def offsets(v,t,rawbaseline):
    ref=(t>=ms(NIGHT+' 22:00'))&(t<ms(NIGHT+' 23:00'));late=(t>=ms('2026-11-13 03:00'))&(t<ms('2026-11-13 06:00'))
    return {'own_baseline_median':float(np.nanmedian(v[ref])),'late_median':float(np.nanmedian(v[late])),
            'late_minus_own_baseline_median':float(np.nanmedian(v[late])-np.nanmedian(v[ref])),
            'late_minus_raw_baseline_median':float(np.nanmedian(v[late])-rawbaseline),
            'late_minus_own_baseline_mean':float(np.nanmean(v[late])-np.nanmean(v[ref]))}
def main():
    devices=[];points=[];trace=[];provenance=[]
    for dev in DEVICES:
        source=BASE/'data/left'/dev/'input.npz'
        with np.load(source) as d:t=d['timestamp'];names=list(map(str,d['names']));raw=d['x'];cal=d['online_x']
        native={};configs={}
        for profile in PROFILES:
            directory=BASE/'round2_waveform_10n/results'/profile/'left'/dev;rec=read(directory/'output.bin');assert np.array_equal(t,rec['timestamp']);native[profile]=rec['xy'][:,0,:]
            configs[profile]=json.loads((directory/'output.bin.config.json').read_text(encoding='utf8'));provenance.append({'device':dev,'profile':profile,'output_sha256':sha(directory/'output.bin'),'config':configs[profile]})
        status=pd.read_csv(BASE/'round2_waveform_10n/results/current/left'/dev/'status.csv');gate=status.gate_x.to_numpy();assert np.array_equal(t,status.timestamp)
        fed=w3(t,raw);core=inverse_s1(t,native['no_s2'],gate);post,common,smooth,s2support=forward_s2(t,core,gate)
        checks={'forward_S2_vs_no_s1':error(post,native['no_s1']),'forward_S1_vs_current':error(forward_s1(t,post,gate),native['current']),'inverse_forward_S1_vs_no_s2':error(forward_s1(t,core,gate),native['no_s2'])};assert max(checks.values())<1e-10,checks
        stage_window=(t>=ms(NIGHT+' 22:00'))&(t<ms('2026-11-13 07:00'))
        stage_path=OUT/f'algorithm_cause_audit_stage_{dev}.npz'
        np.savez_compressed(stage_path,timestamp=t[stage_window],names=names,raw=raw[stage_window],w3=fed[stage_window],modal=core[stage_window],s2=post[stage_window],new=native['current_fade07'][stage_window],calX=cal[stage_window],gate=gate[stage_window])
        print('STAGES_READY',dev,str(stage_path),'SHA256',sha(stage_path),'CHECKS',checks,flush=True)
        logs=gain_logs(dev,'current_fade07');model_w3=model(t,fed,names,logs);model_raw=model(t,raw,names,gain_logs(dev,'modal_only'))
        xj=names.index('ZXJ6') if dev=='780638327479' else None
        reconstructed=evaluate(t,fed,model_w3,contribution_target=xj);plain=evaluate(t,raw,model_raw)
        sel=reconstructed['sel'];tt=t[sel];nw=(tt>=ms(NIGHT+' 23:00'))&(tt<ms('2026-11-13 07:00'));full=(tt>=ms(NIGHT+' 23:20'))&(tt<ms('2026-11-13 07:00'));late=(tt>=ms('2026-11-13 03:00'))&(tt<ms('2026-11-13 06:00'));base=(tt<ms(NIGHT+' 23:00'))
        checks['independent_W3_modal_vs_recovered_core']=error(reconstructed['core'],core[sel]);checks['independent_raw_modal_vs_native_modal_only']=error(plain['core'],native['modal_only'][sel]);assert max(checks.values())<1e-8,checks
        phase=(t>=ms(NIGHT+' 23:00'))&(t<ms('2026-11-13 07:00'));assert error(native['current'][phase],native['current_fade07'][phase])==0
        values={'raw':raw[sel],'database_calX':cal[sel],'W3_input':fed[sel],'same_history_modal_core':core[sel],'post_S2':post[sel],**{p:a[sel] for p,a in native.items()}}
        device={'device':dev,'markers':len(names),'input_sha256':sha(source),'stage_reconstruction_checks':checks,'status_counts':status.loc[phase,'state_x'].value_counts().to_dict(),
                'history_x_values':sorted(map(int,status.loc[phase,'history_x'].unique())),'modes_x_values':sorted(map(int,status.loc[phase,'modes_x'].unique())),
                'learn_names':[n for i,n in enumerate(names) if model_w3['learn'][i]],'regression_nonlearn_logs':logs,
                'historical_learning_dates':['2026-11-09','2026-11-10','2026-11-11'],'historical_learning_window':'[22:00,next02:00); each reference [22:00,23:00)',
                'historical_frames':[h['n_frames'] for h in model_w3['hist']],'pooled_learning_frames':model_w3['nf'],
                'night_frames_with_solver_rejection':int(reconstructed['drop'][nw].any(axis=1).sum()),'solver_rejected_point_frames':int(reconstructed['drop'][nw].sum()),
                'S2_late_median_addition':float(np.nanmedian(post[sel][late]-core[sel][late])),
                'S2_late_common_median':float(np.nanmedian(common[sel][late])),'S2_late_smoothed_median':float(np.nanmedian(smooth[sel][late]))}
        targets=[i for i,n in enumerate(names) if re.match(r'ZD(42|43|44|45|46|47)\d+$',n) or 'J' in n]
        fixed_hist=[evaluate(t,fed,model_w3,date=f'2026-11-{day:02d}') for day in [9,10,11]]
        for j in targets:
            name=names[j];rawbase=float(np.nanmedian(raw[sel][base,j]));metrics={p:{'23_07':stats(a[nw,j],tt[nw]),'2320_07':stats(a[full,j],tt[full]),'offsets':offsets(a[:,j],tt,rawbase)} for p,a in values.items()}
            identity={'use':bool(model_w3['use'][j]),'learn':bool(model_w3['learn'][j]),'fit_only':bool(model_w3['fit_only'][j]),'excluded_by_spread':bool(model_w3['spread_drop'][j]),'excluded_by_guard':bool(model_w3['guard_drop'][j]),'history_valid_fraction':float(model_w3['coverage'][j]),'baseline_finite_count':int(reconstructed['baseline']['ref_counts'][j]),'historical_sd':float(model_w3['sd'][j]),'spread_cutoff':float(model_w3['spread_limit']),'native_regression_gain_log':logs.get(name),'solver_rejections_this_point':int(reconstructed['drop'][nw,j].sum())}
            pred=reconstructed['prediction'][:,j];z=reconstructed['fed'][:,j]-reconstructed['b'][j]
            energy={}
            for label,mask in [('learning_hours_23_02',(tt>=ms(NIGHT+' 23:20'))&(tt<ms('2026-11-13 02:00'))),('late_03_06',late)]:
                ok=mask&np.isfinite(z)&np.isfinite(pred);obs=float(np.mean(z[ok]**2));pp=float(np.mean(pred[ok]**2));cross=float(np.mean(z[ok]*pred[ok]));energy[label]={'observed_second_moment':obs,'predicted_second_moment':pp,'cross_second_moment':cross,'q_current':cross/pp if pp else None,'residual_second_moment':float(np.mean((z[ok]-pred[ok])**2)),'observed_mean':float(np.mean(z[ok])),'predicted_mean':float(np.mean(pred[ok])),'residual_mean':float(np.mean(z[ok]-pred[ok]))}
            hist_pattern=[]
            for h in fixed_hist:
                ht=h['t'];start=ht[0]//86400000;date=iso(ht[0])[:10];histlate=(ht>=ms(date+' 22:00')+5*3600000)&(ht<ms(date+' 22:00')+8*3600000);histlearn=(ht>=ms(date+' 22:00'))&(ht<ms(date+' 22:00')+4*3600000)
                for phase_name,mask in [('history_22_02',histlearn),('history_03_06',histlate)]:
                    obs=h['fed'][:,j]-h['b'][j];res=h['core'][:,j]-h['b'][j];hist_pattern.append({'date':date,'phase':phase_name,'observed_mean':float(np.nanmean(obs[mask])),'residual_mean':float(np.nanmean(res[mask])),'residual_p95p5':float(np.diff(np.nanquantile(res[mask],[.05,.95]))[0]),'meaning':'Current11/12 fixed model applied diagnostically to history; not that night native deployed model'})
            point={'device':dev,'marker':name,'section_target':bool(re.match(r'ZD(42|43|44|45|46|47)\d+$',name)),'identity':identity,'metrics':metrics,'current_energy':energy,'fixed_model_history_patterns':hist_pattern,'old_calX_vs_modal_only_max_abs':float(np.nanmax(abs(cal[sel,j][nw]-native['modal_only'][sel,j][nw])))}
            points.append(point)
            for k in np.flatnonzero(nw):trace.append({'device':dev,'marker':name,'timestamp':int(tt[k]),'time':iso(tt[k]),'gate':float(gate[sel][k]),**{p:float(a[k,j]) for p,a in values.items()},'delta_W3':float(fed[sel][k,j]-raw[sel][k,j]),'delta_modal':float(core[sel][k,j]-fed[sel][k,j]),'delta_S2':float(post[sel][k,j]-core[sel][k,j]),'delta_S1':float(native['current'][sel][k,j]-post[sel][k,j])})
        if xj is not None:
            con=reconstructed['contributions'];assert np.nanmax(abs(con.sum(axis=1)[nw]-reconstructed['prediction'][nw,xj]))<1e-8
            donors=sorted([{'name':n,'late_mean_contribution':float(np.mean(con[late,j])),'night_contribution_std':float(np.std(con[nw,j]))} for j,n in enumerate(names) if model_w3['learn'][j]],key=lambda r:-abs(r['late_mean_contribution']))
            device['ZXJ6_top_donors']=donors[:10];device['ZXJ6_live_donor_interventions']=[]
            for donor in donors[:5]:
                other=evaluate(t,fed,model_w3,exclude=[names.index(donor['name'])]);baseline=float(np.nanmedian(raw[sel][base,xj]));device['ZXJ6_live_donor_interventions'].append({'removed_donor':donor['name'],'late_core_minus_raw_baseline':float(np.nanmedian(other['core'][late,xj])-baseline),'core_change_max':float(np.nanmax(abs(other['core'][nw,xj]-reconstructed['core'][nw,xj]))),'scope':'Fixed historical model; donor removed from live and baseline SolveV only'})
        devices.append(device);print('DEVICE_DONE',dev,'checks',checks,'target_count',len(targets),flush=True)
    result={'scope':'Frozen native outputs plus validated stage inversion and independent NumPy modal reconstruction; no new DLL execution, no model or DB changes','user_physical_evidence':'User reports external total-station instrument found device disturbance, not true target displacement. Instrument records not independently supplied/verified in this audit.',
            'night':NIGHT,'target_window':'[23:00,next07:00)','baseline_window':'[22:00,23:00)','late_window':'[next03:00,next06:00)','unit':'pixel','stage_helper_sha256':sha(HELPER),'script_sha256':sha(Path(__file__)),
            'devices':devices,'points':points,'native_provenance':provenance,
            'limits':['Different W3 profiles use different independently learned histories; profile subtraction is not a single-stage contribution.','Range and median differences are not additive. Stage traces are pointwise additive.','No data-driven result alone proves physical displacement or absence of device disturbance.','Historical 3-night training uses only22–02; use/learn flags and gain do not enforce final output flatness or point-specific physical correctness.']}
    (OUT/'algorithm_cause_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    pd.DataFrame(trace).to_csv(OUT/'algorithm_cause_audit.trace.csv',encoding='utf-8-sig',index=False)
    flat=[]
    for p in points:
        for variant,v in p['metrics'].items():flat.append({'device':p['device'],'marker':p['marker'],'variant':variant,**v['23_07'],**v['offsets']})
    pd.DataFrame(flat).to_csv(OUT/'algorithm_cause_audit.metrics.csv',encoding='utf-8-sig',index=False)
    print('AUDIT_READY',len(points),'points',len(trace),'trace_rows',flush=True)
if __name__=='__main__':main()
