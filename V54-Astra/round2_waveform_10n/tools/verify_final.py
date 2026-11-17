from pathlib import Path
import hashlib,json,struct,re
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):
    with p.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    return np.memmap(p,dtype=[('ts','<i8'),('xy','<f8',(2,m))],mode='r',offset=8,shape=(n,))
def main():
    checks={};man=json.loads((ROOT/'build/native_window_manifest.json').read_text(encoding='utf8'))
    checks['candidate_source_and_driver_hashes']=all(sha(ROOT/p)==v for p,v in man['source_sha256'].items())
    checks['candidate_binary_hash']=sha(ROOT/man['binary'])==man['binary_sha256']
    checks['first_round_cpp_unchanged']=sha(ROOT.parent/'src/ModalSelfCal.cpp')=='d725da11246a89b7df7e015a4f1d859aa1a4ebdb4c10afc22ec6f20ed43a842d'
    checks['first_round_h_unchanged']=sha(ROOT.parent/'src/ModalSelfCal.h')=='e341acc3a06907ff2bdced92c94a57bf53b57de997f51317d05aa6a6ab7c066e'
    result=[]
    for f in sorted((ROOT/'results/current').glob('*/*/output.bin')):
        line,dev=f.parent.parent.name,f.parent.name;a=read(f);b=read(ROOT/'results/current_fade07'/line/dev/'output.bin')
        hour=((a['ts']+8*3600000)%86400000)/3600000
        exit_window=(hour>=7)&(hour<7+20/60)
        row=dict(line=line,device=dev,frames=len(a),timestamps=np.array_equal(a['ts'],b['ts']),
                 y_bitwise=np.array_equal(a['xy'][:,1].view('u8'),b['xy'][:,1].view('u8')),
                 mask=np.array_equal(np.isfinite(a['xy']),np.isfinite(b['xy'])),
                 all_frames_outside_exit_bitwise=np.array_equal(a['xy'][~exit_window].view('u8'),b['xy'][~exit_window].view('u8')))
        assert all(row[k] for k in ['timestamps','y_bitwise','mask','all_frames_outside_exit_bitwise']);result.append(row)
    checks['fade07_changes_only_exit_window']=True
    metrics=pd.read_csv(ROOT/'reports/range_point_nights.csv',dtype={'device':str})
    lat=pd.read_csv(ROOT/'reports/latency_current_point_nights.csv',dtype={'device':str})
    lat['window']=lat.window.map({'night_22_08':'full','active_2320_07':'active'})
    k=['line','device','marker','night','window'];a=metrics[metrics.profile=='current'].set_index(k);b=lat.set_index(k).reindex(a.index)
    checks['independent_range_and_latency_eligibility_agree']=bool((a.eligible==b.eligible).all())
    both=a.eligible
    checks['independent_range_and_latency_p2p_agree']=bool(np.allclose(a.loc[both,'p2p'],b.loc[both,'output_p2p_px'],rtol=0,atol=1e-10))
    c=metrics[metrics.profile=='current_fade07'].set_index(k)
    changes=dict(old_pass_lost=int((a.eligible&a.pass_class&~c.pass_class).sum()),new_pass_gained=int((a.eligible&~a.pass_class&c.pass_class).sum()),
                 newly_material_amplified=int((a.eligible&~a.material_amplification&c.material_amplification).sum()))
    plots=json.loads((ROOT/'plots/range_plot_manifest.json').read_text(encoding='utf8'));checks['all_524_markers_in_range_figures']=plots['total_roster_markers']==524
    package=json.loads((ROOT/'reports/package_manifest.json').read_text(encoding='utf8'));checks['package_sha']=sha(Path(package['package']))==package['sha256']
    checks['package_inputs_unchanged']=all(sha(ROOT/r['path'])==r['sha256'] for r in package['files'])
    index=(ROOT/'plots/index.html').read_text(encoding='utf8');refs=re.findall(r'(?:href|src)="([^"]+)"',index)
    checks['html_local_links_exist']=all((ROOT/'plots'/r).resolve().is_file() for r in refs if not r.startswith('#'))
    checks['all_checks_passed']=all(checks.values());assert checks['all_checks_passed'],checks
    record=dict(checks=checks,fade07_vs_current=changes,device_checks=result,
                candidate_is_offline_review_only=True,full_night_95_percent_plus_physical_waveform_acceptance=False,
                plot_review='Root visually inspected range overview, full-roster 100-marker heatmap and real-data lag figure; latency reviewer inspected boundary and native plots.',
                package_sha256=package['sha256'])
    (ROOT/'reports/final_verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(record,ensure_ascii=False))
if __name__=='__main__':main()
