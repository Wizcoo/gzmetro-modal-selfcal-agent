"""Verify the user's 23-07 output contract over frozen native replay results.

This is an output selector audit, not a new native modal replay. Core processing
must continue outside the published correction window to preserve history.
"""
from pathlib import Path
from datetime import datetime
import sys, json
import numpy as np
import pandas as pd
from window_xj_audit import read, sha, ms, iso, TZ

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent
REPORT = ROOT / 'reports'
sys.path.insert(0, str(BASE / 'round3_physics_failure/tools'))
import chinese_failure_atlas as atlas

DAY = 86400000
HOUR = 3600000


def correction_window(timestamps):
    local_ms = (timestamps % DAY + 8 * HOUR) % DAY
    return (local_ms >= 23 * HOUR) | (local_ms < 7 * HOUR)


def same(a, b):
    assert np.array_equal(np.isnan(a), np.isnan(b))
    assert np.array_equal(a[~np.isnan(a)], b[~np.isnan(b)])


def main():
    checks, events = [], []
    examples = [('left', '780638327479', 'ZD4703', '2026-11-12')]
    old_meta = json.loads((BASE / 'round2_waveform_10n/reports/latency_plot_examples.json').read_text(encoding='utf8'))
    b = old_meta['boundary']
    examples.append((b['line'], b['device'], b['marker'], b['night']))
    figures = {}
    # Explicit half-open boundary contract, plus absence of state at restart.
    boundary_times = [ms('2026-11-07 ' + s) for s in ['06:59:59.999', '07:00:00', '22:59:59.999', '23:00:00']]
    assert correction_window(np.array(boundary_times)).tolist() == [True, False, False, True]
    for source in sorted((BASE / 'data').glob('*/*/input.npz')):
        line, device = source.parent.parent.name, source.parent.name
        with np.load(source) as d:
            ts, names, raw, cal = d['timestamp'], list(d['names']), d['x'], d['online_x']
        output = BASE / f'round2_waveform_10n/results/current_fade07/{line}/{device}/output.bin'
        native = read(output)
        assert np.array_equal(ts, native['timestamp'])
        active = correction_window(ts)
        result = np.array(native['xy'])
        result[~active, 0, :] = raw[~active]
        same(result[active, 0, :], native['xy'][active, 0, :])
        same(result[~active, 0, :], raw[~active])
        same(result[:, 1, :], native['xy'][:, 1, :])
        # A new selector instance has no prior offset/filter state to restore.
        for split in [len(ts) // 3, 2 * len(ts) // 3]:
            part_active = correction_window(ts[split:])
            part = np.where(part_active[:, None], native['xy'][split:, 0, :], raw[split:])
            same(part, result[split:, 0, :])
        checks.append(dict(line=line, device=device, frames=len(ts), markers=len(names),
            active_frames=int(active.sum()), raw_frames=int((~active).sum()),
            active_finite_x=int(np.isfinite(result[active, 0, :]).sum()),
            raw_finite_x=int(np.isfinite(result[~active, 0, :]).sum()),
            input_sha256=sha(source), native_sha256=sha(output),
            active_exact=True, outside_raw_exact=True, y_exact=True, masks_preserved=True,
            selector_chunk_restart_exact=True))
        for day in range(6, 16):
            night = f'2026-11-{day:02d}'
            boundary = ms(night + ' 23:00') + 8 * HOUR
            k = int(np.searchsorted(ts, boundary))
            if k == 0 or k == len(ts) or ts[k] - boundary > 3 * 60000 or boundary - ts[k-1] > 3 * 60000:
                continue
            for j, name in enumerate(names):
                if not np.isfinite(result[k-1:k+1, 0, j]).all() or not np.isfinite(raw[k-1:k+1, j]).all():
                    continue
                events.append(dict(line=line, device=device, marker=name, night=night,
                    previous_time=iso(ts[k-1]), first_raw_time=iso(ts[k]),
                    gap_minutes=float((ts[k]-ts[k-1])/60000),
                    raw_step=float(raw[k,j]-raw[k-1,j]),
                    old_fade_step=float(native['xy'][k,0,j]-native['xy'][k-1,0,j]),
                    selected_step=float(result[k,0,j]-result[k-1,0,j]),
                    selected_minus_raw_after_boundary=float(result[k,0,j]-raw[k,j]),
                    segment_change=True))
        for ex_line, ex_device, marker, night in examples:
            if (line,device) != (ex_line,ex_device):
                continue
            j=names.index(marker)
            boundary=ms(night+' 23:00')+8*HOUR
            selected=(ts>=boundary-30*60000)&(ts<boundary+60*60000)
            local_ts=ts[selected]
            values=np.column_stack([raw[selected,j],cal[selected,j],result[selected,0,j],native['xy'][selected,0,j]])
            frame=pd.DataFrame(dict(timestamp_ms=local_ts, time=[iso(v) for v in local_ts],
                raw_x=values[:,0],database_calX=values[:,1],selected_x=values[:,2],old_fade_x=values[:,3],
                segment=np.where(correction_window(local_ts),'night_corrected','day_raw')))
            frame.to_csv(REPORT/f'exit_output_{device}_{marker}_{night}.csv',encoding='utf-8-sig',index=False)
            figures[(device,marker,night)]=(local_ts,values,boundary)
    pd.DataFrame(events).to_csv(REPORT/'exit_output_boundary_events.csv',encoding='utf-8-sig',index=False)
    summary=dict(contract='[23:00, next 07:00) Asia/Shanghai selects native Astra X; otherwise selects pre-W3 raw X; Y unchanged',
        scope='Offline selector over frozen native output; no new native DLL or physical event validation',
        devices=len(checks), total_device_frames=sum(c['frames'] for c in checks),
        active_finite_x=sum(c['active_finite_x'] for c in checks),raw_finite_x=sum(c['raw_finite_x'] for c in checks),
        boundary_point_events=len(events),boundary_segment_change_is_not_physical_motion=True,
        endpoint_cases_passed=4,selector_restart_checks=2*len(checks),checks=checks)
    (REPORT/'exit_output_verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    plt=atlas.plt
    fig, axes=plt.subplots(len(figures),1,figsize=(14,8.6),layout='constrained')
    for ax, ((device,marker,night),(t,v,boundary)) in zip(axes,figures.items()):
        px,pv=atlas.plot_input(t,v)
        ax.plot(px,pv[:,0],color='#77818d',lw=1.3,label='数据库 raw X')
        ax.plot(px,pv[:,1],color='#2871b9',lw=1.1,ls='--',label='原算法 calX（数据库）')
        ax.plot(px,pv[:,3],color='#ae8a52',lw=1.15,ls=':',label='此前 Astra 渐退输出（对照）')
        # Do not join corrected coordinates to raw coordinates across the switch.
        for flag in [True,False]:
            mask=correction_window(t)==flag
            sx,sy=atlas.plot_input(t[mask],v[mask,2:3])
            ax.plot(sx,sy[:,0],color='#cb493e',lw=1.6,label='本次输出：07点前修正／之后raw' if flag else None)
        atlas.setup_axis(ax,int(t[0]),boundary+60*60000)
        dt=datetime.fromtimestamp(boundary/1000,TZ)
        ax.axvline(dt,color='#7a4552',ls='--',lw=1)
        ax.axvspan(dt,datetime.fromtimestamp((boundary+60*60000)/1000,TZ),color='#cbd8de',alpha=.18)
        ax.text(.99,.50 if marker=='ZD4703' else .96,'07:00起：原始观测段\n边界不连线，不计作物理峰谷',transform=ax.transAxes,ha='right',va='top',fontsize=10)
        ax.set_title(f'左线 {device} / {marker}｜{night}夜退出对照',fontsize=12)
        ax.set_xlabel('北京时间；原采集时间与数值基准，无额外平滑或时间平移')
    fig.suptitle('07点后只看原始：结束修正段，不再输出07:00—07:20渐退斜坡',fontsize=15)
    fig.legend(*axes[0].get_legend_handles_labels(),loc='outside lower center',ncol=2,fontsize=10)
    fig.savefig(ROOT/'plots/exit_output_contract.png',dpi=160)
    plt.close(fig)
    print(json.dumps({k:v for k,v in summary.items() if k!='checks'},ensure_ascii=True))


if __name__ == '__main__':
    main()
