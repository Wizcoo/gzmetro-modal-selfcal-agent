"""Chinese plots and readable report for the frozen YD1102 stage audit."""
from pathlib import Path
import os,sys,importlib.util,json
ROOT=Path(__file__).resolve().parents[1];REPORT=ROOT/'reports';PLOT=ROOT/'plots'
os.environ['MPLCONFIGDIR']=str(PLOT/'.yd_mplconfig')
CACHE=Path(r'C:\Users\12750\AppData\Local\uv\cache\archive-v0');ABI=f'cp{sys.version_info.major}{sys.version_info.minor}'
for module in ['matplotlib','contourpy','cycler','fontTools','kiwisolver','packaging','pyparsing','PIL']:
    if importlib.util.find_spec(module):continue
    for package in CACHE.iterdir() if CACHE.exists() else []:
        c=package/module
        if not c.exists():continue
        native=list(c.rglob('*.pyd')) if c.is_dir() else []
        if any('.cp3' in p.name and ('.'+ABI+'-') not in p.name for p in native):continue
        sys.path.append(str(package));break
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
import pandas as pd,numpy as np
from datetime import datetime,timezone,timedelta
TZ=timezone(timedelta(hours=8))
font_manager.fontManager.addfont(r'C:\Windows\Fonts\msyh.ttc')
plt.rcParams.update({'font.family':font_manager.FontProperties(fname=r'C:\Windows\Fonts\msyh.ttc').get_name(),'axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False})

def main():
    d=pd.read_csv(REPORT/'yd_stage_trace.csv');m=pd.read_csv(REPORT/'yd_stage_metrics.csv');v=json.loads((REPORT/'yd_stage_verification.json').read_text(encoding='utf8'))
    t=[datetime.fromtimestamp(x/1000,TZ) for x in d.timestamp]
    fig,axes=plt.subplots(4,1,figsize=(15,13),sharex=True,layout='constrained',height_ratios=[2.4,2.4,2,1])
    specs=[
        [('raw','数据库 raw X','#7c8791'),('database_calX','数据库 calX','#347ab4'),('current_fade07','新算法最终 X','#c44e3a')],
        [('W3_input','W3 后输入','#77818d'),('same_history_modal_core','同一历史：模态核心后','#97529c'),('same_history_after_S2','再经 S2','#cb8733'),('current','再经 S1（最终）','#c44e3a')],
        [('delta_W3','W3 新增量','#77818d'),('delta_modal','模态新增量','#97529c'),('delta_S2','S2 新增量','#cb8733'),('delta_S1','S1 新增量','#248879')]]
    titles=['三条业务曲线：原始、数据库原算法、新算法','逐级定位：保持同一套 W3 历史和当前输入','每环节新增量：正值抬高、负值压低；四项之和 = 最终 − raw']
    for ax,series,title in zip(axes[:3],specs,titles):
        for col,label,color in series:ax.plot(t,d[col],label=label,color=color,lw=1.05)
        ax.set_title(title,loc='left',fontsize=12);ax.set_ylabel('X（pixel）' if ax!=axes[2] else '新增量（pixel）')
        ax.legend(loc='upper left',bbox_to_anchor=(1.01,1),fontsize=9)
    axes[2].axhline(0,color='#999999',lw=.7)
    axes[3].plot(t,d.valid_input_count,color='#476a79',lw=1);axes[3].set_ylim(0,53);axes[3].set_ylabel('有效点数 / 51')
    axes[3].set_title('输入可见性（有效不等于独立物理正确）',loc='left',fontsize=11)
    for ax in axes:
        ax.grid(alpha=.16);ax.ticklabel_format(axis='y',style='plain',useOffset=False)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M',tz=TZ));ax.xaxis.set_major_locator(mdates.HourLocator(interval=1,tz=TZ))
        ax.set_xlim(datetime(2026,11,6,23,tzinfo=TZ),datetime(2026,11,7,7,tzinfo=TZ))
        ax.axvline(datetime(2026,11,7,1,45,tzinfo=TZ),color='#8f8484',ls=':',lw=.8)
    axes[3].set_xlabel('北京时间；23:00—07:00；未平移时间、未重定基准、未额外平滑')
    fig.suptitle('YD1102 负优化定位｜右线 780639298317｜2026-11-06夜\n首先放大发生在模态核心；本例 S2、S1 均略微减轻放大',fontsize=15)
    fig.savefig(PLOT/'yd_stage_decomposition.png',dpi=170);plt.close(fig)
    summary=m[m.window=='23_07'].set_index('name')
    labels={'raw':'数据库 raw X','W3_input':'W3后输入','same_history_modal_core':'同一历史模态核心','same_history_after_S2':'再经过 S2','current':'再经过 S1，最终输出','database_calX':'数据库 calX','modal_only':'关闭W3/S2/S1，重新独立学习','no_w3':'关闭W3，保留S2/S1，重新独立学习'}
    rows='\n'.join(f'|{label}|{summary.loc[k,"p2p"]:.6f}|{summary.loc[k,"p95p5"]:.6f}|' for k,label in labels.items())
    extrema=d.loc[d.current.idxmin()]
    check_max=max(v['reconstruction_checks'].values())
    report=f'''# YD1102：负优化首先出现在哪一层

**结论：本例首先把波动放大的是“经过W3历史学习后的模态核心”，不是后面的S2共模中位数，也不是S1弱阻尼。** S2和S1在本例反而略微缓解放大。关闭W3并重新学习的整条原生回放没有出现同样放大，说明需要继续检查W3改变后的历史模态/当前输入关系，不能把原因简化成“中值滤波自身把波峰拉大”。

对象为右线780639298317/YD1102，2026-11-06夜。按用户新口径23:00—次日07:00，共479个有效样本。此例修后max−min仍为1.836546 pixel，未超过普通点2 pixel，但P95−P5从raw的1.017261升至1.473360，确实存在观测幅度放大。

## 同一条链的逐级数值

|阶段或对照|23–07 max−min（pixel）|23–07 P95−P5（pixel）|
|---|---:|---:|
{rows}

前五行是同一套W3历史、同一当前输入的逐级路径。最后两行是重新独立学习的消融，仅可比较整条配置，不可直接相减当作某个组件新增量。P95跨度与max−min也不能按阶段相加；逐帧新增量才满足精确可加关系。

## 最深波谷的逐项解释

2026-11-07 **01:45:00.119**：

|环节|值或新增量（pixel）|
|---|---:|
|原始X|{extrema.raw:.9f}|
|W3新增量|{extrema.delta_W3:+.9f}|
|W3后输入|{extrema.W3_input:.9f}|
|模态新增量|{extrema.delta_modal:+.9f}|
|模态核心输出|{extrema.same_history_modal_core:.9f}|
|S2新增量|{extrema.delta_S2:+.9f}|
|S1新增量|{extrema.delta_S1:+.9f}|
|最终输出|{extrema.current:.9f}|

原始约−0.6565，W3只改了+0.0148；核心模态又向下减了约0.9582，才形成额外深谷。S2抬回0.0519，S1再抬回0.0979。该帧49/51个输入有效，不存在全设备大面积失效才开始修正的现象；但单凭有效标志仍不能排除个别跟踪异常。

## 不是仅有一个尖峰

以“模态新增量绝对值≥0.25 pixel”作为**定位时间段的诊断刻度，不是新算法门限**，01:31:00.106—02:42:00.167连续72帧都满足，中位新增量−0.59936 pixel；00:48—01:12还有25帧连续压低。最深谷不是孤立一帧造成的P95假象。具体哪个历史夜、哪些空间点导致估计关系偏移，需要结合模态矩阵和点级干预；本文件不凭相关性把责任归给某一个测点。

该夜S2对YD1102的新增量仅在−0.02897至+0.05533 pixel之间，无法解释核心约−0.96 pixel的压低。S1最终是相邻状态与当前输入的凸组合，对全链样本可平滑，但不构成“最终一定比raw能量小”的保证。

## 这个结论怎样核验

没有执行新DLL，也没有修改算法或原始数据。利用已冻结原生`no_s2`输出，在gate=1且状态连续处反解已知S1递推：

`core[t] = y[t−1] + (y[t]−y[t−1]) / (1−exp(−Δt/1.5min))`。

非完整门值、缺口和非有限状态均按源码分支处理。对恢复出的核心按原源码复算S2（前30完整门值帧基准、中位数共同偏移、15帧中位数、0.55系数），再复算S1。全{v['frames']}帧×{v['markers']}点与已有`no_s1/current`原生输出最大差 **{check_max:.3g} pixel**；用已有`no_s1`直接正向S1与`current`差为0。这使“核心、S2、S1贡献”成为可逐帧复核的代数分解，而不是目测猜测。

本点本夜数据库calX与raw-fed `modal_only`最大差3.89×10⁻¹⁵ pixel，表明这个对照在此例吻合；不据此宣称现场所有设备始终运行该配置。

`modal_only`实际关闭W3、S2、S1；`no_temporal`关闭W3、S1但保留S2。它们各自从11/02连续输入独立学习历史，不能当作current共享历史的中间结果。配置、源文件哈希与重建核验见`yd_stage_verification.json`。

## 产物

- `plots/yd_stage_decomposition.png`：中文四面板，业务三曲线、同历史阶段、逐项新增量、有效点数。
- `reports/yd_stage_core.npz`：本夜全部51点的raw、W3、恢复核心、S2后、最终和gate，用于进一步独立矩阵复核。
- `yd_stage_metrics.csv`：22–08、23–07、23:20–07全部配置与阶段指标。
- `yd_stage_trace.csv`：600个原始时间帧的逐级值及精确贡献，不插值。
- `yd_stage_extreme_decomposition.csv`：各窗口各阶段极值时刻的完整分解。
- `yd_stage_persistent_component_blocks.csv`：固定诊断刻度下的连续贡献区间。

三夜历史与算法约束能减少某些失配，但不是当夜每个测点、每个时刻、每项输出指标的非放大定理。本例已经确定应查模态核心和W3相关的历史/输入关系；尚未凭本阶段审查区分单一大点、少量离群、整体空间模式变化的责任。
'''
    (REPORT/'yd_stage_review.md').write_text(report,encoding='utf8')
    print(json.dumps({'report':'reports/yd_stage_review.md','plot':'plots/yd_stage_decomposition.png'},ensure_ascii=False))

if __name__=='__main__':main()
