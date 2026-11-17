"""Audited, read-only source extraction for chronological V54-Astra replay.

Never interpolate gaps. Input x/y are Marker_<device>.x/y in pixels (user
confirmed 2026-11-16), valid iff ROI == 1
and that axis is finite. calX/calY are recorded online references only.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import argparse, hashlib, json, os, shutil, sqlite3, struct, subprocess
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent
BASE = Path(r'E:\Wiz\GZMetro-Cpp\data-sql')
TZ = timezone(timedelta(hours=8))
def ms(s): return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def local(t): return datetime.fromtimestamp(int(t)/1000,TZ).isoformat(sep=' ') if t is not None else None
START, END = ms('2026-11-02 22:00'), ms('2026-11-16 08:00')
def dump(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest().upper()
def conn(p): return sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=60)

def inventory():
    known=[]
    for manifest in [OLD/'audit_x_median_crossline_20261112/recovery_manifest.json',OLD/'backtest_X_1112_V54_20261113/recovery_manifest.json']:
        known.extend(json.loads(manifest.read_text(encoding='utf-8')))
    candidates=[]
    for line,folder,prefix in [('left',BASE/'左线/NewDevice','1793507670403'),('right',BASE/'右线','1793052366195')]:
        for p in sorted(folder.glob(prefix+'_DataBaseFile_*.db')):
            number=int(p.stem.split('_')[-1].split(' ')[0])
            # Previous stream ranges establish these completed files precede
            # 11/02 22:00; right file 4 ends 11/02 18:39, left file 1 at 11:33.
            if (line=='right' and number<5) or (line=='left' and number<2):continue
            # The original truncated right file 7 and the valid supplied copy are
            # audited independently. Use the copy, as established in prior data audit.
            candidates.append((line,p))
    def one(pair):
        line,p=pair
        st=p.stat(); e=dict(line=line,source=str(p),bytes=st.st_size,mtime_ns=st.st_mtime_ns,source_sha256=sha(p),read_path=str(p),tables={})
        with conn(p) as c:
            try:e['source_integrity']=c.execute('PRAGMA quick_check').fetchall()
            except sqlite3.DatabaseError as ex:e['source_integrity']=[[str(ex)]]
        if line=='right' and p.name=='1793052366195_DataBaseFile_7.db':
            e['excluded']='truncated original; supplied file 7 copy audited and used instead'
            print('INVENTORY_EXCLUDED',line,p.name,flush=True)
            return e
        if e['source_integrity'] != [('ok',)]:
            prev=next((r for r in known if r['source']==str(p) and r['source_sha256']==e['source_sha256']),None)
            if prev and Path(prev['recovered']).exists() and sha(Path(prev['recovered']))==prev['recovered_sha256']:
                e['read_path']=prev['recovered']; e['recovery']='reuse exact source SHA-256 matched prior recovery';e['prior_recovery_record']=prev
            else:
                dst=ROOT/'data/recovery'/(line+'_'+p.stem+'_recovered.db');dst.parent.mkdir(parents=True,exist_ok=True)
                if dst.exists(): raise RuntimeError('Refusing to overwrite unverified recovery '+str(dst))
                env=os.environ.copy();env['PATH']=r'C:\msys64\ucrt64\bin;'+env['PATH']
                exe=r'C:\msys64\ucrt64\bin\sqlite3.exe'
                source_copy=dst.with_suffix('.source.db')
                shutil.copyfile(p,source_copy)
                assert sha(source_copy)==e['source_sha256']
                with dst.with_suffix('.recover.log').open('wb') as log1,dst.with_suffix('.import.log').open('wb') as log2:
                    a=subprocess.Popen([exe,str(source_copy),'.recover --ignore-freelist'],stdout=subprocess.PIPE,stderr=log1,env=env)
                    b=subprocess.Popen([exe,str(dst)],stdin=a.stdout,stdout=log2,stderr=log2,env=env);a.stdout.close()
                    rc2=b.wait();rc1=a.wait()
                assert rc1==rc2==0,(p,rc1,rc2)
                e['read_path']=str(dst);e['recovery']='new .recover --ignore-freelist; source opened read only by extraction'
        rp=Path(e['read_path'])
        with conn(rp) as c:
            e['read_integrity']=c.execute('PRAGMA quick_check').fetchall()
            assert e['read_integrity']==[('ok',)],(rp,e['read_integrity'])
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'Marker_[0-9]*'")]
            for t in sorted(tables):
                lo,hi,n=c.execute(f'SELECT min(timestamp),max(timestamp),count(*) FROM "{t}" NOT INDEXED').fetchone()
                e['tables'][t]=dict(min_ts=lo,max_ts=hi,rows=n,start=local(lo),end=local(hi))
        e['read_sha256']=sha(rp)
        print('INVENTORY',line,p.name,'recovered' if 'recovery' in e else 'ok',list(e['tables'].values())[0] if e['tables'] else 'empty',flush=True)
        return e
    with ThreadPoolExecutor(max_workers=3) as pool: rows=list(pool.map(one,candidates))
    dump(ROOT/'reports/data_inventory.json',rows)
    return rows

def extract_one(line,dev,inventory_rows):
    t='Marker_'+dev
    selected=[e for e in inventory_rows if e['line']==line and not e.get('excluded') and t in e['tables'] and e['tables'][t]['max_ts']>=START and e['tables'][t]['min_ts']<END]
    frames=[]; src=[]
    cols=['timestamp','markerName','markerIndex','RoiCalState','x','y','calX','calY']
    for e in selected:
        p=Path(e['read_path'])
        with conn(p) as c:
            d=pd.read_sql_query(f'SELECT {",".join(cols)} FROM "{t}" NOT INDEXED WHERE timestamp>=? AND timestamp<? ORDER BY timestamp,rowid',c,params=(START,END))
        src.append(dict(source=e['source'],read_path=e['read_path'],rows=len(d),source_sha256=e['source_sha256'],read_sha256=e['read_sha256']))
        frames.append(d)
    df=pd.concat(frames,ignore_index=True).sort_values(['timestamp','markerName'],kind='stable')
    keys=['timestamp','markerName'];dup=df.duplicated(keys,keep=False)
    conflicts=0
    if dup.any():conflicts=int(df.loc[dup].groupby(keys)[[c for c in cols if c not in keys]].nunique(dropna=False).gt(1).any(axis=1).sum())
    assert conflicts==0,(line,dev,'conflicting duplicate keys',conflicts)
    duplicates=int(df.duplicated(keys).sum());df=df.drop_duplicates(keys,keep='first')
    names=sorted(df.markerName.unique());times=np.sort(df.timestamp.unique()).astype('<i8')
    def matrix(k):return df.pivot(index='timestamp',columns='markerName',values=k).reindex(index=times,columns=names).to_numpy(dtype='<f8',copy=True)
    roi=matrix('RoiCalState');x,y,dbx,dby=[matrix(k) for k in ['x','y','calX','calY']]
    invalid_x_raw=int(((roi==1)&~np.isfinite(x)).sum());invalid_y_raw=int(((roi==1)&~np.isfinite(y)).sum())
    for a in [x,y,dbx,dby]:a[(roi!=1)|~np.isfinite(a)]=np.nan
    out=ROOT/'data'/line/dev;out.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out/'input.npz',timestamp=times,names=names,roi=roi,x=x,y=y,online_x=dbx,online_y=dby)
    with (out/'input.bin').open('wb') as f:
        f.write(struct.pack('<I',len(names)))
        for name in names:
            b=name.encode('utf-8');f.write(struct.pack('<I',len(b)));f.write(b)
        f.write(struct.pack('<I',len(times)))
        records=np.empty(len(times),dtype=np.dtype([('timestamp','<i8'),('v','<f8',(2,len(names)))]))
        records['timestamp']=times;records['v'][:,0,:]=x;records['v'][:,1,:]=y;records.tofile(f)
    gaps=np.diff(times);gap_idx=np.flatnonzero(gaps>90000)
    nights=[]
    for day in range(2,16):
        a,b=ms(f'2026-11-{day:02d} 22:00'),ms(f'2026-11-{day+1:02d} 08:00'); sel=(times>=a)&(times<b);tt=times[sel]
        nights.append(dict(night=f'2026-11-{day:02d}',frames=len(tt),nominal_frames=600,first=local(tt[0]) if len(tt) else None,last=local(tt[-1]) if len(tt) else None,max_gap_s=float(np.diff(tt).max()/1000) if len(tt)>1 else None,valid_x_cells=int(np.isfinite(x[sel]).sum()),total_cells=int(sel.sum()*len(names))))
    rec=dict(line=line,device=dev,names=names,markers=len(names),frames=len(times),rows=len(df),first=local(times[0]),last=local(times[-1]),requested_start=local(START),requested_end_exclusive=local(END),sources=src,duplicates_removed=duplicates,duplicate_conflicts=conflicts,missing_marker_cells=int(len(times)*len(names)-len(df)),invalid_roi_cells=int(np.isfinite(roi).sum()-np.count_nonzero(roi==1)),valid_roi_nonfinite_x=invalid_x_raw,valid_roi_nonfinite_y=invalid_y_raw,max_gap_s=float(gaps.max()/1000),gaps_over_90s=[dict(before=local(times[j]),after=local(times[j+1]),seconds=float(gaps[j]/1000)) for j in gap_idx],nights=nights,input_sha256=sha(out/'input.bin'),mask='Each axis: RoiCalState == 1 AND finite raw axis; missing/invalid is NaN; no interpolation.',input_format='u32 m; [u32 UTF8 bytes, name] * m; u32 n; [i64 timestamp, f64[m] x, f64[m] y] * n; little endian')
    dump(out/'coverage.json',rec)
    print('EXTRACTED',line,dev,len(names),len(times),local(times[-1]),'gaps',len(gap_idx),flush=True)
    return rec

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['all','inventory','extract'],default='all');p.add_argument('--device');p.add_argument('--line',choices=['left','right']);a=p.parse_args()
    inv=inventory() if a.stage in ['all','inventory'] else json.loads((ROOT/'reports/data_inventory.json').read_text(encoding='utf-8'))
    if a.stage=='inventory':return
    jobs=sorted(set((e['line'],t.split('_')[1]) for e in inv if not e.get('excluded') for t in e['tables']))
    if a.device:jobs=[j for j in jobs if j[1]==a.device]
    if a.line:jobs=[j for j in jobs if j[0]==a.line]
    records=[]
    # One device first, so native runner work can begin during subsequent extraction.
    for line,dev in jobs: records.append(extract_one(line,dev,inv))
    if not a.device and not a.line:dump(ROOT/'reports/data_coverage.json',records)
    for e in inv:
        p=Path(e['source']);assert p.stat().st_size==e['bytes'] and p.stat().st_mtime_ns==e['mtime_ns'],'source changed during extraction'
    print('DATA_READY',len(records),'devices',flush=True)
if __name__=='__main__':main()
