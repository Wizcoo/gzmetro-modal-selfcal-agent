"""Traceable illustrative lag and boundary cases, absolute X and original time."""
from pathlib import Path
from datetime import datetime,timedelta
import importlib.util,json,os,sys
import numpy as np
import pandas as pd
from latency_analyze import ROOT,ROUND,TZ,read_result,clean
from latency_metrics import _centered_median5,_extrema

os.environ['MPLCONFIGDIR']=str(ROUND/'reports/latency_mplconfig')
CACHE=Path(r'C:\Users\12750\AppData\Local\uv\cache\archive-v0');ABI=f'cp{sys.version_info.major}{sys.version_info.minor}'
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
import matplotlib.dates as mdates

COLORS={'raw':'#646B74','current':'#D17B22','no_w3':'#087F8C','current_fade07':'#3159B8','current_end08':'#9471B7','current_fade08':'#345FC4'}
LABELS={'raw':'Raw X','current':'Current Astra','no_w3':'No W3','current_fade07':'Fade at 07:00','current_end08':'End at 08:00','current_fade08':'Fade at 08:00'}

def load(line,device,marker,variants):
    rawpath=ROOT/'data'/line/device/'input.npz';raw=np.load(rawpath,allow_pickle=False)
    j=list(raw['names']).index(marker);ts=raw['timestamp'];values={'raw':raw['x'][:,j]};paths={'raw':str(rawpath)}
    for variant in variants:
        p=ROUND/'results'/variant/line/device/'output.bin';out=read_result(p);assert np.array_equal(ts,out['timestamp'])
        values[variant]=np.array(out['x'][:,j]);paths[variant]=str(p)
    times=pd.to_datetime(ts,unit='ms',utc=True).tz_convert(TZ).to_pydatetime()
    return ts,np.asarray(times),values,paths

def draw(ax,times,values,mask,variants):
    actual=times[mask];breaks=np.array([i+1 for i in range(len(actual)-1) if (actual[i+1]-actual[i]).total_seconds()>90],dtype=int)
    xt=np.insert(actual,breaks,actual[breaks])
    for v in variants:
        yt=np.insert(values[v][mask],breaks,np.nan)
        ax.plot(xt,yt,color=COLORS[v],lw=1.6 if v!='raw' else 1.15,label=LABELS[v],alpha=.95)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M',tz=TZ));ax.set_ylabel('Absolute X (pixel)')
    ax.ticklabel_format(axis='y',style='plain',useOffset=False);ax.grid(alpha=.2);ax.legend(ncol=len(variants),loc='best',fontsize=9)
    ax.set_xlim(actual[0],actual[-1])

