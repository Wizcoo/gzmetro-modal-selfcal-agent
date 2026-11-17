"""Attach confirmed pixel units and summarize audited data coverage."""
import json
from pathlib import Path
from data_prepare import ROOT,dump

unit_path=ROOT/'reports/user_confirmed_units.json'
units=json.loads(unit_path.read_text(encoding='utf-8'))
scale_path=ROOT/'reports/data_scale_audit.json'
s=json.loads(scale_path.read_text(encoding='utf-8'))
s['initial_audit_status']=s.get('initial_audit_status',s['status'])
s['status']='INPUT_PIXEL_UNITS_USER_CONFIRMED_NO_SCALE_CONVERSION'
s['data_units']='x/y are pixels, explicitly confirmed by the user on 2026-11-16. calX/calY have the same dimensions; scale is not applied.'
s['unit_confirmation_file']=str(unit_path)
dump(scale_path,s)
coverage=json.loads((ROOT/'reports/data_coverage.json').read_text(encoding='utf-8'))
missing=[];partial=[]
for e in coverage:
    e['input_units']='pixel'
    e['scale_conversion']='none; user confirmed x/y already pixel'
    dump(ROOT/'data'/e['line']/e['device']/'coverage.json',e)
    for n in e['nights']:
        r=dict(line=e['line'],device=e['device'],**n)
        if n['frames']==0:missing.append(r)
        elif n['frames']<600:partial.append(r)
dump(ROOT/'reports/data_coverage.json',coverage)
validation=json.loads((ROOT/'reports/data_validation.json').read_text(encoding='utf-8'))
summary=dict(period='2026-11-02 22:00 <= timestamp < 2026-11-16 08:00, Asia/Shanghai',input_units='pixel',scale_conversion='none',devices=len(coverage),markers=sum(r['markers'] for r in coverage),device_frames=sum(r['frames'] for r in coverage),night_count_per_device=14,night_device_slots=len(coverage)*14,missing_night_device_slots=len(missing),present_night_device_slots=len(coverage)*14-len(missing),missing_nights=missing,partial_nights=partial,latest_night_frames_per_device={r['line']+'/'+r['device']:r['nights'][-1]['frames'] for r in coverage},binary_npz_and_finite_mask_validation='PASS',latest_independent_original_extract_comparison_frames=validation['total_latest_frames_compared'],source_recovery='Only left source file 4 needed recovery; source and recovered SHA-256 exactly matched prior verified recovery. Updated left7/8 and right10/11 now read directly after current quick_check passed.',deduplication='Identical (device,timestamp,markerName) duplicates collapse; any differing source values abort. No conflicting duplicates found.',missing_data='No fabricated frames, no interpolation; daytime retained. Invalid ROI/nonfinite values become NaN per axis.',units_confirmation=str(unit_path))
dump(ROOT/'reports/data_summary.json',summary)
print(json.dumps({k:v for k,v in summary.items() if k not in ['missing_nights','partial_nights','latest_night_frames_per_device']},ensure_ascii=False))
