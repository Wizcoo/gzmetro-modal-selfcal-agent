"""Build the human entry point and a source/review package, without raw databases."""
from pathlib import Path
import hashlib, json, zipfile
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    reports=ROOT/'reports'
    df=pd.read_csv(reports/'metrics_point_nights.csv',dtype={'device':str,'night':str,'marker':str})
    for column in ['eligible','raw_range_target_pass','v54_range_target_pass','astra_range_target_pass',
                   'astra_lost_v54_repair_target','astra_broke_raw_range_target','v54_material_worsening','astra_material_worsening']:
        df[column]=df[column].astype('string').str.lower().eq('true').fillna(False).astype(bool)
    eligible=df[df.eligible]
    table=[]
    for split,label in [('diagnostic','11/05–11 开发检查'),('holdout','11/12–15 后期复核')]:
        for window,wlabel in [('active_2320_07','23:20–07:00'),('night_22_08','22:00–08:00')]:
            part=eligible[(eligible.split==split)&(eligible.window==window)]
            table.append(dict(period=label,window=wlabel,eligible=len(part),raw_pass=int(part.raw_range_target_pass.sum()),
                v54_pass=int(part.v54_range_target_pass.sum()),astra_pass=int(part.astra_range_target_pass.sum()),
                lost_v54=int(part.astra_lost_v54_repair_target.sum()),broke_raw=int(part.astra_broke_raw_range_target.sum()),
                new_material=int((part.astra_material_worsening&~part.v54_material_worsening).sum())))
    latest=df[df.night=='2026-11-15']
    latest[latest.eligible&~latest.astra_range_target_pass].to_csv(reports/'latest_night_failures.csv',index=False,encoding='utf-8-sig')
    latest[~latest.eligible].to_csv(reports/'latest_night_incomplete.csv',index=False,encoding='utf-8-sig')
    remaining=eligible[(eligible.split!='warmup')&eligible.astra_material_worsening]
    remaining.to_csv(reports/'remaining_waveform_regressions.csv',index=False,encoding='utf-8-sig')
    changed=eligible.copy()
    changed['astra_minus_v54_p95p5_px']=changed.astra_p95p5_units-changed.v54_p95p5_units
    changed['astra_minus_v54_p2p_px']=changed.astra_p2p_units-changed.v54_p2p_units
    changed=changed[(changed.astra_minus_v54_p95p5_px>1e-9)|(changed.astra_minus_v54_p2p_px>1e-9)]
    changed.sort_values('astra_minus_v54_p95p5_px',ascending=False).to_csv(reports/'increases_relative_to_v54.csv',index=False,encoding='utf-8-sig')
    examples=eligible[(eligible.device=='780639346578')&(eligible.marker=='YD2603')&
        eligible.night.isin(['2026-11-05','2026-11-06','2026-11-07'])&(eligible.window=='night_22_08')]
    known=[dict(night=r.night,v54=float(r.v54_p2p_units),astra=float(r.astra_p2p_units)) for r in examples.itertuples()]
    build=json.loads((ROOT/'build/manifest_astra.json').read_text())[0]
    for name,value in build['source_sha256'].items():assert digest(ROOT/'src'/name)==value
    tests=json.loads((reports/'test_runs.json').read_text())
    assert all(row['exit_code']==0 for row in tests)
    energy=json.loads((reports/'metrics_energy_audit.json').read_text())
    result=dict(status='OFFLINE_CANDIDATE_NOT_ALL_POINTS_MEET_TARGET',input_unit='pixel',
        target='nightly max-min: ordinary <=2 pixel; J/XJ <=1 pixel',max_frame_dev=0,
        validation_scope='11/02 22:00 through 11/16 08:00 Asia/Shanghai; 12 devices, 524 roster entries; left 11/06 missing',
        period_comparison=table,known_yd2603=known,source_sha256=build['source_sha256'],
        limitations=['Not every point-night reaches 2/1 pixel','No independent physical displacement truth or downstream x0/y0 integration validation',
            'Later-period review is not a strict blind test','fit_only and learned-row behavior retained; two inherited YD1102 spread increases remain'],
        new_material_regressions_vs_v54=int((eligible.astra_material_worsening&~eligible.v54_material_worsening).sum()),
        lost_existing_v54_repairs=int(eligible.astra_lost_v54_repair_target.sum()),
        corrupted_source_recovery='See data_inventory.json and data_supplied_copy_check.json')
    (reports/'delivery_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    rows='\n'.join(f"| {r['period']} | {r['window']} | {r['v54_pass']}/{r['eligible']} | {r['astra_pass']}/{r['eligible']} ({r['astra_pass']/r['eligible']:.2%}) |" for r in table)
    examples_text='\n'.join(f"| {r['night']} | {r['v54']:.3f} | {r['astra']:.3f} |" for r in known)
    readme=f'''# V54-Astra

已完成历史污染引起的回归过度修复的针对性修改，以及12设备连续回放和状态恢复验证。**这是离线候选；尚未达到“每天所有点都在2/1 pixel以内”，未部署。**

## 先看这里

- [完整图册：总览、重点反例、最新夜524点](plots/index.html)
- [最终源码](src/ModalSelfCal.cpp) / [接口和默认参数](src/ModalSelfCal.h)
- [算法依据与边界](reports/design.md)
- [全部逐点逐夜指标](reports/metrics_point_nights.csv)
- [最新夜未达标清单](reports/latest_night_failures.csv) / [覆盖不足](reports/latest_night_incomplete.csv)
- [仍存在的波形放大](reports/remaining_waveform_regressions.csv)
- [相对旧V54波动增加的全部记录](reports/increases_relative_to_v54.csv)
- [最新夜三曲线CSV.gz，12设备、314400行](exports/2026-11-15/manifest.json)
- [机器可读交付摘要](reports/delivery_summary.json)

## 口径与结果

用户确认x/y就是pixel，未换算scale。普通点目标为修后X整夜max−min≤2px；J/XJ点≤1px。`max_frame_dev=0`；该参数与整夜范围目标是不同概念。Y与**同配置V54离线回放**逐值一致，不冒充与现场另一版本/状态完全相同。

原V54数据来自指定源码独立编译回放。11/02–04用于预热，左线11/06夜缺失。仅覆盖达到80%的点夜计入以下分母。后期数据是时间复核，不是严格盲测。

| 时段 | 验收窗口 | V54达标点夜 | Astra达标点夜 |
|---|---|---:|---:|
{rows}

最新11/15夜：23:20–07:00为506/522达标，仍有16点未达标；22–08整夜为443/522，仍有79点未达标。另2个名单点覆盖不足，不能计作通过。全部检查期间没有丢失V54原有达标修复，也没有新增“比原始输入明显更差”的点夜。这里“明显”定义为P95−P5增加超过max(0.05px,原始P95−P5的10%)。部分点相对旧V54仍有小幅波动增加，全部列在上面的相对变化清单中，不声称所有曲线均逐点优于旧版。

YD2603（右线780639346578）的**22–08整夜max−min，单位pixel**：

| 夜号 | V54 | Astra |
|---|---:|---:|
{examples_text}

YD1102（右线780639298317）11/05、11/06的P95−P5仍从原始0.406/1.026变成约0.576/1.479，虽最大最小范围仍在2px内，仍作为未解决的波形放大列出。不能把范围达标等同物理波形保真。

## 改了什么

有效测点因spread/guard退出学习后，原代码仍会给它回归载荷。新增X专用跨夜能量检验，对有效、非学习且非fit_only的回归点按`gamma=clip(2*min(q_n),0,1)`收缩不可靠载荷，可靠载荷保持1；该分类与2px普通点/1px J点的验收分类不同，不按测点名修补，也没有把所有曲线硬截平。原W3/模态/S2/S1链保留，零gate仍含原有W3。状态缓存、完整指纹、导入事务和断采缓存同时修复。

验证包括原生C++全流回放、3955项历史机制检查、原V54测试、8个真实重启检查点及损坏/不兼容状态拒绝。污染合成场景中安静点范围从旧模态6.300px恢复到原始0.100px。证据见[test_runs.json](reports/test_runs.json)、[真实恢复](reports/test_real_restart_manifest.json)、[历史增益审计](reports/metrics_energy_audit.json)。

## 集成与复现

集成只需`src/ModalSelfCal.cpp`和`src/ModalSelfCal.h`，标准C++17；本次使用GCC原生执行验证。可用根目录CMakeLists创建静态库，或把cpp加入现有工程。新快照魔数为`MSC_STATE_V54_ASTRA_HISTORY1`，旧状态明确拒绝；应回放原始历史重建，不能改指纹后强行导入。

`tools/run_replay.py --variant both`编译并回放，`tools/analyze_history_guard.py`生成指标，`tools/run_tests.py`和`tools/run_real_restart.py`验证状态，`tools/plot_report.py`生成图册。脚本需要Python、NumPy/Pandas及图形依赖；数据准备脚本的原库路径与SHA记录于reports。build中的replay DLL是离线工具。

原算法目录和数据库未修改。baseline保存原源码，data保存只读抽取，results保存原生结果，reports/plots/exports是审查入口；被否决的限幅和硬剔除试验在experiments。

## 尚不能承诺

未取得独立位移真值，未联调下游x0/y0；历史代理能量边界不等于未来每日全点达标或现场安全认证。剩余超标及波形问题已经保留在清单中，不能据此直接宣布满足全部上线条件。
'''
    (ROOT/'README.md').write_text(readme,encoding='utf-8')
    paths=[ROOT/'README.md',ROOT/'CMakeLists.txt']
    for folder in ['src','tests']:
        paths += sorted(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.cpp','.h','.hpp'])
    paths += [ROOT/'tools'/n for n in ['run_tests.py','run_real_restart.py','replay.cpp','run_replay.py','analyze_history_guard.py']]
    paths += [reports/n for n in ['design.md','delivery_summary.json','metrics_groups.csv','latest_night_failures.csv',
        'remaining_waveform_regressions.csv','increases_relative_to_v54.csv','test_runs.json','test_astra.json','test_real_restart_manifest.json',
        'metrics_energy_audit.json','metrics_summary.json','original_source_integrity.json'] if (reports/n).exists()]
    package=ROOT/'V54-Astra_源码与核验.zip'
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(package) as z:assert z.testzip() is None
    manifest=dict(package=package.name,sha256=digest(package),files={str(p.relative_to(ROOT)):digest(p) for p in paths})
    (reports/'source_package_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(package=package.name,files=len(paths),periods=table),ensure_ascii=False))

if __name__=='__main__':main()
