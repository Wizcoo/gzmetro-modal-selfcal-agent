"""Package the two source files plus audited states and integration records."""
from pathlib import Path
import json,zipfile,hashlib

root=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sorted(p.name for p in (root/'source').iterdir())==['ModalSelfCal.cpp','ModalSelfCal.h']
states=json.loads((root/'状态清单.json').read_text(encoding='utf8'))
for row in states['records']:
    source=Path(row['source_state'])
    assert sha(source)==row['state_sha256']
    for name in row['files']:assert (root/name).read_bytes()==source.read_bytes()
    assert (root/row['marker_file']).read_text(encoding='utf8').splitlines()==row['names_in_required_order']
for name,value in states['source_files'].items():assert sha(root/'source'/name)==value
compiled=json.loads((root/'reports/compile_validation.json').read_text(encoding='utf8'))
assert compiled['passed'] and compiled['source_sha256']==states['source_files']
independent=json.loads((root/'reports/independent_release_routing_audit.json').read_text(encoding='utf8'))
assert independent['passed'] and independent['error_count']==0
for value in states['source_files'].values():assert value in json.dumps(independent['code'])

files=sorted((root/'source').glob('*'))+sorted((root/'state').rglob('*'))
files=[p for p in files if p.is_file()]+[root/'接入说明.md',root/'状态清单.json']
files += [p for p in sorted((root/'reports').glob('*')) if p.is_file() and p.name!='package_verification.json']
hashes=''.join(f'{sha(p)}  {p.relative_to(root).as_posix()}\n' for p in files)
sums=root/'SHA256SUMS.txt';sums.write_text(hashes,encoding='utf8',newline='\n');files.append(sums)
target=root/'V54-Astra_单cpp单h_12设备_1113-1115初始状态.zip'
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for p in files:archive.write(p,p.relative_to(root).as_posix())
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    names=archive.namelist()
    assert sum(name.endswith('.cpp') for name in names)==1
    assert sum(name.endswith('.h') for name in names)==1
    assert sum(name.endswith('.state') for name in names)==12
    assert sum(name.endswith('.state.bak') for name in names)==12
    for p in files:assert archive.read(p.relative_to(root).as_posix())==p.read_bytes()
result={'file':target.name,'bytes':target.stat().st_size,'sha256':sha(target),'entries':len(files),
        'cpp_files':1,'h_files':1,'primary_states':12,'backup_states':12,'rosters':12,
        'zip_crc_pass':True,'zip_all_files_byte_equal':True,'state_source_bytes_unchanged':True,
        'new_wrapper_native_execution':False}
(root/'reports/package_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
(root/(target.name+'.sha256')).write_text(result['sha256']+'  '+target.name+'\n',encoding='utf8')
print(json.dumps(result,ensure_ascii=True))
