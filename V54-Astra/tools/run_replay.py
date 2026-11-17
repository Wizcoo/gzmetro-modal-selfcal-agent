"""Compile the exact C++ sources and execute through a native DLL.

The DLL path is an ordinary Windows loader route; no interpreter reimplementation
or changes to Windows policy are used. All outputs stay in V54-Astra.
"""
from pathlib import Path
import argparse,ctypes,hashlib,json,os,subprocess,sys,time

ROOT=Path(__file__).resolve().parents[1]
GXX=Path(r'C:\msys64\ucrt64\bin\g++.exe')

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def compile_native(variant):
    source=ROOT/('src' if variant=='astra' else 'baseline')
    target=ROOT/'build'/('replay_'+variant+'.dll')
    args=[str(GXX),'-std=c++17','-O2','-shared','-static-libgcc','-static-libstdc++','-I',str(source),str(ROOT/'tools/replay.cpp'),str(source/'ModalSelfCal.cpp'),'-o',str(target)]
    files=[source/'ModalSelfCal.cpp',source/'ModalSelfCal.h']
    hashes={p.name:digest(p) for p in files}
    r=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (ROOT/'build'/('compile_'+variant+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError('compile failed '+variant+'\n'+r.stderr)
    if hashes!={p.name:digest(p) for p in files}:raise RuntimeError('source changed during compilation')
    return dict(variant=variant,command=args,source_sha256=hashes,driver_sha256=digest(ROOT/'tools/replay.cpp'),binary=str(target),binary_sha256=digest(target))

def worker(args):
    # The compiler runtime is available by explicit DLL search directory.
    token=os.add_dll_directory(str(GXX.parent)) if hasattr(os,'add_dll_directory') else None
    library=ctypes.CDLL(str(ROOT/'build'/('replay_'+args.variant+'.dll')))
    fn=library.replay_files;fn.argtypes=[ctypes.c_char_p]*4+[ctypes.c_double];fn.restype=ctypes.c_int
    folder=ROOT/'data'/args.line/args.device
    output=ROOT/'results'/args.variant/args.line/args.device;output.mkdir(parents=True,exist_ok=True)
    rc=fn(os.fsencode(folder/'input.bin'),os.fsencode(output/'output.bin'),os.fsencode(output/'status.csv'),args.device.encode(),args.max_frame_dev)
    if token:token.close()
    return rc

def main():
    p=argparse.ArgumentParser();p.add_argument('--variant',choices=['baseline','astra','both'],default='both');p.add_argument('--line');p.add_argument('--device');p.add_argument('--max-frame-dev',type=float,default=0.0);p.add_argument('--worker',action='store_true');p.add_argument('--build-only',action='store_true');p.add_argument('--skip-build',action='store_true');args=p.parse_args()
    if args.worker:return worker(args)
    variants=['baseline','astra'] if args.variant=='both' else [args.variant]
    builds=[compile_native(v) for v in variants] if not args.skip_build else []
    if builds:(ROOT/'build'/('manifest_'+args.variant+'.json')).write_text(json.dumps(builds,indent=2),encoding='utf-8')
    if args.build_only:return 0
    jobs=[]
    for path in sorted((ROOT/'data').glob('*/*/input.bin')):
        line,device=path.parent.parent.name,path.parent.name
        if args.line and args.line!=line:continue
        if args.device and args.device!=device:continue
        for variant in variants:jobs.append((variant,line,device))
    if not jobs:raise RuntimeError('no matching input.bin')
    manifest=[]
    for variant,line,device in jobs:
        dest=ROOT/'results'/variant/line/device;dest.mkdir(parents=True,exist_ok=True)
        cmd=[sys.executable,str(Path(__file__).resolve()),'--worker','--variant',variant,'--line',line,'--device',device,'--max-frame-dev',str(args.max_frame_dev)]
        started=time.time()
        with (dest/'replay.log').open('w',encoding='utf-8') as f:r=subprocess.run(cmd,stdout=f,stderr=f)
        record=dict(variant=variant,line=line,device=device,exit_code=r.returncode,seconds=time.time()-started,max_frame_dev=args.max_frame_dev)
        manifest.append(record);print(json.dumps(record),flush=True)
        (ROOT/'results'/('runs_'+args.variant+'.json')).write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        if r.returncode:raise RuntimeError(f'{variant} {line}/{device} failed; inspect replay.log')
    return 0

if __name__=='__main__':raise SystemExit(main())
