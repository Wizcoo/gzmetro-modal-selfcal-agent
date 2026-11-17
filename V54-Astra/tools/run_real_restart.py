"""Native real-stream restart checks on two representative large rosters.

Only first-night warmup plus the second night through the final checkpoint's
20 following frames are processed; this does not repeat the multi-night replay.
"""
from pathlib import Path
import argparse,ctypes,hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
GXX=Path(r'C:\msys64\ucrt64\bin\g++.exe')
REPRESENTATIVES=[('left','780638310097'),('right','780639346578')]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--line');p.add_argument('--device');p.add_argument('--build-only',action='store_true');args=p.parse_args()
    dll=ROOT/'build/test_real_restart.dll'
    if args.worker:
        token=os.add_dll_directory(str(GXX.parent));lib=ctypes.CDLL(str(dll));fn=lib.run_real_restart;fn.argtypes=[ctypes.c_char_p]*3;fn.restype=ctypes.c_int
        result=fn(os.fsencode(ROOT/'data'/args.line/args.device/'input.bin'),os.fsencode(ROOT/'reports'/('test_real_restart_'+args.line+'_'+args.device+'.json')),args.device.encode());token.close();return result
    files=[ROOT/'src/ModalSelfCal.cpp',ROOT/'src/ModalSelfCal.h',ROOT/'tests/test_real_restart.cpp']
    hashes={str(p.relative_to(ROOT)):sha(p) for p in files}
    cmd=[str(GXX),'-std=c++17','-O2','-shared','-static-libgcc','-static-libstdc++','-I',str(ROOT/'src'),str(ROOT/'tests/test_real_restart.cpp'),str(ROOT/'src/ModalSelfCal.cpp'),'-o',str(dll)]
    r=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace');(ROOT/'build/test_real_restart_compile.log').write_text(r.stdout+r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError(r.stderr)
    if hashes!={str(p.relative_to(ROOT)):sha(p) for p in files}:raise RuntimeError('source changed during compilation')
    manifest=dict(sources_sha256=hashes,binary_sha256=sha(dll),command=cmd,runs=[])
    if not args.build_only:
        selected=[(args.line,args.device)] if args.line and args.device else REPRESENTATIVES
        for line,device in selected:
            started=time.time()
            with (ROOT/'reports'/('test_real_restart_'+line+'_'+device+'.log')).open('w',encoding='utf-8') as f:r=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker','--line',line,'--device',device],stdout=f,stderr=f)
            record=dict(line=line,device=device,exit_code=r.returncode,seconds=time.time()-started);manifest['runs'].append(record);print(json.dumps(record),flush=True)
            (ROOT/'reports/test_real_restart_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            if r.returncode:return r.returncode
    else:(ROOT/'reports/test_real_restart_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return 0
if __name__=='__main__':raise SystemExit(main())
