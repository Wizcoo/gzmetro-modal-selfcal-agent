from pathlib import Path
import hashlib,json,argparse
def main():
    p=argparse.ArgumentParser();p.add_argument('--require-replay-data',action='store_true');a=p.parse_args()
    base=Path(__file__).resolve().parents[1]
    manifest=json.loads((base/'SNAPSHOT_MANIFEST.json').read_text(encoding='utf8'))
    rows=manifest['files']+(manifest.get('omitted_replay_files',[]) if a.require_replay_data else [])
    for row in rows:
        f=base/row['path'];assert f.is_file(),'Missing: '+row['path']
        assert f.stat().st_size==row['bytes'],'Size differs: '+row['path']
        assert hashlib.sha256(f.read_bytes()).hexdigest()==row['sha256'],'SHA differs: '+row['path']
    print(json.dumps({'verified_files':len(rows),'replay_payload_required':a.require_replay_data,'native_executed':False}))
if __name__=='__main__':main()
