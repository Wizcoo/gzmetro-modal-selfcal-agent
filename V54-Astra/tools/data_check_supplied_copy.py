"""Check readable rows of truncated right file 7 against the supplied valid copy."""
from pathlib import Path
import json,sqlite3
from data_prepare import ROOT,conn,dump
inv=json.loads((ROOT/'reports/data_inventory.json').read_text(encoding='utf-8'))
original=next(r for r in inv if r['line']=='right' and Path(r['source']).name=='1793052366195_DataBaseFile_7.db')
copied=next(r for r in inv if r['line']=='right' and Path(r['source']).name=='1793052366195_DataBaseFile_7 - 副本.db')
records=[]
with conn(Path(original['source'])) as a,conn(Path(copied['source'])) as b:
    for table in sorted(copied['tables']):
        all_copy=b.execute(f'SELECT timestamp,markerName,markerIndex,RoiCalState,x,y,calX,calY FROM "{table}" NOT INDEXED').fetchall()
        bykey={(r[0],r[1]):r for r in all_copy};assert len(bykey)==len(all_copy)
        n=0;conflicts=0;missing=0;error=None
        try:
            for r in a.execute(f'SELECT timestamp,markerName,markerIndex,RoiCalState,x,y,calX,calY FROM "{table}" NOT INDEXED'):
                n+=1
                key=(r[0],r[1])
                if key not in bykey:missing+=1
                elif bykey[key]!=r:conflicts+=1
        except sqlite3.DatabaseError as ex:error=str(ex)
        records.append(dict(table=table,readable_original_rows=n,supplied_copy_rows=len(all_copy),readable_rows_absent_from_copy=missing,readable_rows_differing_from_copy=conflicts,original_scan_error=error))
        assert missing==conflicts==0,(table,missing,conflicts)
result=dict(original_source=original['source'],original_sha256=original['source_sha256'],supplied_copy=copied['source'],supplied_copy_sha256=copied['source_sha256'],tables=records,all_readable_original_rows_preserved_in_copy=True,unreadable_original_portions='Cannot independently verify values that cannot be read from truncated original. Supplied copy itself passed current SQLite quick_check; gaps remain explicitly reported.')
dump(ROOT/'reports/data_supplied_copy_check.json',result)
print(json.dumps(result,ensure_ascii=False))
