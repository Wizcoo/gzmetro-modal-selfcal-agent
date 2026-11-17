"""Independent native end-window and exit-enhancement diagnostics."""
from pathlib import Path
import argparse, ctypes, json, os, subprocess, sys, time
import native_replay as base
import native_supplemental as supplement

ROOT,PARENT,GXX=base.ROOT,base.PARENT,base.GXX
PROFILES=['window_default0','current_end08','no_w3_end08','no_w3_tau05_end08','current_fade07','current_fade08']
PROFILE_IDS=dict(zip(PROFILES,range(10,16)))
CONFIG_FUNCTION='''static ModalSelfCalConfig profile_config(int profile){
    if(profile<10||profile>15)throw std::runtime_error("invalid window profile");
    ModalSelfCalConfig cfg;cfg.max_frame_dev=0.0;
    if(profile==11||profile==12||profile==13||profile==15)cfg.x_apply_end_h=32.0;
    if(profile==12||profile==13)cfg.enable_x_w3_filter=false;
    if(profile==13)cfg.velocity_damping_tau_min=0.5;
    if(profile==14||profile==15)cfg.fade_x_enhancements_with_gate=true;
    return cfg;
}

'''

def protected_evidence():
    evidence=supplement.old_evidence()
    paths=[ROOT/'build/native_supplemental_manifest.json',ROOT/'build/native_supplemental.dll',
           ROOT/'tools/native_supplemental.cpp',ROOT/'tools/native_supplemental.py',ROOT/'reports/native_supplemental_summary.json']
    paths += [ROOT/'results'/p/'manifest.json' for p in supplement.PROFILES]
    evidence.update({str(p.relative_to(ROOT)):base.sha(p) for p in paths})
    return evidence

