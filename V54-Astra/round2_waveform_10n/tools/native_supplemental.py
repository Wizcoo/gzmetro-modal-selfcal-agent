"""Native parameter sensitivity runs; preserves the original six-profile evidence."""
from pathlib import Path
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import native_replay as base

ROOT = base.ROOT
PARENT = base.PARENT
GXX = base.GXX
PROFILES = ['no_w3_tau05', 'no_w3_s2_070', 'no_temporal_s2_070', 'no_temporal_s2_085']
PROFILE_IDS = dict(zip(PROFILES, range(6, 10)))

CONFIG_FUNCTION = '''static ModalSelfCalConfig profile_config(int profile){
    if(profile<6||profile>9)throw std::runtime_error("invalid supplemental profile");
    ModalSelfCalConfig cfg; cfg.max_frame_dev=0.0;
    cfg.enable_x_w3_filter=false;
    if(profile==6)cfg.velocity_damping_tau_min=0.5;
    if(profile==7||profile==8)cfg.mount_drift_shrinkage=0.70;
    if(profile==9)cfg.mount_drift_shrinkage=0.85;
    if(profile==8||profile==9)cfg.enable_x_velocity_damping=false;
    return cfg;
}

'''

def old_evidence():
    paths = [ROOT/'build/native_replay_manifest.json', ROOT/'build/native_replay.dll',
             ROOT/'tools/native_replay.cpp', ROOT/'tools/native_replay.py',
             ROOT/'reports/native_runs.json', ROOT/'reports/native_summary.json']
    for profile in base.PROFILES:
        paths.append(ROOT/'results'/profile/'manifest.json')
    return {str(p.relative_to(ROOT)):base.sha(p) for p in paths}

def build():
    driver = ROOT/'tools/native_supplemental.cpp'
    original = (ROOT/'tools/native_replay.cpp').read_text(encoding='utf-8')
    start = original.index('static ModalSelfCalConfig profile_config(')
    end = original.index('static void write_config(', start)
    driver.write_text(original[:start]+CONFIG_FUNCTION+original[end:], encoding='utf-8')
    source = ROOT/'baseline_src'
    files = [source/'ModalSelfCal.cpp', source/'ModalSelfCal.h', driver, Path(__file__).resolve()]
    before = {str(p.relative_to(ROOT)):base.sha(p) for p in files}
    previous = json.loads((ROOT/'build/native_replay_manifest.json').read_text(encoding='utf-8'))
    for name in ['ModalSelfCal.cpp','ModalSelfCal.h']:
        assert base.sha(source/name) == previous['source_sha256'][str(Path('baseline_src')/name)]
    command = [str(GXX),'-std=c++17','-O2','-shared','-static-libgcc','-static-libstdc++',
               '-I',str(source),str(driver),str(source/'ModalSelfCal.cpp'),'-o',str(ROOT/'build/native_supplemental.dll')]
    result = subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (ROOT/'build/native_supplemental_compile.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError(result.stderr)
    assert before == {str(p.relative_to(ROOT)):base.sha(p) for p in files}
    base.write_json(ROOT/'build/native_supplemental_manifest.json',dict(
        source_sha256=before, binary='build/native_supplemental.dll',
        binary_sha256=base.sha(ROOT/'build/native_supplemental.dll'), command=command,
        profile_id_map={str(v):k for k,v in PROFILE_IDS.items()},
        max_frame_dev=0,
        history='Each profile starts from the complete chronological input, including daytime, at 2026-11-02 22:00. No states are shared across profiles.',
        baseline_manifest='build/native_replay_manifest.json', baseline_manifest_sha256=base.sha(ROOT/'build/native_replay_manifest.json')))

def worker(args):
    token = os.add_dll_directory(str(GXX.parent)) if hasattr(os,'add_dll_directory') else None
    native = ctypes.CDLL(str(ROOT/'build/native_supplemental.dll'))
    function = native.replay_profile
    function.argtypes = [ctypes.c_char_p]*4+[ctypes.c_int]
    function.restype = ctypes.c_int
    source = PARENT/'data'/args.line/args.device/'input.bin'
    target = ROOT/'results'/args.profile/args.line/args.device
    target.mkdir(parents=True,exist_ok=True)
    result = function(os.fsencode(source),os.fsencode(target/'output.bin'),os.fsencode(target/'status.csv'),args.device.encode(),PROFILE_IDS[args.profile])
    if token:token.close()
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=PROFILES+['all'], default='all')
    parser.add_argument('--line')
    parser.add_argument('--device')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--build-only', action='store_true')
    args = parser.parse_args()
    if args.worker:return worker(args)
    protected_before = old_evidence()
    if not args.skip_build:build()
    if args.build_only:return 0
    selected = PROFILES if args.profile=='all' else [args.profile]
    records = []
    for profile in selected:
        for source in sorted((PARENT/'data').glob('*/*/input.bin')):
            line,device = source.parent.parent.name,source.parent.name
            if args.line and line != args.line:continue
            if args.device and device != args.device:continue
            destination = ROOT/'results'/profile/line/device
            destination.mkdir(parents=True,exist_ok=True)
            command = [sys.executable,str(Path(__file__).resolve()),'--worker','--profile',profile,'--line',line,'--device',device]
            started = time.perf_counter()
            with (destination/'replay.log').open('w',encoding='utf-8') as log:
                result = subprocess.run(command,stdout=log,stderr=log)
            if result.returncode:raise RuntimeError(f'Native replay failed {profile}/{line}/{device}')
            row = base.verify(profile,line,device)
            row['wall_seconds'] = time.perf_counter()-started
            cfg = row['actual_config']
            assert cfg['max_frame_dev']==0 and not cfg['enable_x_w3_filter']
            assert cfg['enable_x_mount_drift_damping']
            assert cfg['enable_x_velocity_damping'] == (profile in PROFILES[:2])
            assert cfg['mount_drift_shrinkage'] == (0.55 if profile==PROFILES[0] else 0.85 if profile==PROFILES[3] else 0.70)
            assert cfg['velocity_damping_tau_min'] == (0.5 if profile==PROFILES[0] else 1.5)
            records.append(row)
            base.write_json(ROOT/'reports/native_supplemental_runs.json',records)
            print(json.dumps({k:row[k] for k in ['profile','line','device','frames','y_bitwise_equal','wall_seconds']}),flush=True)
        done = [r for r in records if r['profile']==profile]
        base.write_json(ROOT/'results'/profile/'manifest.json',dict(profile=profile,devices=len(done),source_manifest='../../build/native_supplemental_manifest.json',runs=done))
        print('PROFILE_DONE '+profile,flush=True)
    protected_after = old_evidence()
    assert protected_before == protected_after, 'original evidence changed during supplemental replay'
    base.write_json(ROOT/'reports/native_supplemental_summary.json',dict(
        profiles=selected,runs=len(records),devices_per_profile={p:sum(r['profile']==p for r in records) for p in selected},
        all_y_bitwise_equal=all(r['y_bitwise_equal'] for r in records),
        all_masks_and_timestamps_equal=all(r['x_finite_mask_equal'] and r['timestamps_equal'] for r in records),
        frame_total=sum(r['frames'] for r in records),
        old_evidence_unchanged=True,protected_old_evidence_sha256=protected_after,
        timing_note='Native Process wall time includes existing buffered diagnostics; excludes input/output stream operations. Signal phase delay is measured separately.'))
    return 0

if __name__=='__main__':raise SystemExit(main())
