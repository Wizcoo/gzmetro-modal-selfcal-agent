"""Record and compare replay evidence after a comment/config-validation rebuild."""
from pathlib import Path
import argparse,json
import native_replay as base
from native_window import PROFILES

ROOT=base.ROOT
parser=argparse.ArgumentParser()
parser.add_argument('--record',action='store_true')
args=parser.parse_args()
records={}
for profile in PROFILES:
    for folder in sorted((ROOT/'results'/profile).glob('*/*')):
        if not folder.is_dir():continue
        for name in ['output.bin','status.csv','output.bin.state','output.bin.config.json']:
            file=folder/name
            records[str(file.relative_to(ROOT))]=base.sha(file)
snapshot=ROOT/'reports/window_evidence_before_final_replay.json'
assert len(records)==72*4
if args.record:
    base.write_json(snapshot,records)
    print('RECORDED',len(records))
else:
    before=json.loads(snapshot.read_text(encoding='utf-8'))
    assert before==records,'window replay evidence changed after comment/config guard'
    manifest=json.loads((ROOT/'build/native_window_manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['source_sha256'].items():
        assert base.sha(ROOT/name)==expected,name
    assert base.sha(ROOT/manifest['binary'])==manifest['binary_sha256']
    report=dict(verified_devices=72,verified_files=len(records),
        all_outputs_status_snapshots_configs_bitwise_same_as_before_guard=True,
        final_source_and_binary_hashes_match_manifest=True,
        manifest_sha256=base.sha(ROOT/'build/native_window_manifest.json'),
        source_sha256=manifest['source_sha256'],binary_sha256=manifest['binary_sha256'])
    base.write_json(ROOT/'reports/window_final_rebuild_verification.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