def build():
    source=ROOT/'src/window_candidate';driver=ROOT/'tools/native_window.cpp'
    original=(ROOT/'tools/native_replay.cpp').read_text(encoding='utf-8')
    start=original.index('static ModalSelfCalConfig profile_config(')
    end=original.index('static void write_config(',start)
    content=original[:start]+CONFIG_FUNCTION+original[end:]
    content=content.replace('NUMBER(apply_end_h);','NUMBER(apply_end_h);NUMBER(x_apply_end_h);NUMBER(fade_x_enhancements_with_gate);')
    content+='\n#include "native_window_checks.inc"\n'
    driver.write_text(content,encoding='utf-8')
    files=[source/'ModalSelfCal.cpp',source/'ModalSelfCal.h',driver,Path(__file__).resolve(),ROOT/'tools/native_window_checks.inc']
    before={str(p.relative_to(ROOT)):base.sha(p) for p in files}
    command=[str(GXX),'-std=c++17','-O2','-shared','-static-libgcc','-static-libstdc++','-I',str(source),str(driver),str(source/'ModalSelfCal.cpp'),'-o',str(ROOT/'build/native_window.dll')]
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (ROOT/'build/native_window_compile.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError(result.stderr)
    assert before=={str(p.relative_to(ROOT)):base.sha(p) for p in files}
    base.write_json(ROOT/'build/native_window_manifest.json',dict(source_sha256=before,binary='build/native_window.dll',binary_sha256=base.sha(ROOT/'build/native_window.dll'),command=command,
        profile_id_map={str(v):k for k,v in PROFILE_IDS.items()},max_frame_dev=0,
        history='Independent full continuous chronology from 2026-11-02 22:00, including daytime. No learned state shared between profiles.',
        boundary_coverage='All available input kept. Source ends 2026-11-16 08:00, so the final night has no full 08:00-08:20 boundary follow-up.',
        scope='Diagnostic only: moving the end time is not proof that exit transitions or physical accuracy are fixed.',
        baseline_manifest_sha256=base.sha(ROOT/'build/native_replay_manifest.json')))

def dll():
    token=os.add_dll_directory(str(GXX.parent)) if hasattr(os,'add_dll_directory') else None
    return ctypes.CDLL(str(ROOT/'build/native_window.dll')),token

def worker(args):
    native,token=dll()
    if args.checks_worker:
        function=native.window_native_checks;function.argtypes=[ctypes.c_char_p]*3;function.restype=ctypes.c_int
        result=function(os.fsencode(PARENT/'data/right/780639346578/input.bin'),os.fsencode(ROOT/'reports/window_native'),b'780639346578')
    else:
        function=native.replay_profile;function.argtypes=[ctypes.c_char_p]*4+[ctypes.c_int];function.restype=ctypes.c_int
        source=PARENT/'data'/args.line/args.device/'input.bin';target=ROOT/'results'/args.profile/args.line/args.device
        target.mkdir(parents=True,exist_ok=True)
        result=function(os.fsencode(source),os.fsencode(target/'output.bin'),os.fsencode(target/'status.csv'),args.device.encode(),PROFILE_IDS[args.profile])
    if token:token.close()
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--profile',choices=PROFILES+['all'],default='all');parser.add_argument('--line');parser.add_argument('--device')
    for flag in ['worker','checks-worker','skip-build','build-only','checks-only']:parser.add_argument('--'+flag,action='store_true')
    args=parser.parse_args()
    if args.worker or args.checks_worker:return worker(args)
    before=protected_evidence()
    if not args.skip_build:build()
    if args.build_only:return 0
    with (ROOT/'reports/window_native_checks.log').open('w',encoding='utf-8') as log:
        result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--checks-worker'],stdout=log,stderr=log)
    if result.returncode:raise RuntimeError('Native window checks failed; see reports/window_native_checks.log')
    print('NATIVE_WINDOW_CHECKS_PASSED',flush=True)
    if args.checks_only:return 0
    selected=PROFILES if args.profile=='all' else [args.profile];records=[]
    for profile in selected:
        for source in sorted((PARENT/'data').glob('*/*/input.bin')):
            line,device=source.parent.parent.name,source.parent.name
            if args.line and line!=args.line:continue
            if args.device and device!=args.device:continue
            target=ROOT/'results'/profile/line/device;target.mkdir(parents=True,exist_ok=True)
            started=time.perf_counter()
            with (target/'replay.log').open('w',encoding='utf-8') as log:
                result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker','--profile',profile,'--line',line,'--device',device],stdout=log,stderr=log)
            if result.returncode:raise RuntimeError(f'Window replay failed {profile}/{line}/{device}')
            row=base.verify(profile,line,device);row['wall_seconds']=time.perf_counter()-started
            cfg=row['actual_config'];assert cfg['max_frame_dev']==0
            expected_end=32 if profile in ['current_end08','no_w3_end08','no_w3_tau05_end08','current_fade08'] else 0
            assert cfg['x_apply_end_h']==expected_end
            assert cfg['fade_x_enhancements_with_gate']==(profile in ['current_fade07','current_fade08'])
            if profile=='window_default0':assert row['output_sha256']==base.sha(ROOT/'results/current'/line/device/'output.bin')
            records.append(row);base.write_json(ROOT/'reports/native_window_runs.json',records)
            print(json.dumps({k:row[k] for k in ['profile','line','device','frames','y_bitwise_equal','wall_seconds']}),flush=True)
        done=[r for r in records if r['profile']==profile]
        base.write_json(ROOT/'results'/profile/'manifest.json',dict(profile=profile,devices=len(done),source_manifest='../../build/native_window_manifest.json',runs=done))
        print('PROFILE_DONE '+profile,flush=True)
    after=protected_evidence();assert before==after,'old evidence changed'
    base.write_json(ROOT/'reports/native_window_summary.json',dict(profiles=selected,runs=len(records),devices_per_profile={p:sum(r['profile']==p for r in records) for p in selected},
        frame_total=sum(r['frames'] for r in records),all_y_bitwise_equal=all(r['y_bitwise_equal'] for r in records),all_masks_and_timestamps_equal=all(r['x_finite_mask_equal'] and r['timestamps_equal'] for r in records),
        default0_matches_current_bitwise=all(r['x_changed_cells_vs_prior_astra']==0 for r in records if r['profile']=='window_default0'),
        old_evidence_unchanged=True,protected_old_evidence_sha256=after))
    return 0

if __name__=='__main__':raise SystemExit(main())
