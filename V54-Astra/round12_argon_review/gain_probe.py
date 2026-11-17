"""One fixed-model numerical audit of Argon's gain proposal; no native execution."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import ast,copy,json,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent
TZ=timezone(timedelta(hours=8));NIGHT='2026-11-12'
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
HELPERS=[(BASE/'round4_window_causality/tools/yd_stage_audit.py',{'w3'}),
 (BASE/'round9_left_42_47_1112/tools/algorithm_cause_audit.py',{'night_data','solve','evaluate'}),
 (BASE/'round10_history_design/tools/history_window_sensitivity.py',{'history_stat','make_model'})]
for path,wanted in HELPERS:
    tree=ast.parse(path.read_text(encoding='utf8'))
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted],type_ignores=[]),str(path),'exec'))

def main():
    source=BASE/'data/left/780638327479/input.npz'
    with np.load(source) as f:t=f['timestamp'];raw=f['x'];names=list(map(str,f['names']))
    fed=w3(t,raw);model=make_model(t,fed,names,4);j=names.index('ZXJ6');L=np.flatnonzero(model['learn']);V=model['A'][L]
    actual=evaluate(t,fed,model,date=NIGHT);tt=actual['t'];raw_night=raw[actual['sel']]
    baseline=tt<ms('2026-11-12 23:00');night=(tt>=ms('2026-11-12 23:00'))&(tt<ms('2026-11-13 07:00'));late=(tt>=ms('2026-11-13 03:00'))&(tt<ms('2026-11-13 06:00'))
    raw_ref_med=float(np.median(raw_night[baseline,j]));detail=model['gain_detail']['ZXJ6'];q=detail['minimum_q']
    candidate=copy.deepcopy(model);candidate['A'][j]*=q/model['gains'][j]
    changed=evaluate(t,fed,candidate,date=NIGHT)
    def metrics(v):return dict(night_range=float(np.ptp(v[night,j])),late_median_minus_raw_ref_median=float(np.median(v[late,j])-raw_ref_med),late_mean_minus_algorithm_baseline=float(np.mean(v[late,j]-actual['b'][j])))
    original_stage=BASE/'round9_left_42_47_1112/reports/algorithm_cause_audit_stage_780638327479.npz'
    with np.load(original_stage) as z:
        take=np.isin(tt,z['timestamp']);error=float(np.nanmax(abs(actual['core'][take]-z['modal'])))
    assert error<1e-8
    per_mode=[]
    for h in model['hist']:
        H=np.divide(h['S'],h['N'],out=np.zeros_like(h['S']),where=h['N']>1)
        R=V.T@H[np.ix_(L,L)]@V
        a=model['A'][j]/model['gains'][j]
        component_cross=a*(H[j,L]@V);component_energy=(a*a)*np.diag(R)
        qk=np.divide(component_cross,component_energy,out=np.full(3,np.nan),where=component_energy>1e-14)
        gram=a[:,None]*R*a[None,:]
        corr=R/np.sqrt(np.outer(np.diag(R),np.diag(R)))
        per_mode.append(dict(night=h['date'],mode_score_second_moment=R.tolist(),mode_score_uncentered_normalized_moment=corr.tolist(),max_abs_normalized_offdiag=float(np.max(abs(corr-np.eye(3)))),component_q=qk.tolist(),component_cross=component_cross.tolist(),component_energy=component_energy.tolist(),total_component_energy=float(gram.sum()),diagonal_only_energy=float(np.trace(gram)),cross_terms=float(gram.sum()-np.trace(gram))))
    loadings={n:dict(A=model['A'][names.index(n)].tolist(),use=bool(model['use'][names.index(n)]),learn=bool(model['learn'][names.index(n)]),fit_only=bool(model['fit_only'][names.index(n)]),gain=float(model['gains'][names.index(n)])) for n in ['ZXJ6','ZD4403','ZD4503','ZD4603','ZD4703','ZJ5','ZJ6','ZJ7','ZJ8']}
    late_rows=[]
    for n in loadings:
        k=names.index(n);obs=actual['fed'][late,k]-actual['b'][k];pred=actual['prediction'][late,k]
        good=np.isfinite(obs)&np.isfinite(pred);obs=obs[good];pred=pred[good]
        late_rows.append(dict(marker=n,observed_mean=float(obs.mean()),prediction_minus_cbar_mean=float(pred.mean()),residual_mean=float((obs-pred).mean()),q_current_second_moment=float(obs@pred/(pred@pred)),observed_median=float(np.median(obs)),prediction_median=float(np.median(pred)),residual_median=float(np.median(obs-pred))))
    rec=dict(scope='one device, one night, fixed model; X modal core only; no native execution, no production change',history_gain=detail,
        raw_median_offset=float(np.median(raw_night[late,j])-raw_ref_med),w3_median_offset=float(np.median(actual['fed'][late,j])-raw_ref_med),
        original_metrics=metrics(actual['core']),minq_row_only_metrics=metrics(changed['core']),baseline_native_max_abs_error=error,
        eigenvalues=model['eigenvalues'][:3].tolist(),lambda3_over_lambda1=float(model['eigenvalues'][2]/model['eigenvalues'][0]),loadings=loadings,late_observed_prediction=late_rows,per_night_mode_moments=per_mode,
        argon_quoted_ratio=6.148/(6.148+5.119),pooled_equal_night_second_moment_optimum=sum(r['cross'] for r in detail['by_night'])/sum(r['predicted'] for r in detail['by_night']))
    (ROOT/'gain_audit.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:rec[k] for k in ['history_gain','original_metrics','minq_row_only_metrics','eigenvalues','lambda3_over_lambda1','pooled_equal_night_second_moment_optimum']},ensure_ascii=False,indent=2))
    print('MODE_CROSS',json.dumps(per_mode,ensure_ascii=False))
if __name__=='__main__':main()
