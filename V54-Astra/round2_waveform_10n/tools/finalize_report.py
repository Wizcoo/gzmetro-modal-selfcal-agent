"""Package evidence without source databases, replay binaries, or runtime DLLs."""
from pathlib import Path
import hashlib,html,json,zipfile,shutil
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    summary=pd.read_csv(ROOT/'reports/range_summary.csv')
    point=pd.read_csv(ROOT/'reports/range_point_nights.csv',dtype={'device':str})
    profiles=['current','current_fade07','current_fade08','no_w3','no_w3_end08','no_w3_tau05','no_temporal','no_temporal_s2_070','no_temporal_s2_085']
    labels={'current':'第一轮 Astra','current_fade07':'07:00 增强渐退候选','current_fade08':'修正延至08:00＋渐退','no_w3':'关闭 W3，保留 S1','no_w3_end08':'关闭 W3＋修正延至08:00','no_w3_tau05':'关闭 W3＋S1 tau=0.5min','no_temporal':'关闭 W3/S1','no_temporal_s2_070':'无时间滤波＋S2=0.70','no_temporal_s2_085':'无时间滤波＋S2=0.85'}
    table=['|方案|完整22–08 分类通过|活跃23:20–07 分类通过|完整夜全部点≤1px|活跃段全部点≤1px|','|---|---:|---:|---:|---:|']
    for p in profiles:
        s=summary[summary.profile==p].set_index('window');f,a=s.loc['full'],s.loc['active']
        table.append(f'|{labels[p]}|{int(f.pass_class)}/{int(f.n)} = {f.pass_class_pct:.2f}%|{int(a.pass_class)}/{int(a.n)} = {a.pass_class_pct:.2f}%|{f.pass1_pct:.2f}%|{a.pass1_pct:.2f}%|')
    table='\n'.join(table)
    selected=point[(point.profile.isin(['current','current_fade07','current_fade08','no_w3'])) & point.eligible]
    selected[~selected.pass_class].to_csv(ROOT/'reports/selected_range_failures.csv',index=False)
    rows=[]
    for keys,g in selected.groupby(['profile','window','line','night','special_j']):
        row=dict(zip(['profile','window','line','night','special_j'],keys));row.update(n=len(g),passed=int(g.pass_class.sum()),pass_pct=100*g.pass_class.mean(),under1=int(g.pass1.sum()));rows.append(row)
    pd.DataFrame(rows).to_csv(ROOT/'reports/selected_by_line_night_type.csv',index=False)
    readme=f'''# V54-Astra 第二轮：十夜波形与延迟回测

本轮完成了十个日历夜、全部 12 台设备 524 点的原生回测及已知事件注入。**未达到“完整夜 95% 范围通过且物理波形保持”的交付条件。** 不能把活跃段 96.33% 范围通过写成整夜达标，也不能把曲线压小写成物理保真。

确认了两类现象：W3＋S1 引入约两分钟的信号滞后；07:00 的 S1/S2 硬旁路会引入额外边界跳变。已提供退出增强渐退的可编译候选及独立恢复测试。去 W3 是减约一分钟的折中候选，完整夜范围反而变差；本轮不将其设置为默认。加大 S2 至0.70/0.85收益很小且会削弱共同事件，因此不采用为推荐增强。

## 数据与判定

- 评价夜号 **2026-11-06–2026-11-15**；完整窗口22:00至次日08:00，结束不含08:00；预热历史从11/02开始。所有 profile 独立按时间顺序学习，不使用未来帧，也不按当夜最终范围回缩。
- 左线11/06整夜缺失，保留缺测，不用其他日期替补。524×10=5,240个名义点夜；完整夜合格4,968，活跃段合格4,963。有效点须ROI=1、X有限且覆盖≥80%；不插值。
- x/y 已由用户确认是pixel；不乘scale。`max_frame_dev=0`。判定用真实 **max−min**，不是P95−P5。分类门限沿用普通点≤2px、J/XJ≤1px；另单列全部测点≤1px的偏好。
- 19个已提取源数据库SHA与上一轮完全一致。右线file4读到11/02 18:39，早于预热起点；没有漏入本期的新旋转文件。受损库的只读恢复/健康副本与可验证范围沿用第一轮，详见上级`reports/data_inventory.json`。源库不写入。
- 本十夜用于候选比较，属于回顾性回测，不是未见未来数据或独立物理验收。每次输出保留原始时间戳；时间戳相同不代表没有相位延迟。

## 范围结果

{table}

完整明细见 `reports/range_point_nights.csv`，逐夜见 `range_by_night.csv`，按线路/日期/J类型见 `selected_by_line_night_type.csv`。失败明细 `selected_range_failures.csv` 未删除尖峰或大幅点。左线780638327479/ZXJ6在11/09仍有15.654px修后范围，不能被总体通过率掩盖。

![范围取舍](plots/range_tradeoff.png)

## 延迟与波形

原生 current 平均Process约9.80微秒/设备帧；分钟级滞后主要来自时间滤波。W3在单调段晚一帧；S1 tau=1.5min再增加约1.055min低频滞后。已知阶跃经W3＋S1达到50%晚2分钟，95%晚5分钟。它是因果处理，不等待未来帧，但输出波形仍晚。

真实点夜只对幅值足够、高相关且时差最优值不在搜索边界的集合解释延迟。current与no_w3的同一180个可评估点夜中，滞后中位从2min变为1min，157个点夜滞后下降；去W3/S1则约0min，但范围通过率下降。current全部4,963个合格点夜中仅232个满足可解释延迟筛选。**这不代表所有点都晚两分钟或去滤波即保真。** 大多数raw→修后曲线的差异包含模态扣除，无法解释成简单平移。原时间轴相关、峰谷保留/方向与事件时差以 `reports/latency_findings.md` 和CSV为准；评估用的居中滤波没有进入在线算法。

当前07:00首次退出全门值的4,892个点夜边界中，输出单步最大1.559px，11个≥1px（其中3个raw同帧变化<0.2px）。fade07候选把首次退出的最大跳变降至0.762px、≥1px为0，P95从0.328降至0.163px。活跃段输出与第一轮逐位相同。

渐退仅把增强撤销分摊到既有20min退出过程，**没有消灭总补偿恢复趋势**，静止平台也可能在退出期出现缓慢变化。把结束时刻延到08:00也只是移动边界。完整退出阶段与08:20统计均保留；最后一夜11/16 08:00以后无输入，因此不能声称末夜08:00–08:20已验证。不要把退出阶段趋势当成真实运动。

独立窗口实验中，raw静止平台的0.4125px总恢复量在fade后仍存在；超过3min的缺口会按既有规则清空增强缓存，缺口后仍可恢复跳变。fade阶段core和增强估计都继续变化，不能普遍保证严格单调或每帧只变化旧跳变量的1/20。详见 `reports/design_window_review.md`。这也是本候选没有被标为现场可交付版本的原因。

## 已知事件的限制

原生已学习状态的1,200组成对注入，比较“相同控制输入”与“加已知阶跃/斜坡/脉冲的输入”，不把现场未知raw当成物理真值。单学习点+0.75px阶跃约保留93%，3点局部簇可仅保留78%；落入已学共同模态的整体同相阶跃可被几乎全部扣掉。若共同方向不在模态，S2=.55仍可把共同阶跃稳态压到45%，S2=.85只剩15%。因此只有坐标观测不能保证区分真实共同位移和成像共同扰动。

对“学习点共同移动而参考点未动”的合成输入，参考点也可能被共同补偿带动。增大S2会加剧这一类串扰。详见 `reports/design_native_events_review.md` / `design_native_events.json`，包含±阶跃、斜坡、脉冲、未注入点响应和全部逐帧记录。

普通固定压幅虽可数学上保留峰谷时间，也会等比例削弱真实位移；动态压幅还可在静平台造出趋势。本轮没有用这类缩放刷95%通过率。若现场“1px约4mm”成立，1px也不能直接等同于3mm报警安全，且该换算尚无逐点独立标定。

## 可审查源码与配置

`src/window_candidate/ModalSelfCal.cpp`、`.h` 是独立候选，未覆盖第一轮 `../src` 或用户原V54。`CandidateProfiles.h` 提供三个与已测配置对应的工厂函数。两个新参数默认关闭，以便显式复现实验：

```cpp
ModalSelfCalConfig cfg;
cfg.max_frame_dev = 0;
cfg.fade_x_enhancements_with_gate = true; // current_fade07：仅退出增强渐退
cfg.x_apply_end_h = 0;                  // 沿用原07:00；32仅用于end08诊断
// no_w3 为单独的低延迟实验：cfg.enable_x_w3_filter = false;
```

fade逻辑只在退出坡段继续更新S1/S2，再按gate混回模态核心输出；进入坡段不变。X结束时刻只覆盖X轴，Y沿用原配置。新增参数纳入配置指纹；旧快照会被拒绝，必须用该候选从原始历史重建。新增退出配置禁止坡段跨中午换夜；已有基线默认行为保持逐字节一致。

原生核验包括：全部profile的Y逐位一致、时间戳/有限掩码一致、默认参数12设备逐字节复现；真实19,250帧中途恢复，后续9,624帧X/Y和状态一致；静止/阶跃退出、坡段中途恢复、非法配置和配置不匹配拒绝。源SHA、编译命令、实际配置见 `build/native_window_manifest.json` 与 `reports/window_native_*.json`。这验证实现与状态连续性，不替代物理事件验收。

## 文件索引与复现

- 图册 `plots/index.html`：波形/延迟示例、原生事件、全部524测点×10夜范围图。
- 范围：`tools/range_metrics.py`；波形：`tools/latency_analyze.py --variant current`。
- 原生回放：`tools/native_replay.py`、`native_supplemental.py`、`native_window.py`。每组按完整11/02起历史独立学习。
- 原生已知事件：`reports/design_native_events.py`；边界：`tools/latency_boundary_audit.py`及transition工具（见索引）。
- 此报告包不含源数据库、完整回放二进制和运行DLL；它们仍在V54-Astra原目录。交付为审查与离线候选，没有现场替换。
'''
    (ROOT/'README.md').write_text(readme,encoding='utf8')
    for source_image in (ROOT/'reports').glob('*.png'):
        shutil.copyfile(source_image,ROOT/'plots'/source_image.name)
    imgs=sorted((ROOT/'plots').glob('*.png'))
    image_html='\n'.join(f'<section id="{html.escape(p.stem)}"><h2>{html.escape(p.stem)}</h2><a href="{html.escape(p.name)}"><img loading="lazy" src="{html.escape(p.name)}" alt="{html.escape(p.stem)}"></a></section>' for p in imgs)
    report_files=[p for p in sorted((ROOT/'reports').iterdir()) if p.suffix in ['.md','.json','.csv'] and not p.name.endswith('_point_nights.csv')]
    links='\n'.join(f'<li><a href="../reports/{html.escape(p.name)}">{html.escape(p.name)}</a></li>' for p in report_files)
    index=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>V54-Astra 十夜波形核验</title><style>body{{max-width:1380px;margin:36px auto;padding:0 24px;font:16px/1.7 system-ui;background:#f5f7f8;color:#1e303b}}h1{{font-size:30px}}section{{background:white;padding:20px;margin:28px 0;border-radius:10px}}img{{max-width:100%;height:auto}}a{{color:#086d78}}.note{{padding:18px;background:#fff1d8;border-left:4px solid #d59432}}table{{border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #ccd8df}}</style><h1>V54-Astra · 十夜波形与延迟核验</h1><p>2026-11-06–11-15｜12台设备、524点｜左线11/06缺测如实保留</p><p class="note">完整夜“95%范围达标且物理波形保持”尚未通过。滤波约两分钟滞后已确认；退出增强渐退候选已实现。范围、相位和物理事件响应分别评价。</p><p><a href="../README.md">完整结论与源码配置</a> · <a href="../reports/range_point_nights.csv">全部点夜范围数据</a> · <a href="../reports/selected_range_failures.csv">失败清单</a></p>{image_html}<section><h2>可复核数据与报告</h2><ul>{links}</ul></section></html>'''
    (ROOT/'plots/index.html').write_text(index,encoding='utf8')
    files=[ROOT/'README.md',ROOT/'plots/index.html']+imgs+list((ROOT/'plots').glob('*.json'))
    files += [p for folder in ['src/window_candidate','baseline_src','tools','reports'] for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ['.cpp','.h','.inc','.py','.md','.json','.csv','.png'] and '__pycache__' not in p.parts and p.name not in ['package_manifest.json','final_verification.json']]
    files += list((ROOT/'build').glob('*manifest.json'))
    files=sorted(set(files));target=ROOT/'V54-Astra_十夜波形与延迟核验.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for p in files:assert hashlib.sha256(z.read(p.relative_to(ROOT).as_posix())).hexdigest()==sha(p)
    manifest=dict(package=str(target),sha256=sha(target),bytes=target.stat().st_size,files=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p)) for p in files])
    (ROOT/'reports/package_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(package=str(target),files=len(files),bytes=target.stat().st_size),ensure_ascii=False))
if __name__=='__main__':main()
