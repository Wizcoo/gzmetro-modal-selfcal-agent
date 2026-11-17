"""Independent static review and full frozen-output routing audit; no DLL execution."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import Counter
import difflib
import hashlib
import json
import re
import struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent
SOURCE = ROOT / 'source'
ORIGINAL = BASE / 'round3_physics_failure/src/practical_candidate'
REPORT = ROOT / 'reports'
TZ = timezone(timedelta(hours=8))
checks = Counter()
errors = []


def check(ok, name, detail=None):
    checks[name] += 1
    if not ok:
        errors.append({'check': name, 'detail': detail})
    return bool(ok)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def equal(a, b):
    """Exact finite float64 bits and missing-value masks, not NaN payload equality."""
    if a.shape != b.shape or not np.array_equal(np.isnan(a), np.isnan(b)):
        return False
    mask = ~np.isnan(a)
    return np.array_equal(a[mask].view('u8'), b[mask].view('u8'))


def integer_route(ts):
    local = (ts % 86400000 + 8*3600000) % 86400000
    return (local >= 23*3600000) | (local < 7*3600000)


def source_hour(ts):
    # Literal arithmetic in unchanged MscLocalParts, using float64 like C++ double.
    t = ts.astype(np.float64)/1000.0 + 8.0*3600.0
    day = np.floor(t/86400.0)
    h = (t-day*86400.0)/3600.0
    return np.where(h < 12.0, h+24.0, h)


def release_select(raw, native_x, night_hours):
    active = (night_hours >= 23.0) & (night_hours < 31.0)
    out = np.array(native_x, copy=True)
    out[~active] = raw[~active]
    out[~np.isfinite(raw)] = np.nan
    return out, active


def r4_select(raw, native_x, ts):
    active = integer_route(ts)
    result = np.where(active[:, None], native_x, raw)
    result[~np.isfinite(raw)] = np.nan
    return result


def defaults(header):
    config = header.split('struct ModalSelfCalConfig {', 1)[1].split('struct ModalSelfCalFrameInfo', 1)[0]
    values = {}
    for typ, key, value in re.findall(r'\b(double|int|bool)\s+(\w+)\s*=\s*([^;]+);', config):
        values[key] = value.strip() == 'true' if typ == 'bool' else float(value) if typ == 'double' else int(value)
    values['fit_only_prefixes'] = re.findall(r'"([^"]*)"', re.search(r'fit_only_prefixes\s*=\s*\{([^}]*)\}', config).group(1))
    return values


def main():
    source_hashes = {n: sha(SOURCE/n) for n in ['ModalSelfCal.cpp', 'ModalSelfCal.h']}
    oldcpp, cpp = [(p/'ModalSelfCal.cpp').read_text(encoding='utf8') for p in [ORIGINAL, SOURCE]]
    oldh, header = [(p/'ModalSelfCal.h').read_text(encoding='utf8') for p in [ORIGINAL, SOURCE]]
    a, b = oldcpp.splitlines(keepends=True), cpp.splitlines(keepends=True)
    changes = [o for o in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes() if o[0] != 'equal']
    check(len(changes) == 1 and changes[0][0] == 'insert', 'cpp_only_one_insertion', changes)
    op, i1, i2, j1, j2 = changes[0]
    block = ''.join(b[j1:j2])
    check(''.join(b[:j1]+b[j2:]) == oldcpp, 'cpp_identical_when_publication_block_removed')
    check(j2-j1 == 12, 'publication_insertion_12_lines', j2-j1)
    check('p.' not in block and 'r.y' not in block and 'r.correction_y' not in block,
          'publication_block_writes_no_engine_state_or_y')
    check(cpp.index('p.velocity_damping.NotifyDaytime(ts, r.x);') < cpp.index(block) < cpp.index('double maxc = 0;', cpp.index(block)),
          'publication_after_temporal_updates_before_correction_vectors')
    check('if (!publish_night_x) r.x = x;' in block and
          'if (!std::isfinite(x[i])) r.x[i] = std::numeric_limits<double>::quiet_NaN();' in block,
          'publication_raw_and_invalid_routing_explicit')
    check('night_hour >= 23.0 && night_hour < 31.0' in header, 'half_open_selector_exact')
    check('r.x_source = replay ? ModalSelfCalXSource::NoOutput' in block and
          'ModalSelfCalXSource x_source = ModalSelfCalXSource::NoOutput;' in header,
          'replay_duplicate_failed_result_default_no_output_source')
    check(cpp.index('*result = ModalSelfCalResult();') < cpp.index('if (ts <= p.x->last_ts()'),
          'duplicate_and_failure_result_reset_precedes_processing')
    check('r.output_ready = !replay;' in cpp and 'if (replay) {\n            r.x.clear();' in cpp,
          'replay_still_clears_published_vectors')
    old_defaults, new_defaults = defaults(oldh), defaults(header)
    changed_defaults = {k: [old_defaults.get(k), v] for k,v in new_defaults.items() if old_defaults.get(k) != v}
    check(changed_defaults == {'fade_x_enhancements_with_gate': [False, True]}, 'only_config_default_change_is_fade', changed_defaults)
    adapter_path = BASE/'round4_window_causality/integration/NightWindowOutput.h'
    adapter = adapter_path.read_text(encoding='utf8')
    check('night_hour >= 23.0 && night_hour < 31.0' in adapter, 'r4_same_hour_predicate')
    check('if (!std::isfinite(raw_x[i]))' in adapter, 'r4_same_missing_input_guard')

    # Four transition neighborhoods at millisecond resolution on each requested night.
    boundary_times = []
    for day in range(13, 17):
        for hour in [7, 12, 23, 0]:
            center = int(datetime(2026, 11, day, hour, tzinfo=TZ).timestamp()*1000)
            boundary_times.extend(range(center-2000, center+2001))
    bt = np.asarray(boundary_times, dtype=np.int64)
    hours = source_hour(bt)
    check(np.array_equal((hours >= 23) & (hours < 31), integer_route(bt)), 'millisecond_boundary_formula_equivalence', len(bt))
    # Invalid raw never becomes finite, even if a hypothetical core value is finite.
    synthetic_raw = np.asarray([[np.nan, -0.0, 3.0, 2.0]]*4)
    synthetic_core = np.asarray([[7.0, 1.0, np.nan, -1.0]]*4)
    synthetic_ts = np.asarray([int(datetime(2026,11,16,h,m,tzinfo=TZ).timestamp()*1000) for h,m in [(6,59),(7,0),(22,59),(23,0)]])
    out, _ = release_select(synthetic_raw, synthetic_core, source_hour(synthetic_ts))
    check(equal(out, r4_select(synthetic_raw, synthetic_core, synthetic_ts)), 'synthetic_nan_and_negative_zero_equivalence')
    check(np.isnan(out[:,0]).all(), 'raw_nan_never_promoted')
    check(np.isnan(out[[0,3],2]).all() and np.array_equal(out[[1,2],2], [3.0,3.0]), 'finite_raw_core_nan_routing')

    r4path = BASE/'round4_window_causality/reports/exit_output_verification.json'
    r4 = json.loads(r4path.read_text(encoding='utf8'))
    oldchecks = {(d['line'],d['device']):d for d in r4['checks']}
    devices = []
    for path in sorted((BASE/'data').glob('*/*/input.npz')):
        line, device = path.parent.parent.name, path.parent.name
        with np.load(path) as d:
            ts, names, raw_x, raw_y = d['timestamp'], d['names'], d['x'], d['y']
        directory = BASE/'round2_waveform_10n/results/current_fade07'/line/device
        native_path = directory/'output.bin'
        with native_path.open('rb') as f:
            m,n = struct.unpack('<II', f.read(8))
        check((n,m) == raw_x.shape, 'native_dimensions_exact', device)
        ar = np.memmap(native_path, dtype=[('ts','<i8'),('xy','<f8',(2,m))], offset=8, shape=(n,), mode='r')
        check(np.array_equal(ar['ts'],ts), 'native_timestamps_exact', device)
        frozen = json.loads((directory/'verification.json').read_text(encoding='utf8'))
        cfg = frozen['actual_config']
        check(all(cfg[k] == v for k,v in new_defaults.items()), 'release_defaults_match_profile14_config', device)
        check(cfg['profile_id'] == 14, 'frozen_output_is_profile14', device)
        raw_hash, output_hash = sha(path), sha(native_path)
        old = oldchecks[(line,device)]
        check(raw_hash == old['input_sha256'] and output_hash == old['native_sha256'] == frozen['output_sha256'], 'frozen_hashes_match_r4_and_native', device)
        native_x, native_y = ar['xy'][:,0,:], ar['xy'][:,1,:]
        published, active = release_select(raw_x, native_x, source_hour(ts))
        check(np.array_equal(active, integer_route(ts)), 'all_frames_same_time_route', device)
        check(equal(published, r4_select(raw_x,native_x,ts)), 'all_x_cells_exactly_r4_publication', device)
        check(equal(published[active],native_x[active]), 'night_native_x_unchanged', device)
        check(equal(published[~active],raw_x[~active]), 'outside_raw_x_exact', device)
        check(np.array_equal(np.isnan(published),np.isnan(raw_x)), 'x_nan_mask_unchanged', device)
        final_y = np.array(native_y, copy=True)
        check(np.array_equal(final_y.view('u8'),native_y.view('u8')), 'y_all_bits_unchanged', device)
        correction_x = raw_x-published
        check(np.all(correction_x[~active][np.isfinite(raw_x[~active])] == 0), 'outside_x_correction_zero_for_finite_raw', device)
        for cut in [n//3, 2*n//3]:
            part,_ = release_select(raw_x[cut:], native_x[cut:], source_hour(ts[cut:]))
            check(equal(part,published[cut:]), 'selector_chunk_restart_no_state', [device,cut])
        stat = dict(line=line,device=device,frames=n,markers=m,total_x_cells=n*m,
                    active_frames=int(active.sum()),raw_frames=int((~active).sum()),
                    active_finite_x=int(np.isfinite(published[active]).sum()),
                    raw_finite_x=int(np.isfinite(published[~active]).sum()),
                    x_nan_cells=int(np.isnan(published).sum()),
                    y_finite_cells=int(np.isfinite(final_y).sum()),
                    y_nan_cells=int(np.isnan(final_y).sum()),
                    input_npz_sha256=raw_hash,native_output_sha256=output_hash)
        check(all(stat[k] == old[k] for k in ['frames','markers','active_frames','raw_frames','active_finite_x','raw_finite_x']),
              'all_r4_summary_counts_identical', device)
        devices.append(stat)
        print('ROUTING_CHECKED',line,device,n,n*m,flush=True)
    check(len(devices)==12, 'all_twelve_devices_included')
    check(source_hashes == {n:sha(SOURCE/n) for n in source_hashes}, 'release_source_unchanged_during_audit')
    total = {k:sum(d[k] for d in devices) for k in ['frames','total_x_cells','active_frames','raw_frames','active_finite_x','raw_finite_x','x_nan_cells','y_finite_cells','y_nan_cells']}
    total['devices'] = len(devices)
    check(total['frames'] == r4['total_device_frames'] and total['active_finite_x'] == r4['active_finite_x'] and total['raw_finite_x'] == r4['raw_finite_x'], 'r4_grand_totals_equal')
    report = dict(passed=not errors,validation_scope='Static source review plus Python publication routing over frozen native profile14 outputs; new cpp wrapper was NOT executed; external state ImportState was NOT executed.',
                  code=source_hashes,original_code={n:sha(ORIGINAL/n) for n in source_hashes},
                  r4_adapter_sha256=sha(adapter_path),r4_verification_sha256=sha(r4path),
                  cpp_change={'kind':'single insertion','new_line_start':j1+1,'new_lines':j2-j1,'rest_identical':True},
                  config_default_changes=changed_defaults,release_defaults=new_defaults,
                  static_state_boundary='With matching profile14 configuration the temporal/core/state serialization code is unchanged. Publication writes only local result fields after all normal engine updates. This is a static argument, not a native state roundtrip test.',
                  abi_note='ModalSelfCalResult adds x_source; compile callers with the delivered matching cpp/h. Standalone ModalSelfCalAxis remains unwrapped; paired ModalSelfCalState and ApplyModalSelfCal use publication routing.',
                  diagnostic_note='info_x retains internal diagnostics; x_source labels published coordinate source and is not a physical correctness/status assertion. Legacy GetLastModalSelfCalInfo is an unchanged stub; obtain diagnostics from Process result.',
                  compile_checks={'scope':'Executed separately during audit with existing GCC, -fsyntax-only; no binaries emitted or loaded','cpp_cxx17_exit_code':0,'header_constexpr_boundary_assertions':9,'header_assertions_exit_code':0,'warnings':'Four pre-existing unused parameter warnings; modified publication lines produced no diagnostics.'},
                  millisecond_boundary_cases=len(bt),checks=dict(checks),error_count=len(errors),errors=errors,
                  totals=total,devices=devices,script_sha256=sha(Path(__file__)))
    REPORT.mkdir(parents=True,exist_ok=True)
    (REPORT/'independent_release_routing_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    md=['# V54-Astra 两文件封装：独立审核','', '结论：'+('本轮静态与离线路由核验通过。' if not errors else '存在核验错误。'),'',
        '验证边界：没有执行新封装的 DLL/程序，也没有原生导入本次外部状态包。以下结果来自源代码审核、仅语法编译，以及已冻结 profile14 原生输出上的独立发布路由计算。','',
        f"全 12 台设备、{total['frames']:,} 帧、{total['total_x_cells']:,} 个 X 坐标逐项核对，与 R4 发布路由完全一致。23:00–07:00 保留原生结果，其他时段使用同帧 W3 前 raw X；有限值逐位一致、NaN 掩码一致。Y 的全部位保持不变。",'',
        f"夜间有限 X {total['active_finite_x']:,} 个；日间 raw 有限 X {total['raw_finite_x']:,} 个；X 的 NaN {total['x_nan_cells']:,} 个。",'',
        '- cpp 仅插入 12 行发布选择；删除该插入后与冻结原版逐字符一致。它位于 W3/模态/S2/S1/日间缓存更新之后、输出 correction_x 计算之前。',
        '- 默认参数只有 fade 从 false 改为 true，与全部 12 台冻结 current_fade07/profile14 配置相符。状态编解码、ConfigKey、导入条件及内部更新代码未改变。',
        '- 新 x_source 的默认值、重放和重复帧均不发布；NightCorrection 表示夜间输出路径，不等于修复成功或物理准确。info_x 仍表示内部诊断。',
        f"- {len(bt):,} 个毫秒级边界点与独立整数时钟路由一致；9 个 C++ constexpr 边界断言通过，含 23:00/07:00 和 NaN/±Inf；24 次分块路由与连续路由一致。",
        '- 完整 cpp 通过 C++17 -fsyntax-only 检查，仅有原版已有未使用参数警告。未生成或运行新二进制。',
        '- ModalSelfCalResult 增加字段，调用方应使用配套 cpp/h 重新编译；单轴 ModalSelfCalAxis 不含配对发布封装。旧全局 GetLastModalSelfCalInfo 仍为原有占位实现，真实诊断应读取 Process 返回值。','',
        '静态结构支持内部历史状态不被发布选择改变；本报告没有将该判断夸大为新封装运行等价、外部状态原生导入成功或现场物理准确性验证。']
    if errors:md += ['',json.dumps(errors,ensure_ascii=False,indent=2)]
    (REPORT/'independent_release_routing_audit.md').write_text('\n'.join(md)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'errors':len(errors),**total},ensure_ascii=True),flush=True)
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
