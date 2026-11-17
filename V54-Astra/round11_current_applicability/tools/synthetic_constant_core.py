"""Real historical model + explicitly synthetic current truth, Python modal-only."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import ast,hashlib,json
import numpy as np

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=ROOT/'reports'
TZ=timezone(timedelta(hours=8));NIGHT='2026-11-12';DEVICE='780638327479'
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def iso(t):return datetime.fromtimestamp(int(t)/1000,TZ).isoformat(timespec='milliseconds')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
HELPERS=[(BASE/'round4_window_causality/tools/yd_stage_audit.py',{'w3'}),
         (BASE/'round9_left_42_47_1112/tools/algorithm_cause_audit.py',{'night_data','solve','evaluate'}),
         (BASE/'round10_history_design/tools/history_window_sensitivity.py',{'history_stat','make_model'})]
for path,wanted in HELPERS:
    tree=ast.parse(path.read_text(encoding='utf8'))
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted],type_ignores=[]),str(path),'exec'))

def main():
    OUT.mkdir(parents=True,exist_ok=True);ip=BASE/'data/left'/DEVICE/'input.npz'
    with np.load(ip) as z:t=z['timestamp'];raw=z['x'];names=list(map(str,z['names']))
    fed=w3(t,raw);model=make_model(t,fed,names,4)
    assert [h['date'] for h in model['hist']]==['2026-11-09','2026-11-10','2026-11-11']
    actual=evaluate(t,fed,model,date=NIGHT)
    stagepath=BASE/'round9_left_42_47_1112/reports'/f'algorithm_cause_audit_stage_{DEVICE}.npz'
    with np.load(stagepath) as z:
        take=np.isin(actual['t'],z['timestamp']);assert np.array_equal(actual['t'][take],z['timestamp'])
        error=float(np.nanmax(abs(actual['core'][take]-z['modal'])))
    assert error<1e-8
    start=ms(NIGHT+' 22:00');end=ms('2026-11-13 07:00');ts=np.arange(start,end,60000,dtype=np.int64)
    ref=(t>=start)&(t<start+3600000);levels=np.nanmedian(raw[ref],axis=0);assert np.isfinite(levels).all()
    constant=np.repeat(levels[None,:],len(ts),axis=0);target_index=names.index('ZD4703')
    L=np.flatnonzero(model['learn']);projection=model['A']@np.linalg.solve(model['A'][L].T@model['A'][L],model['A'][L].T)
    candidates=[j for j in L if 'J' not in names[j]]
    largest=max(candidates,key=lambda j:projection[j,list(L).index(j)])
    targets=list(dict.fromkeys([target_index,largest]));step_time=ms('2026-11-13 00:00')
    cases=[];arrays={'timestamp':ts,'names':np.asarray(names),'constant_levels':levels,'historical_A':model['A'],'historical_learn':model['learn']}
    inputs=[('all_points_constant',None,0.0,constant)]
    for j in targets:
        for amount in [.2,1.0]:
            synthetic=constant.copy();synthetic[ts>=step_time,j]+=amount
            inputs.append((f'{names[j]}_local_step_{amount:g}',j,amount,synthetic))
    night=ts>=start+3600000;post=ts>=step_time;pre=(ts>=step_time-1800000)&(ts<step_time)
    fixed=[j for j,n in enumerate(names) if n.startswith('ZJ')]
    for key,j,amount,synthetic in inputs:
        ev=evaluate(ts,synthetic,model,date=NIGHT);assert np.array_equal(ev['t'],ts)
        corrected=ev['core'];correction=synthetic-corrected
        other=np.ones(len(names),bool)
        if j is not None:other[j]=False
        rec=dict(case=key,target=None if j is None else names[j],injected_true_step=amount,
            step_timestamp=None if j is None else iso(step_time),all_current_observations_valid=True,
            source='Synthetic current inputs, fixed per-marker nonzero levels from real22-23 median; all54 coordinates constant except explicit one-point step.',
            target_is_learning_point=None if j is None else bool(model['learn'][j]),
            target_use=None if j is None else bool(model['use'][j]),
            historical_gain=None if j is None else float(model['gains'][j]),
            modal_max_abs_correction=float(np.max(abs(correction[night]))),
            max_output_error_against_known_physical_truth=float(np.max(abs(corrected[night]-synthetic[night]))),
            stationary_other_points_max_error=float(np.max(abs(corrected[night][:,other]-constant[night][:,other]))),
            fixed_J_max_false_response=float(np.max(abs(corrected[night][:,fixed]-constant[night][:,fixed]))),
            baseline_cbar_max_abs=float(np.max(abs(ev['cbar']))),
            solver_support_min=int(ev['support'][ts>=start+4800000].min()),
            robust_rejected_sample_point_pairs=int(ev['drop'][night].sum()))
        if j is not None:
            amp=float(np.median(corrected[post,j])-np.median(corrected[pre,j]));responses=corrected[post]-constant[post]
            direction=np.abs(corrected[:,j]-levels[j])>1e-10
            onset=ts[direction][0] if direction.any() else None
            rec.update(recovered_step=amp,removed_true_step=amount-amp,retained_fraction=amp/amount,
                response_onset=None if onset is None else iso(onset),modal_onset_delay_ms=None if onset is None else int(onset-step_time),
                maximum_false_response_marker=names[int(np.argmax(np.max(abs(np.where(other[None,:],responses,0)),axis=0)))],
                target_leverage=float(projection[j,list(L).index(j)]) if j in L else 0.0)
        else:
            rec['all_points_output_peak_to_peak_max']=float(np.max(np.ptp(corrected[night],axis=0)))
            assert rec['modal_max_abs_correction']<1e-12
        cases.append(rec);arrays[key+'_input_truth']=synthetic;arrays[key+'_modal']=corrected
    z0=solve(np.zeros(len(names)),model);assert z0 is not None
    # Optional boundary diagnostic: preserve actual W3 cache before22:00 while
    # feeding the synthetic constant night. This is still Python W3+modal only.
    prefix=t<start;joined_t=np.r_[t[prefix],ts];joined_raw=np.vstack([raw[prefix],constant]);joined_fed=w3(joined_t,joined_raw)
    current_fed=joined_fed[-len(ts):];boundary=evaluate(ts,current_fed,model,date=NIGHT)
    diff=np.max(abs(current_fed-constant),axis=1);changed=np.flatnonzero(diff>1e-12)
    boundary_rec=dict(scope='Supplemental Python W3-continuity plus modal diagnostic, not native full chain',
        initial_current_frame_indices_changed_from_constant=changed.tolist(),
        current_w3_max_deviation=float(diff.max()),
        current_w3_from_third_frame_exactly_constant=bool(np.max(abs(current_fed[2:]-constant[2:]))<1e-12),
        baseline_error_vs_constant_max=float(np.max(abs(boundary['b']-levels))),
        main_window_core_max_error_vs_constant=float(np.max(abs(boundary['core'][night]-constant[night]))),
        main_window_max_generated_range=float(np.max(np.ptp(boundary['core'][night],axis=0))))
    arrays['continuity_w3_constant_fed']=current_fed;arrays['continuity_w3_constant_modal']=boundary['core']
    artifact=OUT/'synthetic_constant_core_arrays.npz';np.savez_compressed(artifact,**arrays)
    report=dict(scope='Synthetic known-truth current-night fixtures after real11/09-11 history; Python modal core only, no native DLL or production modification.',
        device=DEVICE,history=[{'date':h['date'],'window':'22:00-next02:00','frames':h['n_frames']} for h in model['hist']],
        current_window={'start_inclusive':iso(start),'end_exclusive':iso(end),'frames':len(ts),'baseline_frames':60,'main_frames':480},
        learning_markers=[names[j] for j in L],fixed_J_markers=[names[j] for j in fixed],
        target_selection={'primary':'ZD4703, already highlighted in11/12 residual review','supplemental':names[largest],'supplemental_rule':'largest self-leverage among ordinary historical learning points; selected from frozen historical model only'},
        zero_vector_solve={'coefficient_max_abs':float(np.max(abs(z0[0]))),'prediction_max_abs':float(np.max(abs(model['A']@z0[0])))},
        model_reconstruction_existing_frozen_native_core_max_abs_error=error,
        cases=cases,W3_continuity_boundary_diagnostic=boundary_rec,
        interpretation=['Frozen history alone does not generate modal correction when current baseline-referenced vector is exactly zero.',
            'A local true step at a historical learning point is projected into common modes even when all fixedJ stay constant; no2.5pixel residual rejection is triggered by these0.2/1pixel fixtures.',
            'Constant direct modal input assumes current W3 initial effects absent or flushed; the separate continuity fixture shows actual old-cache contamination can bias the22-23 baseline slightly.',
            'No S2 mount damping, S1 temporal damping, Y, native state serialization/restart, history update or end-to-end deployment behavior is validated here.'],
        input_sha256=sha(ip),frozen_stage_sha256=sha(stagepath),helper_sha256={str(p):sha(p) for p,_ in HELPERS},
        artifact=str(artifact),artifact_sha256=sha(artifact),script_sha256=sha(__file__))
    (OUT/'synthetic_constant_core.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    lines=['# 真实三夜历史后：恒定今日与局部真实step','','冻结左327479的11/09、10、11三夜22–02历史，使用同一Python历史重建和modal evaluate。当前11/12 22–次07为明确合成数据，54点全部有效；基准22–23也恒定。常值取各点真实22–23中位数，保留各点不同的非零坐标。','',
        f"原真实11/12核心重建与既有原生核心最大差{error:.3g} pixel。这个核对验证重建路径，下面合成实验本身没有执行原生DLL。",'',
        '| 场景 | 注入真实step | 恢复step | 扣掉真实step | 其他静止点最大误差 | 固定J最大误差 |','|---|---:|---:|---:|---:|---:|']
    for r in cases:
        lines.append(f"| {r['case']} | {r['injected_true_step']:.6g} | {r.get('recovered_step',0):.6g} | {r.get('removed_true_step',0):.6g} | {r['stationary_other_points_max_error']:.6g} | {r['fixed_J_max_false_response']:.6g} |")
    lines += ['',f"全点恒定时modal最大补偿{cases[0]['modal_max_abs_correction']:.3g} pixel，最大生成峰谷差{cases[0]['all_points_output_peak_to_peak_max']:.3g} pixel。直接z=0求解的模态系数与预测补偿均为0。说明‘历史波动强’本身不会在今日z=0时凭空生成modal修复。",'',
        '局部step在00:00施加，其他普通点、J、XJ全部保持物理静止，真值即合成输入。ZD4703为预先关注点；补充点按冻结历史模型中普通学习点最大自投影比例选择。若目标是学习点，局部真实step会贡献到模态反解，因而部分被扣掉，并在其他静止点产生假响应。0.2/1 pixel没有触发2.5 pixel残差剔除。这是core层对局部真实运动的风险证据，不等同于整链或现场必然产生同样误差。','',
        '## W3与基准边界','',
        f"另做Python边界诊断：保留22点前真实W3缓存，然后接全点恒定数据。受旧缓存影响的当前帧索引为{changed.tolist()}（从0开始），第三帧起已恒定；其22–23基准最大偏移{boundary_rec['baseline_error_vs_constant_max']:.6g} pixel，23–07 modal最大输出误差{boundary_rec['main_window_core_max_error_vs_constant']:.6g}、最大生成范围{boundary_rec['main_window_max_generated_range']:.6g} pixel。",'',
        'W3初始1–2帧、基准平均和已有缓存必须与“今日从基准起恒定”区分：理想恒定核心零补偿，并不能免除真实重启/连续缓存边界验证。step实验直接送modal，因此没有W3中值滤波造成的step延迟；S2、S1及原生状态恢复均未验证。', '',
        '未增加生产参数、未修改算法或数据库、未运行新DLL。数组和完整数值见同目录synthetic_constant_core_arrays.npz与synthetic_constant_core.json。','']
    (OUT/'synthetic_constant_core.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps({'cases':cases,'W3_boundary':boundary_rec},ensure_ascii=True))

if __name__=='__main__':main()
