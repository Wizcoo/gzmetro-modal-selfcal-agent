"""Static full-roster ten-night range figures; never replace a waveform audit."""
from pathlib import Path
import os,sys,importlib.util,json,html
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'plots';OUT.mkdir(exist_ok=True)
os.environ['MPLCONFIGDIR']=str(OUT/'.mplconfig')
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
from matplotlib.colors import ListedColormap,BoundaryNorm
import numpy as np
import pandas as pd
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'white'})

def main():
    frame=pd.read_csv(ROOT/'reports/range_point_nights.csv',dtype={'device':str})
    summary=pd.read_csv(ROOT/'reports/range_summary.csv')
    profiles=['current','current_fade07','current_end08','current_fade08','no_w3','no_w3_end08','no_w3_tau05','no_temporal','no_temporal_s2_070','no_temporal_s2_085']
    profiles=[p for p in profiles if p in frame.profile.unique()]
    fig,axes=plt.subplots(1,2,figsize=(15,7),sharey=True,layout='constrained')
    for ax,window in zip(axes,['full','active']):
        g=summary[summary.window==window].set_index('profile').loc[profiles]
        y=np.arange(len(profiles));ax.barh(y-.16,g.pass_class_pct,height=.3,color='#137f87',label='Ordinary <=2 px; J/XJ <=1 px')
        ax.barh(y+.16,g.pass1_pct,height=.3,color='#e7a34e',label='All markers <=1 px')
        for i,(_,r) in enumerate(g.iterrows()):
            ax.text(r.pass_class_pct+.5,i-.16,f'{r.pass_class_pct:.2f}%',va='center',fontsize=8)
            ax.text(r.pass1_pct+.5,i+.16,f'{r.pass1_pct:.2f}%',va='center',fontsize=8)
        ax.axvline(95,color='#b33840',ls='--',lw=1);ax.set_xlim(0,107);ax.set_yticks(y,profiles)
        ax.set_xlabel('Eligible point-nights passing nightly max - min (%)')
        ax.set_title(('22:00-08:00 complete night' if window=='full' else '23:20-07:00 original active interval')+f' | n={int(g.iloc[0].n):,}')
        ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
    axes[0].invert_yaxis()
    handles,legends=axes[0].get_legend_handles_labels()
    fig.legend(handles,legends,loc='outside lower center',ncol=2,fontsize=9)
    fig.suptitle('X range and latency trade-off | 2026-11-06 to 2026-11-15\nRange passing alone does not establish waveform or physical event fidelity',fontsize=14)
    fig.savefig(OUT/'range_tradeoff.png',dpi=170);plt.close(fig)
    files=['range_tradeoff.png'];dates=[f'2026-11-{i:02d}' for i in range(6,16)]
    for (line,dev),allg in frame.groupby(['line','device']):
        names=sorted(allg.marker.unique());candidates=['raw','current','current_fade07']
        candidates=[p for p in candidates if p in allg.profile.unique()]
        fig,axes=plt.subplots(1,len(candidates),figsize=(14,max(7,len(names)*.21)),sharey=True,layout='constrained',squeeze=False)
        cmap=ListedColormap(['#e2f0ef','#86c7bd','#f5d28f','#d67772']);cmap.set_bad('#c4c7cb');norm=BoundaryNorm([0,1,2,4,1e9],4)
        for ax,prof in zip(axes[0],candidates):
            g=allg[(allg.profile==prof)&(allg.window=='full')].copy();g.loc[~g.eligible,'p2p']=np.nan
            a=g.pivot(index='marker',columns='night',values='p2p').reindex(index=names,columns=dates).to_numpy()
            ax.imshow(a,aspect='auto',cmap=cmap,norm=norm,interpolation='nearest')
            ax.set_xticks(np.arange(10),[d[5:] for d in dates],rotation=60);ax.set_yticks(np.arange(len(names)),names,fontsize=8)
            ax.set_title(prof);ax.tick_params(length=0)
            for i,j in np.argwhere(np.isfinite(a)):
                if a[i,j]>2:ax.text(j,i,f'{a[i,j]:.1f}',ha='center',va='center',fontsize=5.7,color='#422b2d')
        fig.suptitle(f'{line.upper()} {dev} | all {len(names)} markers, all 10 calendar nights\n22:00-08:00 max - min (pixel). Teal <=1 / green 1-2 / amber 2-4 / red >4 / gray insufficient\nJ/XJ require <=1 pixel; others <=2. Values rounded; CSV uses full precision. No missing-night substitution.',fontsize=11)
        name=f'roster_{line}_{dev}.png';fig.savefig(OUT/name,dpi=170);plt.close(fig);files.append(name)
    manifest={'files':files,'total_roster_markers':int(frame[['line','device','marker']].drop_duplicates().shape[0]),
              'night_count':10,'missing':'Left 11/06 absent. Per-point coverage <80% shown gray. All original rows retained in CSV.'}
    (OUT/'range_plot_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    print(json.dumps(manifest))
if __name__=='__main__':main()
