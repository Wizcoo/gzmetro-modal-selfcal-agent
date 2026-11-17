"""One held-out night, one device: historical-window modal sensitivity only.

No native binary is executed. The enlarged-history energy gains are recomputed
from the source equation, never copied from the old replay logs.
"""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import ast,hashlib,json,re
import numpy as np

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=ROOT/'reports';OUT.mkdir(parents=True,exist_ok=True)
TZ=timezone(timedelta(hours=8));NIGHT='2026-11-12';DEV='780638327479'
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def iso(t):return datetime.fromtimestamp(int(t)/1000,TZ).isoformat(sep=' ',timespec='milliseconds')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

R9=BASE/'round9_left_42_47_1112'
HELPERS=[(BASE/'round4_window_causality/tools/yd_stage_audit.py',{'w3'}),
         (R9/'tools/algorithm_cause_audit.py',{'night_data','solve','evaluate'})]
for path,wanted in HELPERS:
    tree=ast.parse(path.read_text(encoding='utf8'))
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted],type_ignores=[]),str(path),'exec'))

def history_stat(t,x,date,hours):
    lo=ms(date+' 22:00');ref=(t>=lo)&(t<lo+3600000);learn=(t>=lo)&(t<lo+hours*3600000)
    count=np.isfinite(x[ref]).sum(axis=0);b=np.nanmean(x[ref],axis=0);b[count<10]=np.nan
    z=x[learn]-b;valid=np.isfinite(z);v=np.where(valid,z,0)
    return {'date':date,'start_ms':lo,'end_exclusive_ms':lo+hours*3600000,'S':v.T@v,'N':valid.astype(float).T@valid.astype(float),'n_frames':int(valid.any(axis=1).sum()),'baseline':b}

def make_model(t,x,names,hours):
    hist=[history_stat(t,x,f'2026-11-{d:02d}',hours) for d in [9,10,11]]
    S=sum(h['S'] for h in hist);N=sum(h['N'] for h in hist);nf=sum(h['n_frames'] for h in hist)
    C=np.divide(S,N,out=np.zeros_like(S),where=N>1);use=np.diag(N)>=.8*nf
    fit=np.asarray([n.startswith(('YJ','ZJ')) for n in names]);base=use&~fit
    rms=np.sqrt(np.maximum(np.diag(C),0));threshold=3*np.median(rms[base]);learn=base&(rms<=threshold);spread=base&~learn
    if learn.sum()<5:learn=base.copy();spread[:]=False
    guard=np.zeros(len(names),bool)
    for _ in range(1000):
        L=np.flatnonzero(learn);e,V=np.linalg.eigh(C[np.ix_(L,L)]);e=e[::-1];V=V[:,::-1]
        bad=(V[:,:3]**2>.5).any(axis=1)
        if not bad.any() or len(L)-bad.sum()<5:break
        guard[L[bad]]=True;learn[L[bad]]=False
    assert len(L)>=5 and e[2]>1e-12*max(e[0],1e-300)
    A=np.full((len(names),3),np.nan);A[L]=V[:,:3]
    for i in np.flatnonzero(use&~learn):A[i]=(C[i,L]@V[:,:3])/e[:3]
    gains=np.ones(len(names));gain_detail={}
    for i in np.flatnonzero(use&~learn&~fit):
        beta=V[:,:3]@A[i];ids=np.flatnonzero(beta!=0);active_names=L[ids];bb=beta[ids]
        minimum_q=float('inf');support=covered=invalid=uninformative=0;records=[]
        for h in hist:
            H=np.divide(h['S'],h['N'],out=np.full_like(h['S'],np.nan),where=h['N']>1)
            # Source covariance() checks target self, target/donor, and every
            # nonzero-beta donor pair. All point names are identical in this audit.
            counts=np.r_[h['N'][i,i],h['N'][i,active_names],h['N'][np.ix_(active_names,active_names)].ravel()]
            coverage=float(np.min(counts)/h['n_frames'])
            observed=float(H[i,i]);cross=float(H[i,active_names]@bb);predicted=float(bb@H[np.ix_(active_names,active_names)]@bb)
            rec={'date':h['date'],'coverage':coverage,'observed':observed,'cross':cross,'predicted':predicted,'q':None,'supported':False}
            if coverage>=.8:
                covered+=1
                if not np.isfinite([observed,cross,predicted]).all():invalid+=1
                else:
                    tolerance=1e-12*max(1,abs(observed),abs(cross),abs(predicted))
                    if predicted < -tolerance:invalid+=1
                    elif predicted<=tolerance:
                        if abs(cross)<=tolerance:uninformative+=1
                        else:invalid+=1
                    else:
                        q=cross/predicted
                        if not np.isfinite(q):invalid+=1
                        else:minimum_q=min(minimum_q,q);support+=1;rec.update(q=q,supported=True)
            records.append(rec)
        gain=float(np.clip(2*minimum_q,0,1)) if support>0 and invalid==0 else 0.0
        A[i]*=gain;gains[i]=gain
        gain_detail[names[i]]={'gain':gain,'minimum_q':minimum_q if np.isfinite(minimum_q) else None,'support':support,'covered':covered,'invalid':invalid,'uninformative':uninformative,'by_night':records}
    return {'A':A,'use':use,'learn':learn,'fit_only':fit,'hist':hist,'gains':gains,'gain_detail':gain_detail,'rms':rms,'spread_cutoff':threshold,'spread_drop':spread,'guard_drop':guard,'C':C,'nf':nf,'eigenvalues':e}

