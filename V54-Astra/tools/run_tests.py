from pathlib import Path
import argparse,ctypes,os,subprocess,sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
GXX=Path(r'C:\msys64\ucrt64\bin\g++.exe')

def worker(suite):
    token=os.add_dll_directory(str(GXX.parent))
    lib=ctypes.CDLL(str(ROOT/'build'/('test_'+suite+'.dll')))
    if suite=='astra':
        fn=lib.run_tests;fn.argtypes=[ctypes.c_char_p];fn.restype=ctypes.c_int
        result=fn(os.fsencode(ROOT/'reports/test_astra.json'))
    else:
        fn=lib.run_legacy_tests;fn.argtypes=[];fn.restype=ctypes.c_int;result=fn()
    token.close();return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--worker',choices=['astra','legacy']);p.add_argument('--suite',choices=['astra','legacy','both'],default='both');args=p.parse_args()
    if args.worker:return worker(args.worker)
    suites=['astra','legacy'] if args.suite=='both' else [args.suite]
    existing=ROOT/'reports/test_runs.json'
    records=json.loads(existing.read_text(encoding='utf-8')) if existing.exists() else []
    for suite in suites:
        if suite=='legacy':
            text=(ROOT/'baseline/test_v54.cpp').read_text(encoding='utf-8').replace('int main()', 'int legacy_main()')
            text+='\nextern "C" __declspec(dllexport) int run_legacy_tests(){return legacy_main();}\n'
            (ROOT/'tests/legacy_v54.cpp').write_text(text,encoding='utf-8')
        source=ROOT/'tests'/('test_history.cpp' if suite=='astra' else 'legacy_v54.cpp')
        target=ROOT/'build'/('test_'+suite+'.dll')
        cmd=[str(GXX),'-std=c++17','-O2','-shared','-static-libgcc','-static-libstdc++','-I',str(ROOT/'src'),str(source)]
        if suite=='legacy':cmd.append(str(ROOT/'src/ModalSelfCal.cpp'))
        cmd+=['-o',str(target)]
        files=[ROOT/'src/ModalSelfCal.cpp',ROOT/'src/ModalSelfCal.h',source]
        hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        r=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
        (ROOT/'build'/('test_'+suite+'_compile.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError(r.stderr)
        if hashes!={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}:raise RuntimeError('source changed during compilation')
        with (ROOT/'reports'/('test_'+suite+'.log')).open('w',encoding='utf-8') as f:r=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',suite],stdout=f,stderr=f)
        record=dict(suite=suite,exit_code=r.returncode,binary_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),sources_sha256=hashes)
        records=[r for r in records if r['suite']!=suite];records.append(record);print(json.dumps(record),flush=True)
        (ROOT/'reports/test_runs.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        if r.returncode:return r.returncode
    return 0
if __name__=='__main__':raise SystemExit(main())
