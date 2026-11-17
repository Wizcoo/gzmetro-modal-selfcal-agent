"""Extract recorded per-point scale without asserting its physical semantics."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from data_prepare import ROOT,OLD,START,END,conn,dump

coverage=json.loads((ROOT/'reports/data_coverage.json').read_text(encoding='utf-8'))
rows=[]
for cov in coverage:
    line,dev=cov['line'],cov['device'];out=ROOT/'data'/line/dev
    inp=np.load(out/'input.npz');names=inp['names'].astype(str);times=inp['timestamp']
    frames=[]
    for src in cov['sources']:
        with conn(Path(src['read_path'])) as c:
            df=pd.read_sql_query(f'SELECT timestamp,markerName,scale,centerX,centerY,markerPos FROM "Marker_{dev}" NOT INDEXED WHERE timestamp>=? AND timestamp<?',c,params=(START,END))
        frames.append(df)
    df=pd.concat(frames,ignore_index=True);keys=['timestamp','markerName'];dup=df.duplicated(keys,keep=False)
    if dup.any():assert not df.loc[dup].groupby(keys)[['scale','centerX','centerY','markerPos']].nunique(dropna=False).gt(1).any(axis=None)
    df=df.drop_duplicates(keys)
    scale=df.pivot(index='timestamp',columns='markerName',values='scale').reindex(index=times,columns=names).to_numpy(dtype=float,copy=True)
    np.savez_compressed(out/'scale.npz',timestamp=times,names=names,scale=scale)
    for name,g in df.groupby('markerName'):
        vals=g.scale.dropna().unique();vals=np.sort(vals)
        rows.append(dict(line=line,device=dev,marker=name,recorded_scale_min=float(vals.min()) if len(vals) else None,recorded_scale_max=float(vals.max()) if len(vals) else None,recorded_scale_unique_count=int(len(vals)),recorded_scale_values=vals.tolist() if len(vals)<=10 else None,nonpositive_scale_rows=int(g.scale.le(0).sum()),markerPos_values=sorted(g.markerPos.dropna().unique().tolist()),centerX_unique_count=int(g.centerX.nunique()),centerY_unique_count=int(g.centerY.nunique())))
    print('SCALE',line,dev,'range',float(np.nanmin(scale)),float(np.nanmax(scale)),flush=True)
result=dict(status='FIELD_AVAILABLE_UNIT_MAPPING_UNCONFIRMED',database_field='Marker_<device>.scale',data_units='native database x/y; conversion to/from pixel must be confirmed at DB writer/caller',point_count=len(rows),scale_min=min(r['recorded_scale_min'] for r in rows if r['recorded_scale_min'] is not None),scale_max=max(r['recorded_scale_max'] for r in rows if r['recorded_scale_max'] is not None),points_with_changing_scale=sum(r['recorded_scale_unique_count']>1 for r in rows),points_with_nonpositive_scale=sum(r['nonpositive_scale_rows']>0 for r in rows),evidence=[dict(path=str(OLD/'Dot2DDIC_V0.0.0.51(1)/Dot2DDIC.h'),lines='136-140',fact='uv_cal, uv_temp, uv_corre are explicitly pixel displacement; fkxy calibration coefficient; uv_mm is physical mm.'),dict(path=str(OLD/'ModalSelfCal.hpp'),lines='29',fact='Historical ModalSelfCal input comment calls x/y mm, but DB writer and caller mapping are absent from available source.')],points=rows)
units_file=ROOT/'reports/user_confirmed_units.json'
if units_file.exists():
    result['initial_audit_status']=result['status']
    result['status']='INPUT_PIXEL_UNITS_USER_CONFIRMED_NO_SCALE_CONVERSION'
    result['data_units']='x/y are pixels, explicitly confirmed by the user on 2026-11-16. calX/calY have the same dimensions; scale is not applied.'
    result['unit_confirmation_file']=str(units_file)
dump(ROOT/'reports/data_scale_audit.json',result)
pd.DataFrame(rows).to_csv(ROOT/'reports/data_scale_summary.csv',index=False,encoding='utf-8-sig')
print(json.dumps({k:v for k,v in result.items() if k not in ['points','evidence']},ensure_ascii=False))
