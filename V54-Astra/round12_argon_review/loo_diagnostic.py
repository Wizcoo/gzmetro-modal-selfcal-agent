"""Audit Argon LOO claims with the already frozen R11 model; not a new solver release."""
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent
P=BASE/'round11_current_applicability/reports/synthetic_constant_core_arrays.npz'
with np.load(P) as f:
    A=f['historical_A'];learn=f['historical_learn'];names=list(map(str,f['names']))
L=np.flatnonzero(learn);B=A[L];G=B.T@B;H=B@np.linalg.solve(G,B.T);h=np.diag(H)
J=np.array([n.startswith(('YJ','ZJ')) and 'XJ' not in n for n in names])
def diagnose(z,kind='tukey'):
    v0=np.linalg.solve(G,B.T@z[L]);res=z[L]-B@v0;loo=res/(1-h)
    sigma=1.4826*np.median(abs(loo));tau=max(.08,3*sigma)
    if kind=='huber':weights=np.minimum(1,tau/np.maximum(abs(loo),1e-30))
    elif kind=='tukey':weights=np.maximum(0,1-(loo/tau)**2)**2
    elif kind=='hard':weights=(abs(loo)<=tau).astype(float)
    else:raise ValueError(kind)
    Gw=B.T@(weights[:,None]*B);v1=np.linalg.solve(Gw,B.T@(weights*z[L]));out=z-A@v1
    return {'v0':v0,'loo':loo,'sigma':float(sigma),'tau':float(tau),'weights':weights,'out':out,'gram_rank':int(np.linalg.matrix_rank(Gw))}
records=[]
for marker in ['ZD3204','ZD4703']:
    j=names.index(marker);local=list(L).index(j)
    for step in [.2,1.]:
        z=np.zeros(len(names));z[j]=step;one={'marker':marker,'step':step,'leverage':float(h[local]),'total_guard_0p5_excludes':bool(h[local]>.5),'variants':{}}
        for kind in ['huber','tukey','hard']:
            d=diagnose(z,kind);other=np.arange(len(names))!=j
            one['variants'][kind]={'target_loo':float(d['loo'][local]),'sigma_median_abs_loo':d['sigma'],'threshold':d['tau'],
                'peer_median_abs_loo':float(np.median(abs(np.delete(d['loo'],local)))),
                'target_weight':float(d['weights'][local]),'retained_fraction':float(d['out'][j]/step),
                'other_stationary_max_false_response':float(np.max(abs(d['out'][other]))),'fixed_J_max_false_response':float(np.max(abs(d['out'][J]))),
                'remaining_weighted_gram_rank':d['gram_rank']}
        records.append(one)
# A true physical group event on the learning markers that lies exactly in the
# historical solve subspace. All non-learning markers (including fixed J) have zero truth.
vc=np.array([1.,0.,0.]);vc/=np.max(abs(B@vc));truth=np.zeros(len(names));truth[L]=B@vc;d=diagnose(truth)
group=dict(learning_points=int(len(L)),max_true_amplitude=float(np.max(abs(truth))),max_abs_loo=float(np.max(abs(d['loo']))),
    min_weight=float(d['weights'].min()),learning_output_max_abs=float(np.max(abs(d['out'][L]))),
    stationary_J_max_false_response=float(np.max(abs(d['out'][J]))),stationary_nonlearning_max_false_response=float(np.max(abs(d['out'][~learn]))))
cancel=[]
constant_projection=B@np.linalg.lstsq(B,-np.ones(len(L)),rcond=None)[0]
for marker in ['ZD3204','ZD4703']:
    j=names.index(marker);local=list(L).index(j)
    for label in ['all_points_uniform_minus1','exact_historical_subspace']:
        if label=='all_points_uniform_minus1':disturbance=-np.ones(len(names))
        else:
            vc=-A[j]/float(A[j]@A[j]);disturbance=A@vc
        truth=np.zeros(len(names));truth[j]=1.;observed=truth+disturbance;d=diagnose(observed)
        cancel.append(dict(marker=marker,disturbance_assumption=label,target_raw=float(observed[j]),
            target_known_true=1.,target_loo=float(d['loo'][local]),threshold=d['tau'],target_weight=float(d['weights'][local]),
            target_output=float(d['out'][j]),max_error_vs_true=float(np.max(abs(d['out']-truth)))))
# The proposed denominator floor changes deleted-residual identity near h=1.
bb=np.array([1.,.01,.01,.01,.01]);hh=bb[0]**2/float(bb@bb);rr=1-hh
cap=dict(one_parameter_toy=True,leverage=hh,ordinary_residual=rr,exact_deleted_residual=rr/(1-hh),proposed_capped_residual=rr/max(1-hh,.1))
report=dict(scope='One-frame, modal-only synthetic audit using frozen real 327479 model from histories11/09-11. No W3/S2/S1, no native runtime, no parameter tuning.',
    frozen_model_source=str(P),frozen_model_sha256=hashlib.sha256(P.read_bytes()).hexdigest(),
    column_orthogonality_max_error=float(np.max(abs(G-np.eye(3)))),actual_solver='Unregularized OLS over active valid learning points; >=5 points; singular returns failure; at most two solves with absolute residual threshold2.5.',
    thresholds_fixed_from_argon={'noise_floor':.08,'sigma_multiplier':3.,'scale':'1.4826 median(abs(LOO)), no centering'},
    isolated_steps=records,group_event_in_solve_subspace=group,cancellation_fixtures=cancel,
    uniform_minus1_max_error_of_best_unweighted_learning_projection=float(np.max(abs(-1-constant_projection))),denominator_floor_counterexample=cap)
(ROOT/'loo_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
print(json.dumps({'isolated_steps':records,'group_event':group,'cancellation':cancel,'denominator_cap':cap},ensure_ascii=False,indent=2))