def metric(v,t,raw):
    baseline=t<ms(NIGHT+' 23:00');night=(t>=ms(NIGHT+' 23:00'))&(t<ms('2026-11-13 07:00'));late=(t>=ms('2026-11-13 03:00'))&(t<ms('2026-11-13 06:00'))
    def stats(mask):
        a=v[mask];tt=t[mask];valid=np.isfinite(a);a=a[valid];tt=tt[valid]
        return {'count':len(a),'range':float(np.ptp(a)),'p95p5':float(np.diff(np.quantile(a,[.05,.95]))[0]),'min':float(a.min()),'max':float(a.max()),'min_time':iso(tt[np.argmin(a)]),'max_time':iso(tt[np.argmax(a)])}
    return {'night_23_07':stats(night),'late_03_06':stats(late),'late_median_minus_raw_baseline_median':float(np.nanmedian(v[late])-np.nanmedian(raw[baseline])),
            'late_mean_minus_raw_baseline_mean':float(np.nanmean(v[late])-np.nanmean(raw[baseline]))}

def main():
    ip=BASE/'data/left'/DEV/'input.npz'
    with np.load(ip) as d:t=d['timestamp'];raw=d['x'];names=list(map(str,d['names']))
    fed=w3(t,raw);old=make_model(t,fed,names,4);enlarged=make_model(t,fed,names,9)
    old_eval=evaluate(t,fed,old);new_eval=evaluate(t,fed,enlarged);tt=old_eval['t'];assert np.array_equal(tt,new_eval['t'])
    source_stage=R9/'reports'/f'algorithm_cause_audit_stage_{DEV}.npz'
    with np.load(source_stage) as s:
        selected=np.isin(tt,s['timestamp']);assert np.array_equal(tt[selected],s['timestamp']);assert np.array_equal(np.isfinite(old_eval['core'][selected]),np.isfinite(s['modal']))
        native_error=float(np.nanmax(abs(old_eval['core'][selected]-s['modal'])))
    assert native_error<1e-8,native_error
    log_path=BASE/'round2_waveform_10n/results/current_fade07/left'/DEV/'replay.log'
    native_logs={}
    for line in log_path.read_text(encoding='utf8').splitlines():
        if line.startswith('REG_ENERGY,20769,'):
            c=line.split(',');native_logs[c[2]]={'minimum_q':float(c[4]),'gain':float(c[5])}
    assert set(native_logs)==set(old['gain_detail'])
    for n,v in native_logs.items():
        assert abs(v['gain']-old['gain_detail'][n]['gain'])<1e-10
        assert abs(v['minimum_q']-old['gain_detail'][n]['minimum_q'])<1e-8
    raw_night=raw[old_eval['sel']];point_rows=[]
    for j,name in enumerate(names):
        a=metric(old_eval['core'][:,j],tt,raw_night[:,j]);b=metric(new_eval['core'][:,j],tt,raw_night[:,j])
        role='XJ' if 'XJ' in name else 'J' if name.startswith('ZJ') else 'ordinary'
        point_rows.append({'marker':name,'role':role,'is_42_47':bool(re.match(r'ZD(42|43|44|45|46|47)\d+$',name)),
            'old_22_02_modal':a,'new_22_07_modal':b,
            'delta_night_range_new_minus_old':b['night_23_07']['range']-a['night_23_07']['range'],
            'delta_abs_late_offset_new_minus_old':abs(b['late_median_minus_raw_baseline_median'])-abs(a['late_median_minus_raw_baseline_median']),
            'old_identity':{'use':bool(old['use'][j]),'learn':bool(old['learn'][j]),'fit_only':bool(old['fit_only'][j]),'spread_drop':bool(old['spread_drop'][j]),'guard_drop':bool(old['guard_drop'][j]),'gain':float(old['gains'][j])},
            'new_identity':{'use':bool(enlarged['use'][j]),'learn':bool(enlarged['learn'][j]),'fit_only':bool(enlarged['fit_only'][j]),'spread_drop':bool(enlarged['spread_drop'][j]),'guard_drop':bool(enlarged['guard_drop'][j]),'gain':float(enlarged['gains'][j])}})
    def summarize(rows):
        return {'points':len(rows),'range_improved_gt_1e_6':sum(r['delta_night_range_new_minus_old'] < -1e-6 for r in rows),'range_worse_gt_1e_6':sum(r['delta_night_range_new_minus_old'] > 1e-6 for r in rows),
                'range_worse_gt_0p1':sum(r['delta_night_range_new_minus_old'] > .1 for r in rows),'abs_late_offset_improved_gt_1e_6':sum(r['delta_abs_late_offset_new_minus_old'] < -1e-6 for r in rows),
                'abs_late_offset_worse_gt_0p1':sum(r['delta_abs_late_offset_new_minus_old'] > .1 for r in rows),
                'old_range_le_1':sum(r['old_22_02_modal']['night_23_07']['range']<=1 for r in rows),'new_range_le_1':sum(r['new_22_07_modal']['night_23_07']['range']<=1 for r in rows)}
    summary=summarize(point_rows);summary['ordinary']=summarize([r for r in point_rows if r['role']=='ordinary']);summary['J']=summarize([r for r in point_rows if r['role']=='J'])
    worst=sorted(point_rows,key=lambda r:-r['delta_night_range_new_minus_old'])[:10]
    artifact=OUT/'history_window_sensitivity.npz'
    np.savez_compressed(artifact,timestamp=tt,names=names,raw=raw_night,w3=fed[old_eval['sel']],modal_history_22_02=old_eval['core'],modal_history_22_07=new_eval['core'],A_22_02=old['A'],A_22_07=enlarged['A'],learn_22_02=old['learn'],learn_22_07=enlarged['learn'],gain_22_02=old['gains'],gain_22_07=enlarged['gains'])
    def metadata(model):
        return {'history':[{'night':h['date'],'start':iso(h['start_ms']),'end_exclusive':iso(h['end_exclusive_ms']),'frames':h['n_frames']} for h in model['hist']],
                'latest_history_data_before_target_freeze':max(h['end_exclusive_ms'] for h in model['hist'])<=ms(NIGHT+' 23:00'),
                'pooled_frames':model['nf'],'learn_names':[n for j,n in enumerate(names) if model['learn'][j]],'spread_rms_cutoff':float(model['spread_cutoff']),
                'gain_detail_recomputed_from_history':model['gain_detail']}
    result={'scope':'One device327479, held-out11/12 night. Python modal-only historical-window sensitivity, not a new native algorithm replay or deployment candidate.',
            'comparison':'Historical11/09,10,11 statistics22–02 versus22–07; W3/raw input and each reference22–23 unchanged; target model frozen23:00, no target-night future used for model or gain.',
            'input_sha256':sha(ip),'source_stage_sha256':sha(source_stage),'original_modal_matches_frozen_core_max_abs':native_error,'old_recomputed_gains_match_native_logs':True,
            'gain_method':'Recompute source use/learn/spread/guard/regression rows. For each ordinary nonlearn row recompute pairwise support and q in each enlarged historical window, gain=clamp(2*min_q,0,1); invalid or unsupported evidence closes to0. J fit-only and learn rows retain source exemption.',
            'old_model':metadata(old),'enlarged_model':metadata(enlarged),'summary':summary,'worst_range_changes':worst,'points':point_rows,
            'array_artifact':str(artifact),'array_sha256':sha(artifact),'helper_sha256':{str(p):sha(p) for p,_ in HELPERS},'script_sha256':sha(Path(__file__)),
            'limits':['No S2/S1 output, Y behavior, new native state serialization, restart, cold start or ten-night whole-device acceptance was tested.','Range and offset reduction do not establish preserved true movement or physical accuracy.','Only historical data were enlarged. This does not test learning current-night future data or online refitting during the current disturbance.','The original frozen native comparison validates the reconstruction path, not native execution of the enlarged-history proposal.']}
    (OUT/'history_window_sensitivity.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    focused=[next(r for r in point_rows if r['marker']==name) for name in ['ZXJ6','ZD4403','ZD4503','ZD4603','ZD4703','ZJ5','ZJ6','ZJ7','ZJ8']]
    print('SUMMARY',json.dumps(summary),flush=True)
    print('FOCUS',json.dumps([{'marker':r['marker'],'old_range':r['old_22_02_modal']['night_23_07']['range'],'new_range':r['new_22_07_modal']['night_23_07']['range'],'old_offset':r['old_22_02_modal']['late_median_minus_raw_baseline_median'],'new_offset':r['new_22_07_modal']['late_median_minus_raw_baseline_median'],'old_learn':r['old_identity']['learn'],'new_learn':r['new_identity']['learn'],'new_gain':r['new_identity']['gain']} for r in focused]),flush=True)
    md=['# 历史22–02与22–07：单设备单夜模态敏感性','','本轮只检查左线780638327479、11/12夜。扩大的是11/09、10、11三夜的历史统计范围；基准仍各夜22–23，本夜模型仍在23点固定，未使用本夜未来数据。没有运行新DLL，也没有修改交付源码、状态或数据库。','',
        f"22–02统计每夜240帧，22–07统计每夜540帧。原方案独立模态重建与冻结原生核心最大差 {native_error:.3g} pixel；原历史能量q/gain与原生日志一致。扩大窗后已按源码重算历史能量gain，没有套用旧日志。",'',
        '下表全部为模态核心输出，尚未经过S2/S1。偏移为03–06中位值减本点raw22–23中位基准；范围为23–07的max−min。','',
        '|测点|旧窗范围|扩大窗范围|旧窗晚间偏移|扩大窗晚间偏移|','|---|---:|---:|---:|---:|']
    for r in focused:md.append(f"|{r['marker']}|{r['old_22_02_modal']['night_23_07']['range']:.3f}|{r['new_22_07_modal']['night_23_07']['range']:.3f}|{r['old_22_02_modal']['late_median_minus_raw_baseline_median']:+.3f}|{r['new_22_07_modal']['late_median_minus_raw_baseline_median']:+.3f}|")
    md += ['',f"全54点：范围减小 {summary['range_improved_gt_1e_6']} 点、增大 {summary['range_worse_gt_1e_6']} 点，其中增大超过0.1 pixel的 {summary['range_worse_gt_0p1']} 点；晚间绝对偏移改善 {summary['abs_late_offset_improved_gt_1e_6']} 点，恶化超过0.1 pixel的 {summary['abs_late_offset_worse_gt_0p1']} 点。这些仅为本次敏感性统计，不是现场通过率。",'',
           '范围增大最多的点：','','|测点|范围增加|扩大后范围|扩大后晚间偏移|','|---|---:|---:|---:|']
    for r in worst[:5]:md.append(f"|{r['marker']}|{r['delta_night_range_new_minus_old']:+.3f}|{r['new_22_07_modal']['night_23_07']['range']:.3f}|{r['new_22_07_modal']['late_median_minus_raw_baseline_median']:+.3f}|")
    md += ['', '边界：未验证整链S2/S1、Y、状态导入导出、冷启动、跨夜更新或其他设备/夜间。缩小范围与偏移并不证明真实运动被保留。若要改正式实现，需另行验证过去窗口延长后的统计归档时间、冷启动和状态兼容；本诊断不支持直接替换现有交付。']
    (OUT/'history_window_sensitivity.md').write_text('\n'.join(md)+'\n',encoding='utf8')

if __name__=='__main__':main()
