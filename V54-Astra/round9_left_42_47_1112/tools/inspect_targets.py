from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,re,struct,hashlib
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent
TZ=timezone(timedelta(hours=8))
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
start=ms('2026-11-12 23:00');end=ms('2026-11-13 07:00')
def native(path):
    with path.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    return np.memmap(path,dtype=np.dtype([('timestamp','<i8'),('xy','<f8',(2,m))]),offset=8,mode='r',shape=(n,))
def metric(a,t):
    valid=np.isfinite(a);a=a[valid];t=t[valid]
    if not len(a):return {'valid':0}
    return {'valid':len(a),'min':float(a.min()),'max':float(a.max()),'range':float(np.ptp(a)),
        'min_time':datetime.fromtimestamp(int(t[np.argmin(a)])/1000,TZ).isoformat(),
        'max_time':datetime.fromtimestamp(int(t[np.argmax(a)])/1000,TZ).isoformat()}
records=[]
for folder in sorted((BASE/'data/left').iterdir()):
    d=np.load(folder/'input.npz');names=d['names'].tolist()
    targets=[n for n in names if re.fullmatch(r'ZD4[2-7]\d{2}',n)]
    if not targets:continue
    ts=d['timestamp'];out=native(BASE/'round2_waveform_10n/results/current_fade07/left'/folder.name/'output.bin')
    assert np.array_equal(ts,out['timestamp'])
    sel=(ts>=start)&(ts<end);ref=(ts>=start-3600000)&(ts<start)
    late=(ts>=ms('2026-11-13 03:00'))&(ts<ms('2026-11-13 06:00'))
    for name in targets+[n for n in names if 'J' in n]:
        j=names.index(name);record={'device':folder.name,'marker':name,'target':name in targets,'axes':{}}
        for k,axis in enumerate(['x','y']):
            arrays={'raw':d[axis][:,j],'old':d['online_'+axis][:,j],'new':out['xy'][:,k,j]}
            record['axes'][axis]={}
            for label,a in arrays.items():
                r=metric(a[sel],ts[sel]);r['ref_valid']=int(np.isfinite(a[ref]).sum())
                r['late_median_minus_reference_median']=float(np.nanmedian(a[late])-np.nanmedian(a[ref]))
                r['late_median_minus_raw_reference_median']=float(np.nanmedian(a[late])-np.nanmedian(arrays['raw'][ref]))
                record['axes'][axis][label]=r
        records.append(record)
(ROOT/'reports').mkdir(parents=True,exist_ok=True)
(ROOT/'reports/root_metrics.json').write_text(json.dumps({'window':'2026-11-12 23:00 to2026-11-13 07:00, end exclusive UTC+8','reference':'22:00-23:00','late':'03:00-06:00','records':records},ensure_ascii=False,indent=2),encoding='utf8')
for r in records:
    if (r['device']=='780638327479' and r['marker'] in ['ZD4703','ZD4403','ZJ7','ZXJ6']) or (r['device']=='780638349768' and r['marker'] in ['ZD4404','ZD4703','ZJ7']):
        print(r['device'][-6:],r['marker'],json.dumps(r['axes'],ensure_ascii=True))
