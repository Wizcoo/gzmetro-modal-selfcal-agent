"""Summarize frozen history-length diagnostics; align quiet labels without tuning."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / 'reports'

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def group(rows):
    return {str(h): {
        'point_nights': len(d),
        'range_le_1': int((d['range'] <= 1 + 1e-9).sum()),
        'range_gt_1': int((d['range'] > 1 + 1e-9).sum()),
        'range_gt_raw_by_0p1': int((d['range'] > d.raw_range + .1).sum()),
        'median_range': float(d['range'].median()) if len(d) else None,
    } for h, d in rows.groupby('history_length')}

def main():
    summary = json.loads((OUT/'history_length_summary.json').read_text(encoding='utf8'))
    df = pd.read_csv(OUT/'history_length_point_metrics.csv', dtype={'device':str})
    inventory = json.loads((OUT/'quiet_inventory_all_point_baseline.json').read_text(encoding='utf8'))
    lookup = {(r['line'],r['device'],r['night'],r['marker']): r for r in inventory}
    current = df[df.history_length == 3]
    max_error = 0.
    for row in current.itertuples(index=False):
        other = lookup[(row.line,row.device,row.night,row.marker)]
        assert row.valid == other['raw']['valid']
        if pd.notna(row.raw_range):
            max_error = max(max_error, abs(row.raw_range-other['raw']['range']))
        quiet = bool(row.valid >=384 and row.raw_range <=1+1e-9)
        assert quiet == other['raw_quiet']
    assert max_error < 1e-12
    aligned = df[(df.valid >=384)&(df.raw_range <=1+1e-9)]
    assert aligned.raw_quiet.all()
    assert len(aligned)==int(df.raw_quiet.sum())
    crossings = aligned[aligned['range'] >1+1e-9]
    case = df[(df.device=='780638349768')&(df.marker=='ZD4404')&(df.night=='2026-11-14')]
    artifacts = []
    for item in summary['artifacts']:
        path = Path(item['file'])
        assert sha(path) == item['sha256']
        with np.load(path) as z:
            keys = z.files
            for date in summary['test_nights_common_to_all_devices_and_lengths']:
                key = date.replace('-','_')
                tt = z[key+'_timestamp']; raw = z[key+'_raw']; w3 = z[key+'_w3']
                assert raw.shape==w3.shape==(len(tt),len(z['names']))
                assert np.all(np.diff(tt)>0)
                for h in [3,5,7]:
                    result = z[key+'_modal_h'+str(h)]
                    assert result.shape==raw.shape
                    assert np.array_equal(np.isfinite(raw),np.isfinite(result))
            artifacts.append({'file':str(path),'sha256':item['sha256'],'array_count':len(keys)})
    report = {
        'scope':'Re-aggregation of existing frozen 12-device, 6-common-night modal-only outputs; no model rerun or tuning.',
        'raw_definition':'ROI-masked input.npz x, pixel units, before W3 and before any correction; [23:00,next07:00) peak-to-peak over finite samples.',
        'raw_stats_match_quiet_inventory':{'point_nights_checked':len(current),'max_abs_range_difference':max_error,'valid_counts_and_quiet_labels_equal':True},
        'quiet_alignment':'quiet_inventory: valid>=384 and raw range<=1 pixel. The initial history_length raw_quiet additionally requires absolute 03–06 median minus 22–23 median<=0.5 pixel. Its definition is stricter, but the selected set happens to be exactly the same 74 point-nights in the six common nights; explicit set equality asserted.',
        'quiet_aligned_all_roles':group(aligned),
        'quiet_aligned_ordinary_J':group(aligned[aligned.role!='XJ']),
        'quiet_aligned_XJ_descriptive':group(aligned[aligned.role=='XJ']),
        'quiet_crossings':crossings.astype(object).where(pd.notna(crossings),None).to_dict(orient='records'),
        'specific_case':case.astype(object).where(pd.notna(case),None).to_dict(orient='records'),
        'arrays':artifacts,
        'array_contract':'Each NPZ stores exact marker order names and each night YYYY_MM_DD_timestamp/raw/w3/modal_h3/modal_h5/modal_h7. Times span the evaluate helper 22–08 window. Applied modal correction (including gate) = w3-modal_hN. Full ungated modal coefficients are not separately serialized. Absolute pixel coordinates are retained.',
        'empty_transition_csv_header_restored':True,
        'report_script_sha256':sha(__file__),
    }
    # The strict observed three-large-to-quiet subset is empty. Keep a valid schema.
    assert not df.three_large_then_quiet.any()
    df.head(0).to_csv(OUT/'history_length_three_large_then_quiet.csv',index=False,encoding='utf-8-sig')
    (OUT/'history_length_quiet_alignment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    lines = [
        '# 3 / 5 / 7 夜历史长度独立诊断', '',
        '不建议把“增加历史夜数”当作本夜关系失效保护。5/7 夜有局部收益，也出现新的平稳点放大；暂保留 3 个最近合格夜作为默认，5/7 夜可用于影子对照。这个建议不是“3 夜最优”的证明。', '',
        '范围：12 台设备，三种长度共同可用的 2026-11-10 至 11-15 共 6 夜；每夜评价 23–次日07。3144 个点夜中，3130 个有效样本不少于 384；14 个低覆盖点夜仍保留在明细。历史均为此前合格夜 22–02，基准 22–23，本夜 23 点冻结；左线缺失的 11/06 没有补造。每种长度重新计算学习点、模态和历史能量 gain。', '',
        f"纯 Python 模态重建与冻结原生 3 夜基准核对 72 个设备夜，最大差 {summary['native_baseline_max_error']:.3g} pixel。这里只评价模态核心，未叠加 S2/S1，也没有执行新 DLL 或改动交付源码、状态、数据库。", '',
        '| 历史长度 | 范围≤1 / 3130 | 范围≤2 / 3130 | 范围中位数 | 范围 P95 | 晚间绝对偏移中位数 |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for h in [3,5,7]:
        s=summary['summary'][str(h)]
        lines.append(f"| {h} | {s['range_le_1']} | {s['range_le_2']} | {s['median_range']:.4f} | {s['range_p95']:.4f} | {s['median_abs_late_offset']:.4f} |")
    lines += ['', '相对 3 夜，5 夜有 203 个点夜的范围减少超过 0.1 pixel，也有 207 个增加超过 0.1；7 夜分别为 258 / 241。晚间绝对偏移减少超过 0.1 的点夜分别为 88 / 95，增加超过 0.1 为 72 / 57。整体变化很小，并非单向改善。', '',
        '晚间偏移定义：输出 03–06 中位数减去原始 raw x 在 22–23 的中位数。范围为 max−min。raw 是 input.npz 中 ROI 有效的原始 x，单位 pixel，未经 W3，不是数据库 calX。', '',
        '## 与平稳清单完全一致的口径', '',
        f"本次重新按 quiet_inventory 的“raw 范围≤1 且有效≥384”固定口径汇总；共同 6 夜共有 {len(aligned)//3} 个平稳点夜，其中普通/J {len(aligned[aligned.role!='XJ'])//3}、XJ {len(aligned[aligned.role=='XJ'])//3}。全 3144 个点夜的 raw 范围和有效计数逐一核对，最大范围差 {max_error:.3g} pixel，平稳标签全部一致。", '',
        '初版 history_length_summary.json 中 quiet_summary 另加了“晚间 raw 偏移绝对值≤0.5”的限制。定义更严格，但本次共同 6 夜恰好没有额外排除任何点：两种定义的集合逐一核对一致，均为 74 个点夜。对齐结果独立保存在 history_length_quiet_alignment.json；不回改已完成的模型计算。', '',
        '| 历史长度 | 对齐平稳点夜 | 模态范围>1 | 范围比 raw 大>0.1 |', '|---|---:|---:|---:|']
    for h in [3,5,7]:
        s=report['quiet_aligned_all_roles'][str(h)]
        lines.append(f"| {h} | {s['point_nights']} | {s['range_gt_1']} | {s['range_gt_raw_by_0p1']} |")
    lines += ['', '5/7 夜新增越 1 的点夜是同一案例：左线 780638349768 / ZD4404 / 2026-11-14，有效 480 帧。raw 范围 0.984994 pixel、晚间偏移 +0.349772 pixel，同时满足两种平稳定义。', '',
        '| 历史长度 | 模态范围 | 晚间偏移 | learn | gain | 相对 J 范围 | 相对 J 晚间偏移 |', '|---|---:|---:|---|---:|---:|---:|']
    for r in case.itertuples(index=False):
        lines.append(f"| {r.history_length} | {r.range:.6f} | {r.late_offset:+.6f} | {r.learn} | {r.gain:.6f} | {r.relative_J_range:.6f} | {r.relative_J_late_offset:+.6f} |")
    lines += ['', '增加历史长度改变了该点的 learn 身份（参与模态学习 → 非学习点回归），不只是对同一个模型多取几夜平均。此记录说明系统输出对历史长度存在非单调响应；尚未通过单因素干预把差异全部归因于身份切换。', '',
        '## 327479 / 11 月 12 日重点', '',
        '| 点 | 3/5/7 夜模态范围 | 3/5/7 夜晚间偏移 |', '|---|---|---|']
    focus=df[(df.device=='780638327479')&(df.night=='2026-11-12')]
    for name in ['ZXJ6','ZD4403','ZD4503','ZD4603','ZD4703','ZJ7','ZJ8']:
        d=focus[focus.marker==name].sort_values('history_length')
        if len(d):lines.append(f"| {name} | {' / '.join(f'{v:.3f}' for v in d['range'])} | {' / '.join(f'{v:+.3f}' for v in d['late_offset'])} |")
    lines += ['', 'ZXJ6 和 ZJ8 明显受益，但 ZD4603、ZD4703 和 ZJ7 的范围及晚间绝对偏移变大。增加历史可以改变某个失效案例的历史关系，不能判断本夜该关系是否适用，也不能保证普通点和参考点同时改善。XJ 的范围只作描述，不直接作为业务失败判据。', '',
        '严格观察分类“此前连续 3 个日历夜各 raw P95−P5≥1.5，本夜≤0.5、晚间偏移绝对值≤0.5、四夜均有效≥384”没有找到案例。这不能代表用户提出的极端情景已经通过；也不能据此说不存在较宽口径的强历史后平稳点。', '',
        '## 可复用产物与边界', '',
        '- history_length_point_metrics.csv：全部点夜、3/5/7 结果、历史日期、学习身份、gain、相对 J/XJ 差分。',
        '- history_length_reference_differences.csv：设备层参考差分；两个 vs3 文件为配对变化。',
        '- history_length_arrays_{left/right}_{device}.npz：12 设备逐帧绝对坐标，含 names 和每夜 timestamp/raw/w3/modal_h3/modal_h5/modal_h7；22–08 时间窗口。应用到输出的模态补偿可由 w3−modal_hN 精确恢复，包含门控；没有单独存储未门控系数。',
        '- history_length_summary.json / history_length_quiet_alignment.json：原生核对、来源 hash、历史资格与重新对齐的平稳统计。12 个 NPZ 已重读检查 hash、时间单调、形状和有限掩码。', '',
        '范围变小、能量变低、相对参考点差分变小，都不等于真实位移准确。历史长度的选择不能替代本夜适用性检查；本报告没有验证最终平滑链或新封装原生运行。', '']
    (OUT/'history_length_summary.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps({'quiet_all':report['quiet_aligned_all_roles'],'quiet_primary':report['quiet_aligned_ordinary_J'],'quiet_XJ':report['quiet_aligned_XJ_descriptive'],'crossings':report['quiet_crossings'],'max_raw_diff':max_error,'arrays_verified':len(artifacts)},ensure_ascii=False))

if __name__=='__main__':
    main()
