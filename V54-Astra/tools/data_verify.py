"""Verify serialized inputs, masks, dates, and latest-night independent extracts."""
from pathlib import Path
import json,struct,hashlib
import numpy as np
import pandas as pd
from data_prepare import ROOT,OLD,START,END,ms,sha,dump,local

out=[];metrics=[]
for file in sorted((ROOT/'data').glob('*/*/input.npz')):
    line,dev=file.parent.parent.name,file.parent.name
    with np.load(file) as archive:d={k:archive[k] for k in archive.files}
    t=d['timestamp'];names=d['names'].astype(str);m=len(names);n=len(t)
    assert len(np.unique(t))==n and np.all(np.diff(t)>0)
    assert t.min()>=START and t.max()<END
    assert d['x'].shape==d['y'].shape==d['roi'].shape==(n,m)
    assert not np.isfinite(d['x'][d['roi']!=1]).any()
    assert not np.isfinite(d['y'][d['roi']!=1]).any()
    with file.with_suffix('.bin').open('rb') as f:
        mb=struct.unpack('<I',f.read(4))[0];bn=[]
        for j in range(mb):bn.append(f.read(struct.unpack('<I',f.read(4))[0]).decode('utf-8'))
        nb=struct.unpack('<I',f.read(4))[0]
        r=np.fromfile(f,dtype=np.dtype([('t','<i8'),('v','<f8',(2,mb))]),count=nb)
        assert not f.read()
    assert list(names)==bn and nb==n and mb==m
    assert np.array_equal(r['t'],t)
    assert np.array_equal(r['v'][:,0,:],d['x'],equal_nan=True)
    assert np.array_equal(r['v'][:,1,:],d['y'],equal_nan=True)
    old=OLD/'analysis_20261116_y_1115_night'/line/(dev+'.pkl')
    latest_checked=0
    if old.exists():
        o=pd.read_pickle(old);tt=np.sort(o.timestamp.unique()).astype(np.int64)
        sel=(t>=ms('2026-11-15 22:00'))&(t<ms('2026-11-16 08:00'))
        assert np.array_equal(t[sel],tt),(line,dev,'latest timestamps differ')
        roi=o.pivot(index='timestamp',columns='markerName',values='RoiCalState').reindex(index=tt,columns=names).to_numpy(dtype=float)
        for key in ['x','y']:
            a=o.pivot(index='timestamp',columns='markerName',values=key).reindex(index=tt,columns=names).to_numpy(dtype=float,copy=True)
            a[(roi!=1)|~np.isfinite(a)]=np.nan
            assert np.array_equal(a,d[key][sel],equal_nan=True),(line,dev,key,'latest independent extract differs')
        latest_checked=int(sel.sum())
    coverage=json.loads(file.with_name('coverage.json').read_text(encoding='utf-8'))
    for night in coverage['nights']:
        start=ms(night['night']+' 23:20');end=start+int((7+40/60)*3600*1000)
        sel=(t>=start)&(t<end)
        for j,name in enumerate(names):
            vals=d['x'][sel,j];valid=vals[np.isfinite(vals)]
            metrics.append(dict(line=line,device=dev,marker=name,night=night['night'],frames=int(sel.sum()),valid=int(len(valid)),p95_p05_px=float(np.percentile(valid,95)-np.percentile(valid,5)) if len(valid) else None,range_px=float(valid.max()-valid.min()) if len(valid) else None))
    out.append(dict(line=line,device=dev,frames=n,markers=m,binary_matches_npz=True,finite_mask_valid=True,strictly_increasing=True,latest_independent_extract_frames_checked=latest_checked,input_sha256=sha(file.with_suffix('.bin'))))
dump(ROOT/'reports/data_validation.json',dict(devices=out,total_devices=len(out),total_markers=sum(e['markers'] for e in out),total_frames=sum(e['frames'] for e in out),total_latest_frames_compared=sum(e['latest_independent_extract_frames_checked'] for e in out)))
pd.DataFrame(metrics).to_csv(ROOT/'reports/data_raw_night_metrics.csv',index=False,encoding='utf-8-sig')
print(json.dumps(dict(devices=len(out),markers=sum(e['markers'] for e in out),frames=sum(e['frames'] for e in out),latest_frames=sum(e['latest_independent_extract_frames_checked'] for e in out))))