def run():
    outdir=ROUND/'plots';outdir.mkdir(exist_ok=True);reports=ROUND/'reports';metadata={}
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    # Illustrative paired case chosen after metric review; not a population average.
    line,device,marker,night='right','780639346578','YD3104','2026-11-06'
    ts,times,values,paths=load(line,device,marker,['current','no_w3'])
    start=datetime.fromisoformat(night).replace(tzinfo=TZ)+timedelta(hours=23,minutes=20);stop=start+timedelta(hours=7,minutes=40)
    mask=(ts>=int(start.timestamp()*1000))&(ts<int(stop.timestamp()*1000));indices=np.flatnonzero(mask)
    smooth=_centered_median5(values['raw'][mask]);peaks=_extrema(smooth);assert peaks
    strongest=max(peaks,key=lambda v:v[1])[0];peak=times[indices[strongest]]
    zoom=(ts>=int((peak-timedelta(minutes=25)).timestamp()*1000))&(ts<int((peak+timedelta(minutes=25)).timestamp()*1000))
    metrics={}
    for v in ['current','no_w3']:
        frame=pd.read_csv(reports/f'latency_{v}_point_nights.csv');r=frame[(frame.line==line)&(frame.device.astype(str)==device)&(frame.marker==marker)&(frame.night==night)&(frame.window=='active_2320_07')].iloc[0]
        metrics[v]={k:r[k] for k in ['slow_corr_zero','slow_corr_best','slow_best_lag_min','lag_resolved','output_p2p_px']}
    fig,axs=plt.subplots(2,1,figsize=(13,8.4),layout='constrained',gridspec_kw={'height_ratios':[1.1,1]})
    draw(axs[0],times,values,mask,['raw','current','no_w3']);draw(axs[1],times,values,zoom,['raw','current','no_w3'])
    axs[0].set_title('Full active interval — no time shift, no recentering');axs[0].axvspan(times[zoom][0],times[zoom][-1],color='#92A7BD',alpha=.14)
    axs[1].set_title('50-minute detail around a prominent local peak (offline evaluator)');axs[1].axvline(peak,color='#777777',ls=':',lw=1)
    fig.suptitle(f'Observed lag example | Right {device} / {marker} | night {night}',fontsize=14)
    zero0,zero1=metrics['current']['slow_corr_zero'],metrics['no_w3']['slow_corr_zero']
    fig.supxlabel(f'Acquisition time UTC+08:00 | Slow zero-lag r: current {zero0:.3f}, no W3 {zero1:.3f}; best lag: +2 / +1 min\nIllustrative lag case, not a range-pass example: current peak-to-peak is 5.19 px (>2). Raw is not physical truth.',fontsize=9)
    fig.savefig(outdir/'latency_delay_example.png',dpi=170);plt.close(fig)
    metadata['delay']=dict(line=line,device=device,marker=marker,night=night,metrics=metrics,source_paths=paths,
                           selection='Illustrative case chosen after paired metric review with current +2/no-W3 +1 minute. Detail centers most prominent local peak of the 5-point centered raw evaluator, not the global maximum. Traces are unshifted/unscaled; this case fails the 2px range.',zoom_center=str(peak))
    # Largest current full-gate exit jump among cases with same-frame raw |step|<.2px.
    event=pd.read_csv(reports/'latency_boundary_point_events.csv');event=event[(event.variant=='current')&(event.event=='exit_full_gate')&(event.raw_step_px.abs()<.2)&(event.output_step_px.abs()>=1)]
    row=event.loc[event.output_step_px.abs().idxmax()];line,device,marker,night=str(row.line),str(row.device),str(row.marker),str(row.night)
    variants=['current','no_w3','current_fade07'];ts,times,values,paths=load(line,device,marker,variants)
    boundary=datetime.fromisoformat(night).replace(tzinfo=TZ)+timedelta(days=1,hours=7)
    whole=(ts>=int((boundary-timedelta(minutes=20)).timestamp()*1000))&(ts<int((boundary+timedelta(minutes=30)).timestamp()*1000))
    zoom=(ts>=int((boundary-timedelta(minutes=5)).timestamp()*1000))&(ts<int((boundary+timedelta(minutes=8)).timestamp()*1000))
    fig,axs=plt.subplots(2,1,figsize=(13,8.4),layout='constrained')
    for ax,mask,title in [(axs[0],whole,'Full transition: smoothing fades through 07:20, raw-scale variation returns'),(axs[1],zoom,'First full-gate exit: same-frame raw is nearly flat')]:
        draw(ax,times,values,mask,['raw']+variants);ax.axvline(boundary,color='#888888',ls=':',lw=1)
        ax.axvline(boundary+timedelta(minutes=20),color='#888888',ls='--',lw=1);ax.set_title(title)
    actual=datetime.fromisoformat(str(row.time));i=int(np.argmin(np.abs(ts-int(actual.timestamp()*1000))));steps={v:float(values[v][i]-values[v][i-1]) for v in ['raw']+variants}
    fig.suptitle(f'Boundary example | {line.title()} {device} / {marker} | night {night}',fontsize=14)
    fig.supxlabel('Acquisition time UTC+08:00 | '+actual.strftime('%m-%d %H:%M:%S')+f" step: raw {steps['raw']:+.3f}, current {steps['current']:+.3f}, fade {steps['current_fade07']:+.3f} px\nOriginal absolute X; no time shift. The fade reduces switch discontinuity, not all noise after correction ends.",fontsize=9)
    fig.savefig(outdir/'latency_boundary_example.png',dpi=170);plt.close(fig)
    metadata['boundary']=dict(line=line,device=device,marker=marker,night=night,transition_time=str(actual),steps_px=steps,source_paths=paths,
                              selection='Largest current exit step with raw same-frame absolute step <0.2px among >=1px output steps.')
    (reports/'latency_plot_examples.json').write_text(json.dumps(clean(metadata),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(clean(metadata),ensure_ascii=False,indent=2))

if __name__=='__main__':run()
