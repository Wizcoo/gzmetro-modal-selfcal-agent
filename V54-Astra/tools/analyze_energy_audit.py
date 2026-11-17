"""Extract the final native regression-energy decision audit, without replay."""
from datetime import date,timedelta
import json
import numpy as np
import pandas as pd
from analyze_results import ROOT

def main():
    rows=[]
    for path in sorted((ROOT/'results/astra').glob('*/*/replay.log')):
        line,device=path.parent.parent.name,path.parent.name
        with path.open(encoding='utf-8',errors='strict') as stream:
            for record in stream:
                if not record.startswith('REG_ENERGY,'):continue
                fields=record.strip().split(',')
                if len(fields)!=11:raise ValueError(f'Malformed audit record: {path}: {record}')
                _,nid,marker,support,q,gamma,state,covered,invalid,uninformative,coverage=fields
                night=str(date(1970,1,1)+timedelta(days=int(nid)))
                rows.append(dict(line=line,device=device,night=night,night_id=int(nid),marker=marker,
                    history_support=int(support),min_q=float(q),gamma=float(gamma),state=state,
                    covered_nights=int(covered),invalid_nights=int(invalid),uninformative_nights=int(uninformative),
                    min_supported_coverage=float(coverage)))
    df=pd.DataFrame(rows)
    if df.empty:raise RuntimeError('No native REG_ENERGY audit records')
    df['split']=np.where(df.night<'2026-11-05','warmup',np.where(df.night<'2026-11-12','diagnostic','holdout'))
    duplicate=df.duplicated(['line','device','night','marker'],keep=False)
    df.to_csv(ROOT/'reports/metrics_energy_audit.csv',index=False,encoding='utf-8-sig')
    altered=df[df.gamma<1-1e-12]
    altered.to_csv(ROOT/'reports/metrics_energy_altered.csv',index=False,encoding='utf-8-sig')
    groups=[]
    for (split,state),g in df.groupby(['split','state']):
        groups.append(dict(split=split,state=state,rows=len(g),support_min=int(g.history_support.min()),support_max=int(g.history_support.max()),
            minimum_supported_coverage=float(g.min_supported_coverage.min()) if g.min_supported_coverage.notna().any() else None))
    report=dict(policy='historical_regression_energy',source='Final native results/astra/*/*/replay.log REG_ENERGY records',
        scope='Only ordinary valid nonlearning regression rows checked; fit_only and learned rows are not included in this audit count',
        audited_rows=len(df),duplicate_point_night_rows=int(duplicate.sum()),state_counts={str(k):int(v) for k,v in df.state.value_counts().items()},
        support_counts={str(k):int(v) for k,v in df.history_support.value_counts().sort_index().items()},
        min_supported_coverage=float(df.min_supported_coverage.min()) if df.min_supported_coverage.notna().any() else None,
        groups=groups,altered=json.loads(altered.to_json(orient='records')),
        source_build_manifest=json.loads((ROOT/'build/manifest_astra.json').read_text(encoding='utf-8')),
        qualification='Energy bound applies to historical full-basis moment proxy; pairwise missingness, dynamic SolveV/cbar and postprocessing limit physical/future interpretation')
    (ROOT/'reports/metrics_energy_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['audited_rows','duplicate_point_night_rows','state_counts','support_counts','min_supported_coverage']},indent=2),flush=True)
    print(altered.to_string(index=False),flush=True)

if __name__=='__main__':main()
