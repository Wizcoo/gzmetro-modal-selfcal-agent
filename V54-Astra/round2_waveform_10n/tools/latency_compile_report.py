"""Collect complete waveform audits without mixing point-night comparison cohorts."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from latency_analyze import ROUND,clean

def run():
    reports=ROUND/'reports';rows=[];frames={}
    for path in sorted(reports.glob('latency_*_summary.json')):
        info=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(info.get('summary'),list):continue
        rows.extend(info['summary']);variant=info['variant']
        frame=pd.read_csv(reports/f'latency_{variant}_point_nights.csv')
        frames[variant]=frame
    summary=pd.DataFrame(rows);summary.to_csv(reports/'latency_variant_summary.csv',index=False,encoding='utf-8-sig')
    paired=[];keys=['line','device','marker','night','window']
    cols=['slow_best_lag_min','slow_corr_zero','slow_corr_best','lag_interpretable','lag_resolved','event_timing_interpretable',
          'event_signed_median_min','event_recall','slope_direction_agreement']
    base=frames['current'];base=base[base.eligible]
    for variant,frame in frames.items():
        if variant=='current':continue
        frame=frame[frame.eligible];merged=base[keys+cols].merge(frame[keys+cols],on=keys,suffixes=('_current','_variant'))
        for window,data in merged.groupby('window'):
            use=data[data.lag_interpretable_current & data.lag_interpretable_variant]
            row=dict(variant=variant,window=window,both_eligible=len(data),both_lag_interpretable=len(use))
            for metric in ['slow_best_lag_min','slow_corr_zero','slow_corr_best','slope_direction_agreement']:
                for suffix in ['current','variant']:row[metric+'_'+suffix+'_median']=use[metric+'_'+suffix].median()
            row['paired_lag_change_median_min']=(use.slow_best_lag_min_variant-use.slow_best_lag_min_current).median()
            row['paired_lag_decreased_count']=int((use.slow_best_lag_min_variant<use.slow_best_lag_min_current).sum())
            events=use[use.event_timing_interpretable_current & use.event_timing_interpretable_variant]
            row['both_events_interpretable']=len(events)
            for suffix in ['current','variant']:row['event_lag_'+suffix+'_median_min']=events['event_signed_median_min_'+suffix].median()
            paired.append(clean(row))
    pairedframe=pd.DataFrame(paired);pairedframe.to_csv(reports/'latency_paired_comparisons.csv',index=False,encoding='utf-8-sig')
    (reports/'latency_paired_comparisons.json').write_text(json.dumps(paired,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    active=summary[summary.window=='active_2320_07'];pairactive=pairedframe[pairedframe.window=='active_2320_07']
    main=['current','no_w3','no_s1','no_s2','no_temporal','modal_only']
    current=active[active.variant=='current'].iloc[0]
    lines=['# V54-Astra：延迟与波形独立审计','',
           '结论：当前结果确有滤波造成的分钟级信号滞后，不能归因于计算跑得慢。关闭 W3 可减少约 1 分钟，但不能据此宣布波形整体保真；大多数原始→修后曲线的相关性不足以解释成“同一波形平移”。','',
           '## 范围与口径','',
           '- 回放预热自 2026-11-02；评价 2026-11-06 至 11-15 共 10 个日历夜。左线 11-06 整夜缺失，没有替补、插值或把缺失算通过。',
           '- 12 台设备、524 点；夜间范围 22:00–次日08:00，主要修复段 23:20–次日07:00，UTC+08:00。点夜有效覆盖须至少 80%。',
           '- X 单位 pixel。真实峰峰值 max−min 与 P95−P5 分列；后者不是整夜波动上限。范围是否通过应使用主报告的分类门限。',
           '- raw 是波形参照，不是独立物理真值。模态扣除本来会改变 raw；因此高相关不能证明真实扰动保留，低相关也不能单独证明补偿错误。',
           '', '## 计算速度和信号延迟分开看','',
           '原生回放 current 的 Process 加权平均为 9.80 微秒/设备帧，各设备 P95 为 5.6–24.3 微秒，最大观测 20.45 毫秒（见 native_timing_summary.json）。包含现有缓冲诊断，不含文件输入输出；这是离线观测，不是硬实时保证。输出沿用当前输入时间戳，时间戳相同也不等于波形没有相位滞后。','',
           '直接调用未修改源码的原生 W3/S1/S2 分量：','',
           '- W3 三点因果中值在单调段精确输出前一帧；1 分钟采样就晚 1 分钟。局部极值可能变成平台，平台中心用于峰时刻。',
           '- S1 的 tau=1.5 分钟，alpha=0.486582880967408；低频等效滞后 1.055 分钟。10/20/60 分钟周期的 S1 正弦相位滞后分别约 0.758/0.957/1.043 分钟。',
           '- W3+S1 低频约 2.055 分钟；已知阶跃达到 50% 晚 2 分钟、95% 晚 5 分钟。这是滤波响应，不是请求队列积压。',
           '- S2 先收 30 帧全 gate 基线，约 23:50 后才真正减共模；这是启动等待，不是把数据晚发 30 分钟。其 15 帧因果中值对单调共模估计约晚 7 帧，但输出是“当前值减旧估计”，不能说最终输出统一晚 7 分钟。',
           '- 已知共同高斯峰经过 S2 可提前出现峰并带负尾；同样信号只发生在 1/9 点时，S2 原样保留该点。S2 不能单靠这些输入区分真实共同位移与共同扰动。','',
           '原生分量图：![Native components](latency_native_components.png)','',
           '## 十夜主消融对照','',
           '下表为 23:20–07:00 的 4,963 个合格点夜；“可解释时差”要求慢波最佳相关≥0.8、raw P95−P5≥0.1 px、输出≥0.05 px、至少120对样本且最优时差不在±10分钟搜索边界。该筛选仅用于避免错误解释时差，不是用户验收门限。','',
           '|版本|可解释时差点夜|全部点夜零时差相关中位|可解释集合最优滞后中位(min)|P5–P95(min)|',
           '|---|---:|---:|---:|---:|']
    for v in main:
        r=active[active.variant==v].iloc[0]
        lines.append(f'|{v}|{int(r.lag_interpretable_count)}|{r.slow_corr_zero_median:.3f}|{r.interpretable_lag_median_min:g}|{r.interpretable_lag_p05_min:g}–{r.interpretable_lag_p95_min:g}|')
    lines+=['',f'正值表示输出比 raw 晚；最优相关只作为时差诊断，绝不替代原时间轴的相关分数。current 只有 {int(current.lag_interpretable_count)}/{int(current.eligible_point_nights)}（{100*current.lag_interpretable_count/current.eligible_point_nights:.2f}%）点夜可解释为高相关波形的时差，其余 {int(current.lag_uninterpretable_count):,} 不能统一说成晚 2 分钟。current 可解释集合峰谷事件召回中位约 {current.event_recall_median_interpretable:.3f}，峰谷绝对时差 P90 的跨点夜中位约 {current.event_abs_p90_min_median_interpretable:.1f} 分钟，也说明并非简单整体平移。','',
            '同一可解释集合的成对比较，避免换一批点造成假改善：','',
            '|候选|双方可解释点夜|current滞后中位|候选滞后中位|逐点滞后变化中位|current零时差相关|候选零时差相关|',
            '|---|---:|---:|---:|---:|---:|---:|']
    for v in main[1:]:
        r=pairactive[pairactive.variant==v].iloc[0]
        lines.append(f'|{v}|{int(r.both_lag_interpretable)}|{r.slow_best_lag_min_current_median:g}|{r.slow_best_lag_min_variant_median:g}|{r.paired_lag_change_median_min:g}|{r.slow_corr_zero_current_median:.4f}|{r.slow_corr_zero_variant_median:.4f}|')
    lines+=['','关闭所有时间滤波后，modal_only 全部点夜的零时差相关中位仍只有约 0.306，说明主体波形差异不能靠整体平移修复，也不能仅靠去掉 W3 解决。', '',
            '## 窗口退出与表观延迟混淆','',
            '源码以 gate>=1 决定 S1/S2 是否参与；一旦 gate<1，两者直接旁路，虽然模态 gate 本身仍在渐退。十夜有 4,892 个有效点夜退出边界事件，current 最大单帧跳 1.559 px，11 个≥1 px，其中3个 raw 同帧变化<0.2 px。current 与 no_s1/no_s2 的差值在退出后全为精确0，证实后处理状态直接消失。退出前差值绝对P95分别0.118/0.0208 px。','',
            '关闭 W3 后退出最大单帧跳 2.458 px，41 个≥1 px；这也包括被去掉滤波后暴露的噪声/模态变化，不能全部归因 S2。边界跳变应单独修正、测试，不应通过移动曲线掩盖。计数为点×夜事件，同一设备同一时刻的多个点不是独立物理事件。','',
            '## 渐退修复与 08:00 窗口诊断','',
            'current_fade07 在 23:20–07:00 的全部有限值与 finite mask 均与 current 精确一致。4,892 个退出 full gate 的点夜中，单步跳变绝对P95由0.328降至0.163 px，最大由1.559降至0.762 px，≥1 px数量从11降为0。这证明软件切换不连续被缓解，不代表修复了夜间相位迟滞。','',
            '扩大到完整 06:50–07:30 窗口（4,971 合格点夜），≥1 px输出单步数量为 current 2,811、fade07 2,415；窗口最大单步均为5.187 px。渐退结束后原始尺度的波动仍然回来，因此不能用第一帧的改善代表整个尾段。输出单步及 raw 同帧差异也包含 W3 的时间响应，不能一概称为凭空产生的真实物理事件。','',
            '将 X 结束时间延至08:00的诊断，只是把退出边界移后：4,344 个可观测08退出事件，end08最大2.272 px、8个≥1；fade08最大1.154 px、1个≥1。07:50–08:30完整尾窗只有4,448合格点夜，其最大单步仍约5.58 px。11/16 08:00之后数据结束，末夜08退出/08:20尾段不可评价；没有把这部分当通过。','',
            '详见 latency_transition_summary.json/csv 和逐点夜明细。最终窗口源码重建/重放的288份输出、状态和配置SHA与绘图分析前相同，见 window_final_rebuild_verification.json；不需要用改变后的数据替换已有结论。','',
            '两张实测例图保留绝对X和真实采集时间：plots/latency_delay_example.png（右线YD3104，11-06夜；本例范围5.19 px>2，仅说明2→1分钟延迟，不能当达标示范）；plots/latency_boundary_example.png（左线ZD1601，11-11夜；07:00:26 raw−0.036/current+1.110/fade+0.556 px）。latency_plot_examples.json记录源文件和选择方法。','',
            '## 指标如何复用','',
            '`tools/latency_metrics.py::compute_metrics(timestamp_ms, raw_x, corrected_x)` 可直接接新候选。原生/5点居中中值评估波形分别报告零时差相关和±10分钟最佳相关；居中中值只用于离线评估，不参与算法。栅格以每个评价窗首帧为锚，按最近一分钟槽匹配，避免59.995秒跨整分的毫秒抖动造成假缺帧；事件时差保留真实时间。缺测不插值，真实重复槽剔除（最终15版本均无此重复）；不足幅值、弱相关和边界最优均标不可解释。','',
            '峰谷要求两边连续支持和局部显著性，同极性±10分钟一对一匹配；不匹配事件保留在召回率中。斜率方向在原时间轴评价，输出趋平按不一致计；不先平移再声称保形。','',
            'CLI：`python tools/latency_analyze.py --variant no_w3`；结果目录默认 `results/no_w3`，可用 `--results-root` 指定。`latency_compile_report.py` 汇总所有已完成结果，`latency_boundary_audit.py` 复现边界统计，`latency_native_audit.py` 运行原生分量证据。','',
            '主输出：`latency_variant_summary.csv`、`latency_paired_comparisons.csv`、各版本 `latency_*_point_nights.csv`、`latency_native_summary.json`、`latency_boundary_summary.json`。各版本的 JSON 记录源数据与输出路径。','',
            '结论边界：这些实验能够证实滤波迟滞及可重复的形状变化，不能独立确认真实位移被保留。1–2 px 范围达标、95% 点夜通过与物理安全是不同条件；本十夜被用于比较候选，后续仍需独立时间段/物理事件验收。','']
    (reports/'latency_findings.md').write_text('\n'.join(lines),encoding='utf-8')
    print(f'Wrote {len(summary)} variant-window summaries and {len(paired)} paired comparisons.')

if __name__=='__main__':run()
