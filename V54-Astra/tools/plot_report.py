"""Scientific pixel-domain replay figures and a local HTML figure index.

Run only after final full-device metrics have been frozen. No parameters are
chosen from these plots. Every latest-night marker is plotted, including
failures and missing observations. Gaps are never interpolated.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse, hashlib, html, importlib.util, json, math, os, struct, sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'plots'
os.environ['MPLCONFIGDIR']=str(OUT/'.mplconfig')
OUT.mkdir(parents=True,exist_ok=True)
# Reuse installed wheel caches; do not install packages or modify an environment.
CACHE=Path(r'C:\Users\12750\AppData\Local\uv\cache\archive-v0')
ABI=f'cp{sys.version_info.major}{sys.version_info.minor}'
for module in ['matplotlib','contourpy','cycler','fontTools','kiwisolver','packaging','pyparsing','PIL']:
    if importlib.util.find_spec(module):continue
    for package in CACHE.iterdir() if CACHE.exists() else []:
        candidate=package/module
        if not candidate.exists():continue
        native=list(candidate.rglob('*.pyd')) if candidate.is_dir() else []
        if any('.cp3' in p.name and ('.'+ABI+'-') not in p.name for p in native):continue
        sys.path.append(str(package));break
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

TZ=timezone(timedelta(hours=8))
COLORS=dict(raw='#707680',v54='#D47D24',astra='#087F8C')
LABELS=dict(raw='Raw X',v54='V54',astra='V54-Astra')
LINE_NAMES=dict(left='Left line',right='Right line')
WINDOW_NAMES=dict(night_22_08='22:00–08:00 full night',active_2320_07='23:20–07:00 active interval')
NIGHTS=[f'2026-11-{d:02d}' for d in range(2,16)]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':11,
                     'axes.labelsize':10,'axes.spines.top':False,'axes.spines.right':False,
                     'axes.grid':True,'grid.color':'#DFE3E6','grid.linewidth':0.5,
                     'savefig.facecolor':'white','figure.facecolor':'white','svg.fonttype':'none'})

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()

def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def write_json(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def bool_column(s):return s if s.dtype==bool else s.fillna(False).astype(str).str.lower().eq('true')
def finite_stat(a,kind='range'):
    v=a[np.isfinite(a)]
    if not len(v):return float('nan')
    return float(np.ptp(v)) if kind=='range' else float(np.percentile(v,95)-np.percentile(v,5))
def fmt(v):return 'n/a' if not np.isfinite(v) else f'{v:.3f}'

def read_output(path):
    with path.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    dt=np.dtype([('timestamp','<i8'),('x','<f8',(m,)),('y','<f8',(m,))])
    assert path.stat().st_size==8+n*dt.itemsize,('binary size',path)
    return np.memmap(path,mode='r',offset=8,dtype=dt,shape=(n,))

class Dataset:
    def __init__(self):self.cache={}
    def get(self,line,device):
        key=(str(line),str(device))
        if key not in self.cache:
            folder=ROOT/'data'/key[0]/key[1]
            with np.load(folder/'input.npz') as z:d={k:z[k] for k in ['timestamp','names','x']}
            old=read_output(ROOT/'results/baseline'/key[0]/key[1]/'output.bin')
            new=read_output(ROOT/'results/astra'/key[0]/key[1]/'output.bin')
            assert np.array_equal(old['timestamp'],d['timestamp']) and np.array_equal(new['timestamp'],d['timestamp'])
            assert old['x'].shape==new['x'].shape==d['x'].shape
            self.cache[key]=dict(timestamp=d['timestamp'],names=d['names'].astype(str),raw=d['x'],v54=old['x'],astra=new['x'])
        return self.cache[key]

def save(fig,path,dpi):
    fig.savefig(path,dpi=dpi,bbox_inches='tight')
    plt.close(fig)

def plot_gap_aware(ax,x,y,**kwargs):
    # Insert break vertices without replacing actual measurements at either side.
    where=np.flatnonzero(np.diff(x)>90/3600)+1
    if len(where):
        xx=np.insert(x,where,np.nan);yy=np.insert(y,where,np.nan)
    else:xx,yy=x,y
    return ax.plot(xx,yy,**kwargs)

def plot_three(ax,d,j,night,title=None,small=False):
    start=ms(night+' 22:00');stop=start+10*3600000
    sel=(d['timestamp']>=start)&(d['timestamp']<stop)
    times=d['timestamp'][sel];xx=(times-start)/3600000
    name=str(d['names'][j]);limit=1.0 if 'J' in name.upper() else 2.0
    arrays={k:np.asarray(d[k][sel,j]) for k in ['raw','v54','astra']}
    # Same finite rows used for three curve statistics. Lines retain every finite
    # observation so a mask discrepancy, if any, is not visually concealed.
    common=np.logical_and.reduce([np.isfinite(v) for v in arrays.values()])
    ranges={k:finite_stat(v[common]) for k,v in arrays.items()}
    ax.axvspan(80/60,9,color='#7B8F9B',alpha=0.075,zorder=0)
    ax.axvline(80/60,color='#B7C0C5',lw=0.5,ls=':');ax.axvline(9,color='#B7C0C5',lw=0.5,ls=':')
    for key in ['raw','v54','astra']:
        plot_gap_aware(ax,xx,arrays[key],color=COLORS[key],lw=0.75 if small else 1.05,
                       alpha=0.70 if key=='raw' else 0.93,label=LABELS[key])
    ax.set_xlim(0,10);ax.set_xticks([0,2,4,6,8,10],['22','00','02','04','06','08'])
    ax.set_ylabel('X (pixel)',fontsize=7 if small else 10)
    ax.tick_params(labelsize=7 if small else 9)
    range_text=' / '.join(fmt(ranges[k]) for k in ['raw','v54','astra'])
    color='#AE3F3B' if np.isfinite(ranges['astra']) and ranges['astra']>limit+1e-10 else '#263238'
    ax.set_title(title or f'{name} | limit {limit:g} px',fontsize=8 if small else 12,loc='left',color=color)
    ax.text(0.02,0.98,f'Range R / V54 / A: {range_text} px',transform=ax.transAxes,
            ha='left',va='top',fontsize=6.3 if small else 9,
            bbox=dict(facecolor='white',edgecolor='none',alpha=0.78,pad=1.6))
    if not len(times) or not common.any():
        ax.text(0.5,0.42,'No valid observations',ha='center',va='center',transform=ax.transAxes,color='#8B3F38')
    else:
        ax.text(0.98,0.02,f'n={int(common.sum())}/600',ha='right',va='bottom',transform=ax.transAxes,
                fontsize=6.5 if small else 8,color='#5D666D')
    return dict(marker=name,target_range_px=limit,common_frames=int(common.sum()),
                raw_range_px=ranges['raw'] if np.isfinite(ranges['raw']) else None,
                v54_range_px=ranges['v54'] if np.isfinite(ranges['v54']) else None,
                astra_range_px=ranges['astra'] if np.isfinite(ranges['astra']) else None)

def heatmap(df,window,dpi):
    fig,axes=plt.subplots(1,3,figsize=(19,5.5),sharey=True,layout='constrained')
    subset=df[(df.window==window)&df.eligible]
    groups=[('left','ordinary'),('left','J_or_XJ'),('right','ordinary'),('right','J_or_XJ')]
    vals={};counts=np.zeros((4,len(NIGHTS)),int)
    for key in ['raw','v54','astra']:
        a=np.full((4,len(NIGHTS)),np.nan)
        for i,(line,category) in enumerate(groups):
            for j,night in enumerate(NIGHTS):
                g=subset[(subset.line==line)&(subset.target_class==category)&(subset.night==night)]
                counts[i,j]=len(g)
                if len(g):a[i,j]=100*bool_column(g[key+'_range_target_pass']).mean()
        vals[key]=a
    cmap=plt.get_cmap('YlGnBu').copy();cmap.set_bad('#E6E8EA')
    for ax,key in zip(axes,['raw','v54','astra']):
        im=ax.imshow(vals[key],vmin=0,vmax=100,cmap=cmap,aspect='auto')
        ax.set_title(LABELS[key]);ax.grid(False)
        ax.set_xticks(range(len(NIGHTS)),[n[5:].replace('-','/') for n in NIGHTS],rotation=60,ha='right',fontsize=8)
        ax.set_yticks(range(4),['Left ordinary (2 px)','Left J / XJ (1 px)','Right ordinary (2 px)','Right J / XJ (1 px)'])
        ax.axvline(2.5,color='white',lw=1.5);ax.axvline(9.5,color='#263238',ls='--',lw=1.5)
        for i in range(4):
            for j in range(len(NIGHTS)):
                v=vals[key][i,j]
                ax.text(j,i,'—' if not np.isfinite(v) else f'{v:.0f}%\n{counts[i,j]}',
                        ha='center',va='center',fontsize=6.5,color='white' if np.isfinite(v) and v>=65 else '#263238')
    fig.colorbar(im,ax=axes,shrink=0.78,label='Markers meeting max(X) − min(X) target (%)',pad=0.012)
    fig.suptitle(f'Nightly X range target pass rate | {WINDOW_NAMES[window]}\n'
                 'Cell: pass % / eligible point count. ≥80% common finite coverage. '
                 '11/02–04 warm-up; 11/12–15 later-period review.',fontsize=12)
    path=OUT/f'pass_rate_{window}.png';save(fig,path,dpi)
    return dict(type='pass_rate_heatmap',file=path.name,window=window,denominators=counts.tolist())

def scatter(df,window,dpi):
    selected=df[(df.window==window)&df.eligible&df.split.ne('warmup')]
    fig,axes=plt.subplots(2,3,figsize=(15.5,9),layout='constrained')
    pairs=[('raw','v54'),('raw','astra'),('v54','astra')]
    for row,category in enumerate(['ordinary','J_or_XJ']):
        g=selected[selected.target_class==category];limit=2 if row==0 else 1
        values=g[[k+'_p2p_units' for k in ['raw','v54','astra']]].to_numpy()
        high=max(2*limit,float(np.nanmax(values))*1.13 if len(values) else 2*limit)
        for col,(xkey,ykey) in enumerate(pairs):
            ax=axes[row,col]
            for split,color,marker in [('diagnostic','#6689A0','o'),('holdout','#7854A1','^')]:
                s=g[g.split==split]
                ax.scatter(s[xkey+'_p2p_units'],s[ykey+'_p2p_units'],s=10 if split=='diagnostic' else 14,
                           color=color,marker=marker,alpha=0.34,edgecolors='none',rasterized=True)
            if ykey=='astra':
                bad=g[bool_column(g.astra_broke_raw_range_target)]
                ax.scatter(bad[xkey+'_p2p_units'],bad[ykey+'_p2p_units'],s=28,facecolors='none',
                           edgecolors='#C2403C',linewidths=0.8,label='Astra breaks raw range target')
            ax.plot([0,high],[0,high],ls='--',lw=0.8,color='#757D82')
            ax.axhline(limit,color='#8A3D36',lw=0.8,ls=':');ax.axvline(limit,color='#8A3D36',lw=0.8,ls=':')
            ax.set_xscale('symlog',linthresh=0.1);ax.set_yscale('symlog',linthresh=0.1)
            ax.set_xlim(0,high);ax.set_ylim(0,high)
            ax.set_xlabel(LABELS[xkey]+' range (pixel)');ax.set_ylabel(LABELS[ykey]+' range (pixel)')
            ax.set_title(f'{"Ordinary" if row==0 else "J / XJ"} | {limit} px | n={len(g)}',fontsize=10)
    fig.suptitle(f'Complete ranges, including outliers | {WINDOW_NAMES[window]}\n'
                 'max(X) − min(X); symmetric-log axes with 0.1 px linear region; warm-up excluded',fontsize=12)
    handles=[Line2D([],[],linestyle='none',marker='o',color='#6689A0',label='11/05–11 diagnostic'),
             Line2D([],[],linestyle='none',marker='^',color='#7854A1',label='11/12–15 later-period review'),
             Line2D([],[],linestyle='none',marker='o',markerfacecolor='none',color='#C2403C',label='Astra breaks a raw-passing range target')]
    fig.legend(handles=handles,loc='outside lower center',ncol=3,frameon=False)
    path=OUT/f'range_scatter_{window}.png';save(fig,path,dpi)
    return dict(type='range_scatter',file=path.name,window=window,point_nights=len(selected),axes='symlog; no outlier clipping')

def latest_pages(dataset,df,dpi):
    output=[];seen=[]
    night='2026-11-15'
    for folder in sorted((ROOT/'data').glob('*/*/input.npz')):
        line,device=folder.parent.parent.name,folder.parent.name;d=dataset.get(line,device)
        m=len(d['names']);pages=math.ceil(m/16)
        for page in range(pages):
            remaining=min(16,m-page*16);nrows=math.ceil(remaining/4)
            fig,axes=plt.subplots(nrows,4,figsize=(16,3*nrows+0.6),layout='constrained',squeeze=False)
            cells=[]
            for slot,ax in enumerate(axes.flat):
                j=page*16+slot
                if j>=m:ax.axis('off');continue
                cells.append(plot_three(ax,d,j,night,small=True));seen.append((line,device,str(d['names'][j])))
                if slot>=4*(nrows-1):ax.set_xlabel('Beijing time (hour)',fontsize=7)
            handles=[Line2D([],[],color=COLORS[k],lw=1.3,label=LABELS[k]) for k in ['raw','v54','astra']]
            fig.legend(handles=handles,loc='outside lower center',ncol=3,frameon=False)
            fig.suptitle(f'{LINE_NAMES[line]} / {device} / 2026-11-15 night / page {page+1} of {pages}\n'
                         'All markers, including failures. Range shown for 22:00–08:00. '
                         'Shading: 23:20–07:00. Red title: Astra range exceeds target.',fontsize=12)
            path=OUT/f'latest_{line}_{device}_{page+1:02d}.png';save(fig,path,dpi)
            output.append(dict(type='latest_all_markers',file=path.name,line=line,device=device,night=night,page=page+1,pages=pages,markers=cells))
        print('PLOT_LATEST',line,device,m,'markers',pages,'pages',flush=True)
    assert len(seen)==len(set(seen)),'marker plotted twice'
    expected=sum(len(dataset.get(p.parent.parent.name,p.parent.name)['names']) for p in (ROOT/'data').glob('*/*/input.npz'))
    assert len(seen)==expected==524,('latest roster incomplete',len(seen),expected)
    return output

def focus_rows(df):
    active=df[df.window.eq('active_2320_07')&df.eligible&df.split.ne('warmup')].copy()
    choices=[]
    for night in ['2026-11-06','2026-11-07']:
        fixed=active[active.line.eq('right')&active.marker.eq('YD2603')&active.night.eq(night)]
        for _,r in fixed.iterrows():choices.append((f'Historical failure: YD2603 / {night}',r,'Fixed historical failure case requested; no ranking.'))
    q=active[active.category.eq('quiet')]
    if len(q):
        r=q.sort_values('v54_p95p5_change_units',ascending=False).iloc[0]
        label='Quiet-night V54 overcorrection' if r.v54_p95p5_change_units>1e-10 else 'Quiet-night maximum V54 change (no increase)'
        choices.append((label,r,'Among raw P95−P5 ≤0.5 px point-nights, maximum V54 minus raw P95−P5 change.'))
    if len(active):
        r=active.sort_values('astra_p95p5_change_units',ascending=False).iloc[0]
        label='Largest Astra P95−P5 increase' if r.astra_p95p5_change_units>1e-10 else 'No Astra P95−P5 increase observed'
        choices.append((label,r,'Largest Astra minus raw P95−P5 change across all eligible non-warmup active point-nights.'))
        active['astra_p2p_change']=active.astra_p2p_units-active.raw_p2p_units
        r=active.sort_values('astra_p2p_change',ascending=False).iloc[0]
        label='Largest Astra full-range increase' if r.astra_p2p_change>1e-10 else 'No Astra full-range increase observed'
        choices.append((label,r,'Largest Astra minus raw max−min change across all eligible non-warmup active point-nights.'))
        active['astra_vs_v54_p95']=active.astra_p95p5_units-active.v54_p95p5_units
        active['astra_vs_v54_p2p']=active.astra_p2p_units-active.v54_p2p_units
        r=active.sort_values('astra_vs_v54_p95',ascending=False).iloc[0]
        if r.astra_vs_v54_p95>1e-10:
            choices.append(('New versus V54: largest P95−P5 increase',r,
                            f'Maximum Astra minus V54 P95−P5 increase: {r.astra_vs_v54_p95:.6f} px; this comparison separates newly introduced changes from inherited V54 residuals.'))
        rp=active.sort_values('astra_vs_v54_p2p',ascending=False).iloc[0]
        if rp.astra_vs_v54_p2p>1e-10 and any(str(r[k])!=str(rp[k]) for k in ['line','device','marker','night']):
            choices.append(('New versus V54: largest full-range increase',rp,
                            f'Maximum Astra minus V54 max−min increase: {rp.astra_vs_v54_p2p:.6f} px across eligible non-warmup active point-nights.'))
    bad=active[bool_column(active.astra_broke_raw_range_target)]
    if len(bad):
        r=bad.sort_values('astra_p2p_units',ascending=False).iloc[0]
        choices.append(('Raw-passing range made to fail',r,'Among raw-passing/Astra-failing point-nights, maximum Astra max−min.'))
    if 'astra_lost_v54_repair_target' in active:
        lost=active[bool_column(active.astra_lost_v54_repair_target)]
        if len(lost):
            r=lost.sort_values('astra_p2p_units',ascending=False).iloc[0]
            choices.append(('V54 range repair lost by Astra',r,'Among raw-failing/V54-passing/Astra-failing point-nights, maximum Astra max−min.'))
    return choices

def focused(dataset,df,dpi):
    output=[]
    for i,(label,r,rule) in enumerate(focus_rows(df),1):
        line,device,marker,night=[str(r[k]) for k in ['line','device','marker','night']]
        d=dataset.get(line,device);j=list(d['names']).index(marker)
        fig,axes=plt.subplots(2,1,figsize=(12,7.6),layout='constrained',height_ratios=[2.2,1.0])
        info=plot_three(axes[0],d,j,night,title=f'{label}\n{LINE_NAMES[line]} / {device} / {marker} / {night}')
        axes[0].legend(loc='lower left',framealpha=0.92,ncol=3,fontsize=9)
        start=ms(night+' 22:00');sel=(d['timestamp']>=start)&(d['timestamp']<start+10*3600000)
        xx=(d['timestamp'][sel]-start)/3600000;raw=np.asarray(d['raw'][sel,j])
        axes[1].axvspan(80/60,9,color='#7B8F9B',alpha=0.075)
        for key in ['v54','astra']:
            plot_gap_aware(axes[1],xx,np.asarray(d[key][sel,j])-raw,color=COLORS[key],lw=1.0,label=LABELS[key]+' − Raw')
        axes[1].axhline(0,color='#707680',lw=0.6)
        axes[1].set_xlim(0,10);axes[1].set_xticks([0,2,4,6,8,10],['22','00','02','04','06','08'])
        axes[1].set_ylabel('Output − raw (pixel)');axes[1].set_xlabel('Beijing time (hour)');axes[1].legend(ncol=2,fontsize=8)
        fig.suptitle('Selection uses all eligible 23:20–07:00 point-nights; plots retain the entire 22:00–08:00 night.\n'
                     f'Active ranges (Raw / V54 / Astra): {r.raw_p2p_units:.3f} / {r.v54_p2p_units:.3f} / {r.astra_p2p_units:.3f} px',fontsize=10)
        path=OUT/f'focus_{i:02d}_{line}_{device}_{marker}_{night}.png';save(fig,path,dpi)
        output.append(dict(type='selected_failure',file=path.name,title=label,selection_rule=rule,line=line,device=device,night=night,
                           split=str(r['split']),active_raw_range_px=float(r.raw_p2p_units),active_v54_range_px=float(r.v54_p2p_units),active_astra_range_px=float(r.astra_p2p_units),**info))
    return output

def html_index(figures,df,manifest):
    esc=html.escape
    blocks=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
            '<title>V54-Astra X 向回放图册</title><style>body{font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif;color:#22323a;background:#f4f5f6;margin:0}main{max-width:1440px;margin:auto;padding:28px}h1{font-size:28px}h2{font-size:22px;margin-top:38px}h3{font-size:17px}a{color:#076c83}figure{margin:20px 0;background:white;padding:12px;border:1px solid #d6dce0}img{display:block;width:100%;height:auto}figcaption{font-size:13px;color:#465760}table{border-collapse:collapse;background:white;width:100%;font-variant-numeric:tabular-nums}th,td{border:1px solid #d6dce0;padding:7px;text-align:right}th:first-child,td:first-child{text-align:left}.note{border-left:4px solid #b37b35;padding:12px;background:#fff8eb}details{margin:14px 0;border-top:1px solid #cdd5d9;padding-top:12px}summary{cursor:pointer;font-weight:650}.small{font-size:13px;color:#52636c}nav a{margin-right:16px}</style><main>',
            '<h1>V54-Astra X 向连续回放图册</h1>',
            '<p>12 台设备 · 524 个测点 · 11 月 2 日至 15 日夜间 · 原始 X、原 V54、V54-Astra 三曲线</p>',
            '<nav><a href="#rates">每日达标率</a><a href="#ranges">全量范围散点</a><a href="#failures">失败与退化样例</a><a href="#latest">11/15 全测点</a></nav>',
            '<p class="note">单位为 pixel，按用户确认直接使用数据库 x/y，不做 scale 换算。达标定义：夜间 max(X)−min(X) ≤ 2 pixel；名称含 J（包括 XJ）的测点 ≤ 1 pixel。区间达标仅是数值指标，不能证明物理位移保真。</p>',
            '<p>同时报告 22:00–次日 08:00 整夜和 23:20–次日 07:00 稳态作用区间。统计只纳入三曲线共同有效覆盖率 ≥80% 的点夜；低覆盖和缺失记录仍保存在明细中。11/02–04 为预热，11/05–11 为诊断，11/12–15 为后期复核（CSV 内部标签为 holdout；此前曾查看过单设备旧候选摘要，因此不称为严格盲验证）。左线 11/06 整夜缺失，未补帧。</p>',
            '<p><a href="../reports/metrics_point_nights.csv">全量逐点夜指标 CSV</a> · <a href="../reports/metrics_summary.json">指标与边界检查 JSON</a> · <a href="../reports/metrics_incomplete.csv">低覆盖记录</a> · <a href="../reports/metrics_range_failures.csv">范围未达标记录</a> · <a href="../reports/metrics_lost_v54_repairs.csv">失去 V54 达标修复记录</a> · <a href="manifest.json">图册来源与选例规则</a></p>']
    blocks.append('<h2>范围达标率（预热夜除外）</h2><table><tr><th>窗口 / 集合</th><th>点夜数</th><th>原始 X</th><th>V54</th><th>V54-Astra</th><th>Astra 使原始达标转失败</th><th>Astra 失去 V54 达标修复</th></tr>')
    for window in ['night_22_08','active_2320_07']:
        for split in ['diagnostic','holdout']:
            g=df[df.window.eq(window)&df.split.eq(split)&df.eligible]
            vals=[100*bool_column(g[k+'_range_target_pass']).mean() if len(g) else float('nan') for k in ['raw','v54','astra']]
            label=('整夜 22–08' if window=='night_22_08' else '作用区间 23:20–07')+' / '+('诊断' if split=='diagnostic' else '后期复核')
            lost=str(int(bool_column(g.astra_lost_v54_repair_target).sum())) if 'astra_lost_v54_repair_target' in g else 'n/a'
            blocks.append('<tr><td>'+label+'</td><td>'+str(len(g))+'</td>'+''.join(f'<td>{v:.1f}%</td>' for v in vals)+f'<td>{int(bool_column(g.astra_broke_raw_range_target).sum())}</td><td>{lost}</td></tr>')
    blocks.append('</table>')
    if manifest.get('algorithm_policy')=='historical_regression_energy':
        blocks.append('<p>当前候选针对历史回归载荷能量异常进行保护。这里的 2 / 1 pixel 是输出波动范围的验收目标，不是把修正量或输出数值直接截断到该阈值。</p>')
    if 'target_impossible_given_zero_gate_w3' in df:
        bypass=df[df.window.eq('night_22_08')&df.eligible&df.split.ne('warmup')]
        count=int(bool_column(bypass.target_impossible_given_zero_gate_w3).sum())
        blocks.append(f'<p>沿用 V54 全时因果 W3 预处理，夜间模态、S2、S1 的作用时窗不改。另有 {count} 个有效点夜在 gate=0 的 W3 输出片段中已经超过整夜目标；保持该片段现有处理时，单靠夜间作用区间修正无法使整夜范围达标。<a href="../reports/metrics_outside_window_w3_range_failures.csv">查看这些记录</a>。</p>')
    def figure(r,extra=''):
        return '<figure><a href="'+esc(r['file'])+'"><img loading="lazy" src="'+esc(r['file'])+'" alt="'+esc(r.get('title',r['type']))+'"></a><figcaption>'+esc(extra or r.get('title',r['type']))+'</figcaption></figure>'
    blocks.append('<h2 id="rates">每日 max−min 达标率</h2><p class="small">每格为达标百分比与可纳入统计的测点数；空白灰格无足够数据。虚线后为后期复核夜。</p>')
    for r in figures:
        if r['type']=='pass_rate_heatmap':blocks.append(figure(r,WINDOW_NAMES[r['window']]))
    blocks.append('<h2 id="ranges">全量范围散点</h2><p class="small">完整保留离群值；对称对数坐标的小值线性区为 0.1 pixel。红色空心圈表示原始已达标而 Astra 输出转为不达标的点夜。</p>')
    for r in figures:
        if r['type']=='range_scatter':blocks.append(figure(r,WINDOW_NAMES[r['window']]))
    blocks.append('<h2 id="failures">历史过修与新退化样例</h2><p>以下包含固定历史异常和按全量指标选出的最差样例；不把退化情况排除在图册外。三曲线和修正量均显示完整幅度。</p>')
    for r in figures:
        if r['type']=='selected_failure':blocks.append(figure(r,r['selection_rule']))
    blocks.append('<h2 id="latest">11/15 夜间全部 524 点</h2><p class="small">每页最多 16 点。图内数字为整夜共同有效样本的范围，顺序 Raw / V54 / Astra；红色标题表示 Astra 整夜范围超出目标。阴影区为 23:20–07:00。纵轴逐点自适应，比较幅度请同时看刻度。</p>')
    pages=[r for r in figures if r['type']=='latest_all_markers']
    for line,device in sorted(set((r['line'],r['device']) for r in pages)):
        items=[r for r in pages if r['line']==line and r['device']==device]
        count=sum(len(r['markers']) for r in items)
        blocks.append(f'<details><summary>{"左线" if line=="left" else "右线"} / {device} · {count} 点 · {len(items)} 页</summary>')
        blocks.extend(figure(r,f'{device}, page {r["page"]}/{r["pages"]}') for r in items);blocks.append('</details>')
    blocks.append('<p class="small">图册由 tools/plot_report.py 从原生 C++ 回放二进制与最终指标生成。所有图片均为离线分析产物；原始数据库未改写。</p></main></html>')
    (OUT/'index.html').write_text('\n'.join(blocks),encoding='utf-8')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dpi',type=int,default=155);parser.add_argument('--focus-only',action='store_true');args=parser.parse_args()
    metrics=ROOT/'reports/metrics_point_nights.csv';summary=ROOT/'reports/metrics_summary.json'
    assert metrics.exists() and summary.exists(),'Final all-device metrics are not available yet; do not use partial diagnostic metrics.'
    df=pd.read_csv(metrics,dtype={'device':str,'marker':str,'night':str})
    for col in ['eligible','raw_range_target_pass','v54_range_target_pass','astra_range_target_pass','astra_broke_raw_range_target']:
        df[col]=bool_column(df[col])
    assert df[['line','device']].drop_duplicates().shape[0]==12
    assert set(df.split)=={'warmup','diagnostic','holdout'}
    assert set(df.window)=={'night_22_08','active_2320_07'}
    summary_record=json.loads(summary.read_text(encoding='utf-8'))
    source_hashes=dict(metrics=sha(metrics),summary=sha(summary),plot_script=sha(Path(__file__)))
    dataset=Dataset();figures=[]
    if args.focus_only:
        manifest=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
        assert manifest['source_sha256']['metrics']==source_hashes['metrics'],'Metrics changed; rerender all figures.'
        old=manifest['figures']
        figures=[r for r in old if r['type'] not in ['selected_failure','latest_all_markers']]
        figures+=focused(dataset,df,args.dpi)
        figures+=[r for r in old if r['type']=='latest_all_markers']
        manifest.update(figures=figures,source_sha256=source_hashes,algorithm_policy=summary_record.get('policy'))
        write_json(OUT/'manifest.json',manifest);html_index(figures,df,manifest)
        print('FOCUS_REFRESHED',len([r for r in figures if r['type']=='selected_failure']),flush=True)
        return
    for window in ['night_22_08','active_2320_07']:
        figures.append(heatmap(df,window,args.dpi));figures.append(scatter(df,window,args.dpi))
    figures+=focused(dataset,df,args.dpi)
    figures+=latest_pages(dataset,df,args.dpi)
    manifest=dict(units='pixel',source_sha256=source_hashes,full_metrics_rows=len(df),
                  plotting_library='matplotlib '+matplotlib.__version__,
                  algorithm_policy=summary_record.get('policy','See final metrics_summary.json'),
                  latest_night='2026-11-15',latest_marker_count=sum(len(r['markers']) for r in figures if r['type']=='latest_all_markers'),
                  range_definition='max-min on common finite samples; ordinary 2 px, name containing J incl. XJ 1 px',
                  visual_coverage='All latest-night markers shown. Scatter retains outliers. Failure selection is specified for every selected figure.',
                  figures=figures)
    write_json(OUT/'manifest.json',manifest);html_index(figures,df,manifest)
    assert source_hashes['metrics']==sha(metrics) and source_hashes['summary']==sha(summary),'metrics changed during rendering'
    print('PLOTS_DONE',len(figures),'figures','latest_markers',manifest['latest_marker_count'],flush=True)

if __name__=='__main__':main()
