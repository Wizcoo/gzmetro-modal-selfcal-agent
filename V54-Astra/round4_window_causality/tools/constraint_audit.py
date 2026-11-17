"""Read-only source/log audit for the three-night guarantee question."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,re,struct,hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent
R2=BASE/'round2_waveform_10n'
OUT=ROOT/'reports';OUT.mkdir(exist_ok=True,parents=True)
TZ=timezone(timedelta(hours=8))
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def read(p):
    with p.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    return np.memmap(p,dtype=[('t','<i8'),('xy','<f8',(2,m))],offset=8,mode='r',shape=(n,))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
dev='780639298317';line='right';night='2026-11-06';marker='YD1102'
diagpath=BASE/'experiments/reliable_modes/diagnostic/reports/all_point_modes.csv'
diag=pd.read_csv(diagpath,dtype={'device':str})
dd=diag[(diag.device==dev)&(diag.line==line)]
target=dd[dd.marker==marker].copy()
target.to_csv(OUT/'constraint_yd1102_prior_native_modes.csv',index=False,encoding='utf-8-sig')
roster=dd[dd.night==night].copy()
roster.to_csv(OUT/'constraint_1106_prior_native_roster.csv',index=False,encoding='utf-8-sig')
source=BASE/f'data/{line}/{dev}/input.npz'
with np.load(source) as d:ts=d['timestamp'];x=d['x'];names=list(d['names'])
lo,hi=ms(night+' 23:00'),ms('2026-11-07 07:00')
rows=[];regr=[]
logpath=R2/f'results/current/{line}/{dev}/replay.log'
pattern=re.compile(r'ts=(\d+).*state=(\S+)/\S+.*hist=(\d+)/(\d+) valid=(\d+)/(\d+).*gate=([\d.]+)/')
for lineno,text in enumerate(logpath.read_text(encoding='utf8',errors='replace').splitlines(),1):
    if text.startswith('REG_ENERGY,'):regr.append({'line':lineno,'text':text})
    match=pattern.search(text)
    if not match:continue
    t,state,hx,hy,nx,ny,gate=match.groups();t=int(t)
    if not lo<=t<hi:continue
    at=int(np.searchsorted(ts,t));assert ts[at]==t
    rows.append({'timestamp':t,'time':datetime.fromtimestamp(t/1000,TZ).isoformat(sep=' '),'log_line':lineno,
                 'state_x':state,'history_x':int(hx),'n_solved_x':int(nx),'n_raw_finite_x':int(np.isfinite(x[at]).sum()),'gate_x_rounded_in_log':float(gate)})
frame=pd.DataFrame(rows)
frame.to_csv(OUT/'constraint_1106_frame_log.csv',index=False,encoding='utf-8-sig')
baseline=read(BASE/f'results/baseline/{line}/{dev}/output.bin')
current=read(R2/f'results/current/{line}/{dev}/output.bin')
assert np.array_equal(baseline['t'],current['t'])
sel=(ts>=ms(night+' 22:00'))&(ts<ms('2026-11-07 08:00'))
current_equals_baseline=baseline['xy'][sel].tobytes()==current['xy'][sel].tobytes()
doc={'scope':'Frozen source/log/output inspection only; no native program executed','device':dev,'marker':marker,'night':night,
     'current_1106_xy_bitwise_equal_original_v54':current_equals_baseline,
     'native_1106_roster':{'points':len(roster),'use':int(roster.use.sum()),'learn':int(roster.learn.sum()),'fit_only':int(roster.fit_only.sum()),'spread_rejected':int(roster.spread_rejected.sum()),'guard_rejected':int(roster.guard_rejected.sum())},
     'yd1102_native_1106':json.loads(target[target.night==night].to_json(orient='records'))[0],
     'all_current_device_reg_energy_log_records':len(regr),
     'frame_23_07':{'frames':len(frame),'history_x_counts':frame.history_x.value_counts().to_dict(),'state_x_counts':frame.state_x.value_counts().to_dict(),
        'n_solved_x_counts':frame.n_solved_x.value_counts().to_dict(),'n_raw_finite_x_counts':frame.n_raw_finite_x.value_counts().to_dict(),
        'finite_counts_equal_solved_counts':bool((frame.n_solved_x==frame.n_raw_finite_x).all()),
        'solved_fewer_than_raw_count':int((frame.n_solved_x<frame.n_raw_finite_x).sum())},
     'interpretation_limits':['Earlier MODE_DIAG came from original V54 instrumentation, whose output was bitwise checked against V54. Learning/statistics formulas are unchanged before the Astra gamma branch; gamma only touches valid nonlearning non-fit_only rows.',
        'No REG_ENERGY record alone would not establish learn status; actual earlier MODE_DIAG and unchanged-input/output/source checks support that conclusion.',
        'Matching solver counts only rules out recorded numerical pruning in these frames; it cannot certify raw points are physically free of matching faults.'],
     'sources_sha256':{str(p):sha(p) for p in [diagpath,logpath,source,R2/'src/window_candidate/ModalSelfCal.cpp',R2/'src/window_candidate/ModalSelfCal.h']}}
(OUT/'constraint_source_log_audit.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in doc.items() if k!='sources_sha256'},ensure_ascii=True,indent=2))
