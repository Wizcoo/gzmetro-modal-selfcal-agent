"""Algebraic counterexamples to the pasted Argon proposal, not a new algorithm."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent
def accumulate(u,alpha):
    c=[0.0]
    for i in range(1,len(u)):c.append(c[-1]+alpha[i]*(u[i]-u[i-1]))
    return c
def main():
    u=[0.0,1.0,0.0];alpha=[0.0,.5,1.0];c=accumulate(u,alpha)
    # At the last frame the proposal's recovery condition is satisfied.
    assert abs(u[2])<abs(c[1]) and c[-1]==-.5
    cycle={'u':u,'alpha':alpha,'actual_compensation':c,'raw_for_pure_disturbance':u,'output':[x-y for x,y in zip(u,c)],
        'last_frame_proposed_recovery_condition':True,'known_true_motion':[0,0,0]}
    constant={'u':[0,1,1,1],'alpha':[0,.5,1,1]}
    constant['actual_compensation']=accumulate(constant['u'],constant['alpha'])
    assert constant['actual_compensation']==[0,.5,.5,.5]
    z_j=1.0;c_prev=.9;u_prev=.9;u_now=2.0;rem=z_j-c_prev;du=u_now-u_prev
    assert rem*du>0
    overshoot={'j_raw_change':z_j,'previous_actual_compensation':c_prev,'u_prev':u_prev,'u_now':u_now,
        'remaining_residual':rem,'theoretical_increment':du,'same_sign_test_passes':True,
        'accepted_compensation':c_prev+du,'resulting_j_residual':z_j-(c_prev+du)}
    assert abs(overshoot['resulting_j_residual'])>abs(rem)
    j_pass={'j_raw_change':1,'j_prediction':.8,'j_remaining_after_correction':.2,
        'target_raw_change':1,'target_prediction':2,'target_after_correction':-1,
        'assumption':'One physical device disturbance with stale target/J loading ratio; fixed J still under-corrected while target already over-corrected.'}
    no_j={'design_column':[1]*6,'observed_z':[1]*6,'fitted_coefficient':1,'orthogonal_residual_ratio':0,
        'alpha_from_one_minus_ratio':1,'output':[0]*6,'known_true_group_motion':[1]*6,
        'assumption':'No fixed reference; true coherent group motion lies in learned subspace. Identical observations could also arise from device motion.'}
    result={'scope':'Exact scalar algebra / explicitly constructed physical-truth thought experiments. No field replay, native execution, production or state changes.',
        'partial_acceptance_then_recovery':cycle,'constant_demand_after_reopening':constant,
        'reference_sign_check_does_not_bound_step':overshoot,'J_underfit_cannot_validate_target_loading':j_pass,'no_J_subspace_consistency_not_motion_identity':no_j}
    (ROOT/'increment_counterexamples.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    report='''# Argon增量门控：可执行反例

以下严格按附件的 `c(t)=c(t-1)+alpha(t)*(u(t)-u(t-1))` 计算。它确实去掉了直接乘总补偿的 `-c_prev*delta_gain` 项，但没有证明无漂移、无跳变或能回零。

## 1. “回退一律放行”可能造成反向残留

|时刻|理论补偿u|alpha|实际补偿c|纯设备扰动raw=u|输出raw-c|
|---|---:|---:|---:|---:|---:|
|0|0|0|0|0|0|
|1|1|0.5|0.5|1|0.5|
|2|0|1|-0.5|0|0.5|

最后一帧满足附件的回退条件 `abs(u)=0 < abs(c_prev)=0.5`。真实扰动已回零，但实际补偿变成-0.5，制造+0.5残留。原因是先前只接受一半上升量，回退却扣了完整下降量。

一般式：若初始c=u，则 `c(t)-u(t) = sum((alpha(s)-1)*delta_u(s))`。开启/关闭期间丢失的增量会留下路径依赖。恢复段必须相对于实际已接受补偿规划，检查不越过目标/零点；不能直接宣称alpha=1就能消除旧偏置。

## 2. 恢复信任也不自动补齐

理论u为 `[0,1,1,1]`，alpha为 `[0,0.5,1,1]`，实际c仍是 `[0,0.5,0.5,0.5]`。后续需求恒定、delta_u=0，开门后也无法跟踪到1。若改用u-c作为追踪误差，又需要单独处理补齐时的变化幅度与可信证据，不能当成无副作用替换。

## 3. J残差与增量同向仍可能一步过冲

J观测变化1，已接受补偿0.9，剩余残差+0.1；理论补偿从0.9增加到2，增量+1.1。两者同向，附件规则允许alpha=1，实际补偿变成2，J残差从+0.1变成-1。必须检查更新后的参考误差和幅度，而不只是更新前的符号。即使J自身验证通过，也不能单独证明目标点历史载荷正确。

## 4. J通过不代表每个普通点/XJ都通过

同一设备扰动：J raw变化1，模型只预测0.8；目标raw变化1，旧模型却预测2。J仍有+0.2未补，目标已经反向至-1。单个设备级放行因子无法识别目标载荷过大；要检查模式在J上的可观测性，以及从参考向目标转移的历史关系是否仍成立。实际R9里ZJ7晚间残留为正、ZXJ6大幅为负，不能假定J与目标必然一起过补。

## 5. 无J时的子空间残差不识别运动来源

构造6个普通点，历史只有全1公共模式，当前6点都真实移动+1。拟合系数1、正交残差比rho=0，按1-rho得到满增量；输出全部0，真实运动被抹除。相同观测也能由相机扰动造成。在没有额外参考信息时，子空间一致性只能说明“能拟合”，不能证明“可扣除”。

上述不是现场发生率统计，也没有运行新DLL；它们足以否定附件关于公式普遍无残留/无跳变/满足全部反例的承诺。增量控制仍可研究，但需要重设计闭环跟踪、参考支持、缺测和重启语义，并覆盖S2/S1后级。
'''
    (ROOT/'increment_review.md').write_text(report,encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
