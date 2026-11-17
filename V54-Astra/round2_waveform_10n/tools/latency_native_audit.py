"""Known-waveform attribution through the actual native W3/S1/S2 component code.

This is not a simulation of modal fitting or proof of field displacement accuracy.
"""
from pathlib import Path
import ctypes, hashlib, importlib.util, json, os, sys
import numpy as np
import pandas as pd

ROUND=Path(__file__).resolve().parents[1]
CHANNELS=['W3','S1','W3_S1','S2','S2_S1','W3_S2_S1']

def run():
    dll_dir=os.add_dll_directory(r'C:\msys64\ucrt64\bin')
    native=ctypes.CDLL(str(ROUND/'build/latency_native_components.dll'))
    ptr=ctypes.POINTER(ctypes.c_double)
    native.latency_components.argtypes=[ctypes.c_int,ptr,ctypes.c_int,ptr]
    native.latency_components.restype=ctypes.c_int
    def apply(x,isolated=False):
        x=np.ascontiguousarray(x,dtype=np.float64);y=np.empty((len(x),6),dtype=np.float64)
        rc=native.latency_components(len(x),x.ctypes.data_as(ptr),int(isolated),y.ctypes.data_as(ptr))
        assert rc==0,rc
        if isolated:assert np.array_equal(y[:,3],x),'S2 must preserve a lone point with eight unchanged peers'
        return y
    sine_rows=[];traces=[]
    for period in [10,20,60,120]:
        t=np.arange(1560);x=np.where(t>=120,np.sin(2*np.pi*(t-120)/period),0)
        for isolated in [False,True]:
            y=apply(x,isolated);use=t>=360;theta=2*np.pi*(t[use]-120)/period
            basis=np.c_[np.sin(theta),np.cos(theta),np.ones(len(theta))]
            for j,channel in enumerate(CHANNELS):
                coef=np.linalg.lstsq(basis,y[use,j],rcond=None)[0];fit=basis@coef
                gain=np.hypot(coef[0],coef[1]);delay=-np.arctan2(coef[1],coef[0])/(2*np.pi/period)
                residual=np.sqrt(np.mean((fit-y[use,j])**2))
                sine_rows.append(dict(period_min=period,spatial_pattern='isolated_point' if isolated else 'all_points_common',
                                      component=channel,fundamental_gain=float(gain),phase_delay_min=float(delay),
                                      residual_rms_px=float(residual),phase_note='positive output behind; negative apparent phase lead'))
    shape_rows=[];known={}
    t=np.arange(420)
    cases={'step':np.where(t>=180,1.,0.),'gaussian12':np.where(t>=60,np.exp(-.5*((t-180)/12)**2),0.),
           'ramp':np.where(t>=120,(t-120)/120.,0.)}
    for scenario,x in cases.items():
        for isolated in [False,True]:
            pattern='isolated_point' if isolated else 'all_points_common';y=apply(x,isolated);known[(scenario,pattern)]=(x,y)
            for i in range(len(t)):
                traces.append(dict(scenario=scenario,spatial_pattern=pattern,minute=int(t[i]),raw_px=float(x[i]),
                                   **{c:float(y[i,j]) for j,c in enumerate(CHANNELS)}))
            for j,channel in enumerate(CHANNELS):
                row=dict(scenario=scenario,spatial_pattern=pattern,component=channel)
                if scenario=='step':
                    for threshold in [.1,.5,.9,.95]:
                        cross=np.flatnonzero(y[180:,j]>=threshold)
                        row[f'first_cross_{threshold:g}_min_after_step']=int(cross[0]) if len(cross) else None
                    row['value_at_step']=float(y[180,j]);row['value_7min_after']=float(y[187,j]);row['settled_value']=float(y[-1,j])
                elif scenario=='gaussian12':
                    peak_center=float(np.mean(np.flatnonzero(np.abs(y[:,j]-np.max(y[:,j]))<1e-10)))
                    row['peak_time_shift_min']=peak_center-float(np.argmax(x));row['peak_px']=float(np.max(y[:,j]))
                    row['minimum_px']=float(np.min(y[:,j]))
                elif scenario=='ramp':
                    row['equivalent_ramp_lag_min']=float(np.mean((x[300:360]-y[300:360,j])*120))
                shape_rows.append(row)
    # Exact component checks against independent algebra at steady state.
    alpha=1-np.exp(-1/1.5);r=1-alpha
    for row in sine_rows:
        if row['component']=='S1':
            omega=2*np.pi/row['period_min'];phase=np.arctan2(r*np.sin(omega),1-r*np.cos(omega))/omega
            assert abs(row['phase_delay_min']-phase)<1e-10
        if row['component']=='W3':assert abs(row['phase_delay_min']-1)<1e-10
    step=known[('step','isolated_point')][1][:,2]
    assert np.flatnonzero(step[180:]>=.5)[0]==2
    assert np.flatnonzero(step[180:]>=.95)[0]==5
    reports=ROUND/'reports';pd.DataFrame(sine_rows).to_csv(reports/'latency_native_sine.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(shape_rows).to_csv(reports/'latency_native_shapes.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(traces).to_csv(reports/'latency_native_traces.csv',index=False,encoding='utf-8-sig')
    hashes={str(p.relative_to(ROUND)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROUND/'baseline_src/ModalSelfCal.cpp',ROUND/'baseline_src/ModalSelfCal.h',Path(__file__),ROUND/'tools/latency_native_components.cpp']}
    summary=dict(source_hashes=hashes,sample_period_min=1,constant_gate=1,tau_min=1.5,s2_shrinkage=.55,
                 s1_alpha=float(alpha),s1_low_frequency_delay_min=float(r/alpha),w3_s1_low_frequency_delay_min=float(1+r/alpha),
                 checks='Native S1 sinus phase matches independent transfer function; W3 sine fundamental lag 1 min; W3+S1 step reaches 50% after 2 min, 95% after 5 min; S2 isolated point preserved exactly.',
                 limits='No modal fitting. Common motion is mathematically indistinguishable from nuisance common drift here. S2 may attenuate real common motion; a negative phase value is a shape effect, not prediction.',
                 sine=sine_rows,shapes=shape_rows)
    (reports/'latency_native_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.environ['MPLCONFIGDIR']=str(ROUND/'reports/latency_mplconfig')
    cache=Path(r'C:\Users\12750\AppData\Local\uv\cache\archive-v0')
    abi=f'cp{sys.version_info.major}{sys.version_info.minor}'
    for module in ['matplotlib','contourpy','cycler','fontTools','kiwisolver','packaging','pyparsing','PIL']:
        if importlib.util.find_spec(module):continue
        for package in cache.iterdir() if cache.exists() else []:
            candidate=package/module
            if not candidate.exists():continue
            native_files=list(candidate.rglob('*.pyd')) if candidate.is_dir() else []
            if any('.cp3' in p.name and ('.'+abi+'-') not in p.name for p in native_files):continue
            sys.path.append(str(package));break
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(3,1,figsize=(12,10),layout='constrained')
    for ax,(scenario,pattern,title) in zip(axs,[('step','isolated_point','Step: W3 and S1 delay the first response'),
                                                ('gaussian12','isolated_point','Smooth peak: causal filtering delays the peak'),
                                                ('gaussian12','all_points_common','Common smooth peak: S2 changes its shape and timing')]):
        x,y=known[(scenario,pattern)]
        draw=(lambda xx,yy,**kw:ax.step(xx,yy,where='post',**kw)) if scenario=='step' else ax.plot
        draw(t-180,x,color='black',lw=2,label='Known input')
        for j,label in ([(0,'W3'),(1,'S1'),(2,'W3 + S1')] if pattern=='isolated_point' else [(3,'S2'),(5,'W3 + S2 + S1')]):
            draw(t-180,y[:,j],lw=1.6,label=label)
        ax.set_xlim((-10,20) if scenario=='step' else (-50,70));ax.axvline(0,color='#999999',ls=':',lw=.8)
        ax.set(title=title,xlabel='Minutes from input step/peak',ylabel='X (pixel)');ax.grid(alpha=.2);ax.legend(loc='best',ncol=4)
    fig.suptitle('Native temporal components — unchanged source; 1 minute sampling',fontsize=14)
    fig.savefig(reports/'latency_native_components.png',dpi=160);plt.close(fig)
    print(json.dumps({k:v for k,v in summary.items() if k not in ['sine','shapes','source_hashes']},indent=2))

if __name__=='__main__':run()
