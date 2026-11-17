"""Summarize native replay timings without pooling device quantiles incorrectly."""
from pathlib import Path
import csv
import json

ROOT = Path(__file__).resolve().parents[1]
records = json.loads((ROOT / 'reports/native_runs.json').read_text(encoding='utf-8'))
profiles = ['current', 'no_w3', 'no_s1', 'no_temporal', 'no_s2', 'modal_only']
rows = []
configs = {}
for profile in profiles:
    runs = [r for r in records if r['profile'] == profile]
    assert len(runs) == 12, (profile, len(runs))
    configurations = [r['actual_config'] for r in runs]
    assert all(c == configurations[0] for c in configurations)
    configs[profile] = configurations[0]
    frames = sum(r['frames'] for r in runs)
    timings = [r['timing'] for r in runs]
    rows.append(dict(
        profile=profile, devices=len(runs), frames=frames,
        weighted_mean_process_us=sum(t['process_total_us'] for t in timings)/frames,
        device_p50_min_us=min(t['process_p50_us'] for t in timings),
        device_p50_max_us=max(t['process_p50_us'] for t in timings),
        device_p95_min_us=min(t['process_p95_us'] for t in timings),
        device_p95_max_us=max(t['process_p95_us'] for t in timings),
        device_p99_min_us=min(t['process_p99_us'] for t in timings),
        device_p99_max_us=max(t['process_p99_us'] for t in timings),
        maximum_observed_process_us=max(t['process_max_us'] for t in timings),
        native_process_total_seconds=sum(t['process_total_us'] for t in timings)/1e6,
        workers_total_wall_seconds=sum(r['wall_seconds'] for r in runs),
        x_changed_cells_vs_prior_astra=sum(r['x_changed_cells_vs_prior_astra'] for r in runs),
    ))
    assert configurations[0]['max_frame_dev'] == 0

with (ROOT / 'reports/native_timing_summary.csv').open('w', newline='', encoding='utf-8-sig') as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

report = dict(
    timing_scope='Native Process wall time, including existing buffered diagnostics, excluding input/output files. Worker wall time additionally includes interpreter startup, DLL loading, IO, state export and output verification. This is an observed offline timing result, not a hard realtime guarantee or signal phase-delay result.',
    quantile_note='Device percentile min/max are across 12 devices, not pooled frame percentiles.',
    profiles=rows,
    actual_configs=configs,
)
(ROOT / 'reports/native_timing_summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
for row in rows:
    print(json.dumps(row))
