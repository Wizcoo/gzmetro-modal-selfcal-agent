"""Export latest complete night in pixel units from exact native replay files."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib, json, struct
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
TZ=timezone(timedelta(hours=8))
START=int(datetime(2026,11,15,22,tzinfo=TZ).timestamp()*1000)
END=int(datetime(2026,11,16,8,tzinfo=TZ).timestamp()*1000)

def output(path,times,m):
    with path.open('rb') as f:
        count,n=struct.unpack('<II',f.read(8));assert (count,n)==(m,len(times))
        a=np.fromfile(f,dtype=np.dtype([('ts','<i8'),('xy','<f8',(2,m))]),count=n)
        assert len(a)==n and not f.read()
    assert np.array_equal(a['ts'],times)
    return a['xy']

def main():
    dest=ROOT/'exports'/'2026-11-15';dest.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for source in sorted((ROOT/'data').glob('*/*/input.npz')):
        line,device=source.parent.parent.name,source.parent.name
        with np.load(source) as z:
            times=z['timestamp'];names=z['names'].astype(str);m=len(names)
            mask=(times>=START)&(times<END)
            raw_x=z['x'][mask];raw_y=z['y'][mask];roi=z['roi'][mask]
            old=output(ROOT/'results'/'baseline'/line/device/'output.bin',times,m)[mask]
            new=output(ROOT/'results'/'astra'/line/device/'output.bin',times,m)[mask]
            t=times[mask]
        assert len(t)==600
        labels=[datetime.fromtimestamp(int(ts)/1000,TZ).isoformat(sep=' ',timespec='milliseconds') for ts in t]
        frame=pd.DataFrame(dict(timestamp_ms=np.repeat(t,m),time_beijing=np.repeat(labels,m),
            marker=np.tile(names,len(t)),roi=roi.reshape(-1),raw_x_px=raw_x.reshape(-1),
            v54_x_px=old[:,0,:].reshape(-1),astra_x_px=new[:,0,:].reshape(-1),
            astra_correction_x_px=(raw_x-new[:,0,:]).reshape(-1),raw_y_px=raw_y.reshape(-1),
            v54_y_px=old[:,1,:].reshape(-1),astra_y_px=new[:,1,:].reshape(-1)))
        path=dest/f'{line}_{device}.csv.gz'
        frame.to_csv(path,index=False,encoding='utf-8-sig',compression='gzip',float_format='%.17g')
        reread=pd.read_csv(path)
        assert len(reread)==len(frame) and np.array_equal(reread.timestamp_ms.values,frame.timestamp_ms.values)
        # Parser round trips can differ in the final floating bit; native files retain exact values.
        for column in ['raw_x_px','v54_x_px','astra_x_px','raw_y_px','astra_y_px']:
            assert np.allclose(reread[column],frame[column],rtol=1e-12,atol=1e-12,equal_nan=True)
        manifest.append(dict(line=line,device=device,rows=len(frame),markers=m,frames=len(t),file=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    result=dict(unit='pixel',window='2026-11-15 22:00 <= t < 2026-11-16 08:00 Asia/Shanghai',
        invalid='RoiCalState != 1 or nonfinite input: raw/output NaN, blank CSV fields; no interpolation',
        comparison='V54 and Astra are exact native offline replays, not database online calX',files=manifest)
    (dest/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(devices=len(manifest),rows=sum(x['rows'] for x in manifest)),ensure_ascii=False))

if __name__=='__main__':main()
