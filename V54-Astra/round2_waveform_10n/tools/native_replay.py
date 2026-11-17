"""Exact native C++ ablations, each with independent full-history X learning."""
from pathlib import Path
import argparse,ctypes,hashlib,json,os,subprocess,sys,time,struct
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
PARENT=ROOT.parent
GXX=Path(r'C:\msys64\ucrt64\bin\g++.exe')
PROFILES=['current','no_w3','no_s1','no_temporal','no_s2','modal_only']

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write_json(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')

def build():
    source=ROOT/'baseline_src';driver=ROOT/'tools/native_replay.cpp'
    files=[source/'ModalSelfCal.cpp',source/'ModalSelfCal.h',driver]
    before={str(p.relative_to(ROOT)):sha(p) for p in files}
    assert sha(source/'ModalSelfCal.cpp')==sha(PARENT/'src/ModalSelfCal.cpp')
    assert sha(source/'ModalSelfCal.h')==sha(PARENT/'src/ModalSelfCal.h')
    command=[str(GXX),'-std=c++17','-O2','-shared','-static-libgcc','-static-libstdc++','-I',str(source),str(driver),str(source/'ModalSelfCal.cpp'),'-o',str(ROOT/'build/native_replay.dll')]
    compiled=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (ROOT/'build/native_replay_compile.log').write_text(compiled.stdout+compiled.stderr,encoding='utf-8')
    if compiled.returncode:raise RuntimeError(compiled.stderr)
    assert before=={str(p.relative_to(ROOT)):sha(p) for p in files},'source changed during compile'
    record=dict(source_sha256=before,binary='build/native_replay.dll',binary_sha256=sha(ROOT/'build/native_replay.dll'),command=command,
        profile_id_map=dict(enumerate(PROFILES)),max_frame_dev=0,history='independent full continuous chronology for every profile, starting 2026-11-02 22:00; no shared learned X state',
        period_evaluated='night start dates 2026-11-06 through 2026-11-15; left 11/06 source gap must be excluded and disclosed')
    write_json(ROOT/'build/native_replay_manifest.json',record)
    return record

def load_output(p):
    with p.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    dtype=np.dtype([('timestamp','<i8'),('xy','<f8',(2,m))])
    assert p.stat().st_size==8+n*dtype.itemsize
    return np.memmap(p,dtype=dtype,mode='r',offset=8,shape=(n,)),m,n

def verify(profile,line,device):
    folder=ROOT/'results'/profile/line/device
    actual,m,n=load_output(folder/'output.bin')
    reference,mr,nr=load_output(PARENT/'results/astra'/line/device/'output.bin')
    assert (m,n)==(mr,nr)
    timestamps_equal=np.array_equal(actual['timestamp'],reference['timestamp'])
    xmask_equal=np.array_equal(np.isfinite(actual['xy'][:,0]),np.isfinite(reference['xy'][:,0]))
    ybit_equal=np.array_equal(actual['xy'][:,1].view('<u8'),reference['xy'][:,1].view('<u8'))
    xchanged=int(np.count_nonzero(actual['xy'][:,0].view('<u8')!=reference['xy'][:,0].view('<u8')))
    result=dict(profile=profile,line=line,device=device,frames=n,markers=m,timestamps_equal=timestamps_equal,
        x_finite_mask_equal=xmask_equal,y_bitwise_equal=ybit_equal,x_changed_cells_vs_prior_astra=xchanged,
        output_sha256=sha(folder/'output.bin'),input_sha256=sha(PARENT/'data'/line/device/'input.bin'),
        current_entire_output_bitwise_equal=(sha(folder/'output.bin')==sha(PARENT/'results/astra'/line/device/'output.bin')) if profile=='current' else None)
    assert timestamps_equal and xmask_equal and ybit_equal
    if profile=='current':assert result['current_entire_output_bitwise_equal']
    result['actual_config']=json.loads((folder/'output.bin.config.json').read_text())
    result['timing']=json.loads((folder/'output.bin.timing.json').read_text())
    write_json(folder/'verification.json',result)
    return result

def worker(args):
    token=os.add_dll_directory(str(GXX.parent)) if hasattr(os,'add_dll_directory') else None
    native=ctypes.CDLL(str(ROOT/'build/native_replay.dll'))
    fn=native.replay_profile;fn.argtypes=[ctypes.c_char_p]*4+[ctypes.c_int];fn.restype=ctypes.c_int
    source=PARENT/'data'/args.line/args.device/'input.bin'
    output=ROOT/'results'/args.profile/args.line/args.device;output.mkdir(parents=True,exist_ok=True)
    rc=fn(os.fsencode(source),os.fsencode(output/'output.bin'),os.fsencode(output/'status.csv'),args.device.encode(),PROFILES.index(args.profile))
    if token:token.close()
    return rc

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',choices=PROFILES+['all'],default='all');p.add_argument('--line');p.add_argument('--device');p.add_argument('--worker',action='store_true');p.add_argument('--skip-build',action='store_true');p.add_argument('--build-only',action='store_true');args=p.parse_args()
    if args.worker:return worker(args)
    if not args.skip_build:build()
    if args.build_only:return 0
    profiles=PROFILES if args.profile=='all' else [args.profile]
    records=[]
    for profile in profiles:
        for source in sorted((PARENT/'data').glob('*/*/input.bin')):
            line,device=source.parent.parent.name,source.parent.name
            if args.line and args.line!=line:continue
            if args.device and args.device!=device:continue
            dest=ROOT/'results'/profile/line/device;dest.mkdir(parents=True,exist_ok=True)
            command=[sys.executable,str(Path(__file__).resolve()),'--worker','--profile',profile,'--line',line,'--device',device]
            started=time.perf_counter()
            with (dest/'replay.log').open('w',encoding='utf-8') as log:r=subprocess.run(command,stdout=log,stderr=log)
            if r.returncode:raise RuntimeError(f'Native replay failed {profile}/{line}/{device}; {dest}/replay.log')
            row=verify(profile,line,device);row['wall_seconds']=time.perf_counter()-started;records.append(row)
            write_json(ROOT/'reports/native_runs.json',records)
            print(json.dumps({k:row[k] for k in ['profile','line','device','frames','y_bitwise_equal','wall_seconds']}),flush=True)
        done=[r for r in records if r['profile']==profile]
        write_json(ROOT/'results'/profile/'manifest.json',dict(profile=profile,devices=len(done),source_manifest='../../build/native_replay_manifest.json',runs=done))
        print('PROFILE_DONE '+profile,flush=True)
    assert records
    write_json(ROOT/'reports/native_summary.json',dict(profiles=profiles,runs=len(records),devices_per_profile={profile:sum(r['profile']==profile for r in records) for profile in profiles},
        all_y_bitwise_equal=all(r['y_bitwise_equal'] for r in records),all_masks_and_timestamps_equal=all(r['x_finite_mask_equal'] and r['timestamps_equal'] for r in records),
        current_matches_previous_release=all(r['current_entire_output_bitwise_equal'] for r in records if r['profile']=='current'),
        frame_total=sum(r['frames'] for r in records),timing_note='Native Process wall time includes existing buffered diagnostics; excludes input/output stream operations. Signal phase delay is measured separately.'))
    return 0

if __name__=='__main__':raise SystemExit(main())
