from pathlib import Path
import os,sys,importlib.util
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'plots';OUT.mkdir(exist_ok=True)
os.environ['MPLCONFIGDIR']=str(OUT/'.window_xj_mplconfig')
CACHE=Path(r'C:\Users\12750\AppData\Local\uv\cache\archive-v0');ABI=f'cp{sys.version_info.major}{sys.version_info.minor}'
for module in ['matplotlib','contourpy','cycler','fontTools','kiwisolver','packaging','pyparsing','PIL']:
    if importlib.util.find_spec(module):continue
    for p in CACHE.iterdir() if CACHE.exists() else []:
        c=p/module
        if not c.exists():continue
        native=list(c.rglob('*.pyd')) if c.is_dir() else []
        if any('.cp3' in f.name and ('.'+ABI+'-') not in f.name for f in native):continue
        sys.path.append(str(p));break
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
from datetime import datetime,timezone,timedelta
import pandas as pd
import numpy as np
TZ=timezone(timedelta(hours=8));font=Path(r'C:\Windows\Fonts\msyh.ttc');font_manager.fontManager.addfont(str(font))
plt.rcParams.update({'font.family':font_manager.FontProperties(fname=str(font)).get_name(),'font.size':10,'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
for p in sorted((ROOT/'reports').glob('window_xj_trace_*.csv')):
    d=pd.read_csv(p);key=p.stem.removeprefix('window_xj_trace_');line,dev,point,night=key.split('_');clock=[datetime.fromtimestamp(x/1000,TZ) for x in d.timestamp_ms]
    fig,axes=plt.subplots(4,1,figsize=(14,12),sharex=True,layout='constrained',height_ratios=[1.3,1,1,1])
    l0,=axes[0].plot(clock,d.raw_x,color='#7e8792',lw=1,label='数据库 raw X／原始序列')
    l1,=axes[0].plot(clock,d.database_calX,color='#2871b9',ls='--',lw=1,label='数据库 calX')
    l2,=axes[0].plot(clock,d.new_x,color='#c64e43',lw=1.2,label='新算法 X／修后序列')
    axes[0].set_title('原始数值：raw X、数据库 calX、新算法（Astra＋07:00渐退）');axes[0].set_ylabel('X（pixel）')
    for ax,profile,title,color in [(axes[1],'raw','原始波形与同设备普通点整体趋势','#7e8792'),(axes[2],'current_fade07','修后波形与同设备普通点整体趋势','#c64e43')]:
        ax.plot(clock,d[profile+'_centered_xj'],color=color,lw=1.2)
        lc,=ax.plot(clock,d[profile+'_centered_peer_median'],color='#252f3b',lw=1.15,label='普通点中位趋势（不含J/XJ）')
        ax.fill_between(clock,d[profile+'_peer_q25'],d[profile+'_peer_q75'],color='#93a5b3',alpha=.20)
        ax.set_title(title+'；阴影为普通点第25—75百分位');ax.set_ylabel('相对起点（pixel）')
    axes[3].plot(clock,d.raw_relative_xj_minus_median,color='#7e8792',lw=1)
    axes[3].plot(clock,d.current_fade07_relative_xj_minus_median,color='#c64e43',lw=1.2)
    axes[3].set_title('等像素相对差：XJ − 普通点中位趋势（仅诊断，未经几何平差）');axes[3].set_ylabel('相对差（pixel）')
    for ax in axes:
        ax.grid(alpha=.15);ax.ticklabel_format(axis='y',style='plain',useOffset=False)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M',tz=TZ));ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=9))
    axes[-1].set_xlabel('采集时间（北京时间）；第2—4幅仅减去各点23:00—23:30中位数，不拟合、不缩放、不平移时间')
    fig.legend(handles=[l0,l1,l2,lc],loc='outside lower center',ncol=2,fontsize=10)
    fig.suptitle(f'XJ与设备整体趋势诊断｜左线 {dev} / {point}\n{night} 23:00—次日07:00；共同波动不直接等同于平差后零位移',fontsize=15)
    target=OUT/f'window_xj_{key}.png';fig.savefig(target,dpi=160);plt.close(fig)
    print(str(target),flush=True)
