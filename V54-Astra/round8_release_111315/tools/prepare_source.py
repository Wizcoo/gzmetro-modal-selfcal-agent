"""Prepare the two-file Astra delivery, preserving the reviewed native core."""
from pathlib import Path
import hashlib,json,difflib

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent
SOURCE=BASE/'round3_physics_failure/src/practical_candidate'
DEST=ROOT/'source'
DEST.mkdir(parents=True,exist_ok=True)
(ROOT/'reports').mkdir(exist_ok=True)

def replace_once(text,old,new):
    assert text.count(old)==1,old
    return text.replace(old,new,1)

header=(SOURCE/'ModalSelfCal.h').read_text(encoding='utf8')
header=replace_once(header,'#pragma once\n','#pragma once\n// V54-Astra delivery 2026-11-16: current_fade07 + fixed X publication [23:00,07:00).\n// The paired State/Apply APIs publish raw X outside this window; Y is unchanged.\n// This release accepts matching Astra HISTORY1 snapshots (see bundled state manifest).\n')
header=replace_once(header,'// New snapshots are required. Legacy V54/earlier Astra states must be rebuilt','// Legacy V54/incompatible earlier Astra snapshots must be rebuilt')
header=replace_once(header,'// 面向对象式状态类 (与 V50/V51/V52/V53 接口 100% 兼容)','// 面向对象式状态类：保留既有调用方法；本版 cpp/h 必须一起重新编译客户端')
header=replace_once(header,'// 函数式全局接口 (与 modelselfcal-1016 全局单例接口 100% 兼容)','// 既有函数式全局接口；建议使用上方 State::Process 取得 output_ready 和 x_source')
header=replace_once(header,'bool fade_x_enhancements_with_gate = false;','bool fade_x_enhancements_with_gate = true;')
header=replace_once(header,'    // Diagnostic: keep enhancement state through the exit ramp and blend its\n    // contribution by gate. Entry ramp and default false behavior are unchanged.','    // Reviewed current_fade07 default. Keep internal enhancement state through\n    // the exit ramp; paired State publishes raw X from 07:00 onward.')
header=replace_once(header,'struct ModalSelfCalResult {','''// Describes the published X coordinate source, not correction success.
// A source change at 07:00 is an observation-segment boundary.
enum class ModalSelfCalXSource { NoOutput, RawObservation, NightCorrection };

constexpr bool IsAstraNightCorrectionHour(double night_hour) noexcept {
    return night_hour >= 23.0 && night_hour < 31.0;
}

struct ModalSelfCalResult {''')
header=replace_once(header,'    ModalSelfCalFrameInfo info_y;\n};','''    ModalSelfCalFrameInfo info_y;
    // x/correction_x are published values; info_x remains INTERNAL diagnostics.
    // NightCorrection means the night output path, not guaranteed successful correction.
    ModalSelfCalXSource x_source = ModalSelfCalXSource::NoOutput;
};''')
header=replace_once(header,'    // 单帧处理核心接口：内部执行 W=3预处理 -> V51模态求解 -> 方案D温和物理后处理','''    // 每帧均处理以维护历史和缓存。X仅23:00(含)—次日07:00(不含)发布修后值，
    // 其余时间发布同帧raw X；Y保持核心输出。ROI无效点须由调用方填NaN。
    // 内部顺序：W3 -> 模态 -> S2/S1 -> X发布选择。时间戳使用Unix毫秒。''')
header=replace_once(header,'using gzmetro_msc::ModalSelfCalResult;','using gzmetro_msc::ModalSelfCalResult;\nusing gzmetro_msc::ModalSelfCalXSource;\nusing gzmetro_msc::IsAstraNightCorrectionHour;')

cpp=(SOURCE/'ModalSelfCal.cpp').read_text(encoding='utf8')
cpp=replace_once(cpp,'        double maxc = 0;\n','''        // V54-Astra publication contract: ALL internal state updates above remain
        // unchanged. Match the reviewed R4 selector without another header/call.
        // This only selects the returned X, never the next frame's cached values.
        const bool publish_night_x = IsAstraNightCorrectionHour(r.info_x.night_hour);
        if (!publish_night_x) r.x = x;
        for (size_t i = 0; i < x.size(); ++i) {
            if (!std::isfinite(x[i])) r.x[i] = std::numeric_limits<double>::quiet_NaN();
        }
        r.x_source = replay ? ModalSelfCalXSource::NoOutput
            : (publish_night_x ? ModalSelfCalXSource::NightCorrection
                               : ModalSelfCalXSource::RawObservation);

        double maxc = 0;
''')
for name,text in [('ModalSelfCal.h',header),('ModalSelfCal.cpp',cpp)]:
    (DEST/name).write_text(text,encoding='utf8',newline='\n')
    old=(SOURCE/name).read_text(encoding='utf8')
    diff=''.join(difflib.unified_diff(old.splitlines(True),text.splitlines(True),fromfile='reviewed/'+name,tofile='delivery/'+name))
    (ROOT/'reports'/(name+'.diff')).write_text(diff,encoding='utf8',newline='\n')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
result={'profile':'current_fade07','source':str(SOURCE),'publication':'X [23,31) core; outside raw; Y unchanged',
        'mathematical_core_and_serialization_unchanged':True,
        'files':{n:{'original_sha256':sha(SOURCE/n),'release_sha256':sha(DEST/n)} for n in ['ModalSelfCal.cpp','ModalSelfCal.h']}}
(ROOT/'reports/source_preparation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=True))
