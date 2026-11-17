"""Copy the audited native snapshots without changing a single byte."""
from pathlib import Path
import hashlib,json

root=Path(__file__).resolve().parents[1]
audit_path=root/'reports/state_source_review.json'
audit=json.loads(audit_path.read_text(encoding='utf8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert audit['summary']['devices']==12
assert audit['summary']['exact_requested_history_all_devices']
assert audit['summary']['all_checksums_valid']
assert audit['summary']['all_pairwise_hist_N_equal_frozen_input']
records=[]
for r in audit['devices']:
    source=Path(r['source_state']);assert sha(source)==r['state_sha256']
    assert r['config_matches_profile14']
    for axis in ['axis_x','axis_y']:
        assert [h['night'] for h in r[axis]['histories']]==['2026-11-13','2026-11-14','2026-11-15']
    folder=root/'state'/('左线' if r['line']=='left' else '右线');folder.mkdir(parents=True,exist_ok=True)
    targets=[folder/(r['device']+'.state'),folder/(r['device']+'.state.bak')]
    content=source.read_bytes()
    for target in targets:
        if target.exists():assert target.read_bytes()==content,'Refuse to overwrite different delivery state'
        else:target.write_bytes(content)
        assert target.read_bytes()==content
    names=r['marker_names_in_required_import_order']
    roster=folder/(r['device']+'.markers.txt')
    roster.write_text('\n'.join(names)+'\n',encoding='utf8',newline='\n')
    assert roster.read_text(encoding='utf8').splitlines()==names
    low=[]
    for name in names:
        count=sum(h['valid_frames_by_marker'][name] for h in r['axis_x']['histories'])
        if count<576:low.append({'marker':name,'valid':count,'expected':720,'ratio':count/720})
    records.append({k:r[k] for k in ['line','device','state_sha256','bytes','timestamp_ms','last_frame_local','marker_count','config_fingerprint']} | {
        'files':[p.relative_to(root).as_posix() for p in targets],'marker_file':roster.relative_to(root).as_posix(),
        'marker_file_sha256':sha(roster),'names_in_required_order':names,'history_nights':audit['required_history_nights'],
        'source_state':str(source),'source_copy_byte_exact':True,'low_history_coverage':low})
manifest={'release':'V54-Astra 2026-11-16','profile':'current_fade07','devices':12,'markers':sum(r['marker_count'] for r in records),
    'state_files':24,'primary_state_files':12,'backup_is_identical_initial_copy':True,
    'history_nights':audit['required_history_nights'],'history_window':'22:00 to next02:00 (end exclusive), UTC+8',
    'publication_x_window':'23:00 to next07:00 (end exclusive), UTC+8',
    'intended_first_night':'2026-11-16','future_history':'rolling, no daily package replacement',
    'new_wrapper_native_execution':False,'external_native_roundtrip_completed':False,
    'state_source_audit_sha256':sha(audit_path),'source_files':{p.name:sha(p) for p in (root/'source').glob('*')},
    'records':records}
(root/'状态清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in manifest.items() if k not in ['records','source_files']},ensure_ascii=True))
