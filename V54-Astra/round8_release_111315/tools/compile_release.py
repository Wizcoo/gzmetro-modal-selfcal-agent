from pathlib import Path
import json,subprocess,hashlib
root=Path(__file__).resolve().parents[1]
build=root/'build';build.mkdir(exist_ok=True)
compiler=Path(r'C:\msys64\ucrt64\bin\g++.exe')
commands=[
 [str(compiler),'-std=c++17','-fsyntax-only','-I',str(root/'source'),str(root/'tools/compile_check.cpp')],
 [str(compiler),'-std=c++17','-O2','-c','-I',str(root/'source'),str(root/'source/ModalSelfCal.cpp'),'-o',str(build/'ModalSelfCal.o')],
]
records=[]
for i,command in enumerate(commands):
    proc=subprocess.run(command,text=True,capture_output=True,encoding='utf8',errors='replace')
    log=build/f'compile_{i+1}.log';log.write_text(proc.stdout+proc.stderr,encoding='utf8')
    records.append(dict(command=command,returncode=proc.returncode,log=str(log)))
    if proc.returncode:raise RuntimeError(proc.stderr)
result={'passed':True,'native_execution':False,'scope':'C++17 compile-time boundary assertions, public API syntax and full implementation object compilation; no new DLL or EXE executed.',
 'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'source').glob('*')},'commands':records}
(root/'reports/compile_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=True))
