"""Same-window comparison of frozen temporal ablation outputs; no replay."""
from pathlib import Path
import numpy as np
import pandas as pd
from window_xj_audit import BASE,R2,OUT,ms,span,read,role

existing=pd.read_csv(OUT/'window_xj_point_nights.csv',dtype={'device':str})
records=[]
for source in sorted((BASE/'data').glob('*/*/input.npz')):
    line,dev=source.parent.parent.name,source.parent.name
    with np.load(source) as d:ts=d['timestamp'];raw=d['x'];names=[str(n) for n in d['names']]
    for profile in ['no_w3','modal_only']:
        output=read(R2/'results'/profile/line/dev/'output.bin');assert np.array_equal(output['timestamp'],ts)
        vals=output['xy'][:,0,:];assert np.array_equal(np.isfinite(vals),np.isfinite(raw))
        for day in range(6,16):
            night=f'2026-11-{day:02d}';start=ms(night+' 23:00');sel=(ts>=start)&(ts<start+480*60000)
            for j,name in enumerate(names):
                v=vals[sel,j];r=raw[sel,j];n=int(np.isfinite(v).sum());eligible=n>=384
                p=span(v);q=span(v,[.05,.95]);rp=span(r);rq=span(r,[.05,.95]);limit=2 if role(name)=='ordinary' else 1
                records.append(dict(profile=profile,line=line,device=dev,marker=name,role=role(name),night=night,valid=n,eligible=eligible,limit=limit,p2p=p,p95p5=q,raw_p2p=rp,raw_p95p5=rq,
                    pass_class=bool(eligible and p<=limit+1e-9),pass1=bool(eligible and p<=1+1e-9),material_amplification=bool(eligible and q-rq>max(.05,.1*rq)),quiet_raw1=bool(eligible and rp<=1+1e-9),quiet_broken1=bool(eligible and rp<=1+1e-9 and p>1+1e-9)))
df=pd.concat([existing,pd.DataFrame(records)],ignore_index=True);df.to_csv(OUT/'window_xj_ablation_point_nights.csv',index=False,encoding='utf-8-sig')
keys=['line','device','marker','night'];base=df[df.profile=='current_fade07'].set_index(keys)
summary=[]
for profile,g in df.groupby('profile'):
    z=g.set_index(keys);assert np.array_equal(z.eligible,base.eligible)
    e=z[z.eligible];a=base.loc[e.index]
    summary.append(dict(profile=profile,nominal=len(g),eligible=len(e),passed=int(e.pass_class.sum()),pass_pct=100*e.pass_class.mean(),all1=int(e.pass1.sum()),all1_pct=100*e.pass1.mean(),
        material_amplification=int(e.material_amplification.sum()),quiet_raw1=int(e.quiet_raw1.sum()),quiet_broken1=int(e.quiet_broken1.sum()),gained_vs_fade07=int((e.pass_class&~a.pass_class).sum()),lost_vs_fade07=int((~e.pass_class&a.pass_class).sum())))
s=pd.DataFrame(summary);s.to_csv(OUT/'window_xj_ablation_summary.csv',index=False,encoding='utf-8-sig');print(s.to_string(index=False))
