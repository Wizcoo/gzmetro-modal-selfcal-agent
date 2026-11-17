"""Assemble the final history-energy variant from preserved, verified sources."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'experiments/guard_v2'

def replace(s,a,b):assert s.count(a)==1,(a,s.count(a));return s.replace(a,b)
def function(s,signature):
    start=s.index(signature);at=s.index('{',start);depth=0
    for end in range(at,len(s)):
        if s[end]=='{':depth+=1
        elif s[end]=='}':
            depth-=1
            if depth==0:return s[start:end+1]
    raise ValueError(signature)

if not (ARCHIVE/'src/ModalSelfCal.cpp').exists():
    shutil.copytree(ROOT/'src',ARCHIVE/'src',dirs_exist_ok=True)
    shutil.copytree(ROOT/'tests',ARCHIVE/'tests',dirs_exist_ok=True)
    (ARCHIVE/'tools').mkdir(parents=True,exist_ok=True)
    for name in ['run_tests.py','run_target_mapping.py','run_real_restart.py']:
        shutil.copyfile(ROOT/'tools'/name,ARCHIVE/'tools'/name)
v2=(ARCHIVE/'src/ModalSelfCal.cpp').read_text(encoding='utf-8')
s=(ROOT/'experiments/crossnight_energy/src/ModalSelfCal.cpp').read_text(encoding='utf-8')
h=(ROOT/'experiments/crossnight_energy/src/ModalSelfCal.h').read_text(encoding='utf-8')
start=h.index('#include <cstdint>')
h='''#pragma once
// V54-Astra: X-only cross-night regression energy reliability control.
// Input/output x/y are PIXELS (user confirmed 2026-11-16).
// Preserve V54 W3/modal/S2/S1 processing for reliable rows. Only ordinary
// nonlearn regression rows receive a history-derived gain in [0,1].
// Historical full-basis energy is a reliability proxy, not physical truth
// or a guarantee for final nightly range. Intentional fit_only rows are unchanged.
// New snapshots are required. Legacy V54/earlier Astra states must be rebuilt
// by replaying raw history; their cached A/cbar values are not accepted.

'''+h[start:]
h=replace(h,'double max_frame_dev = 8.0;','double max_frame_dev = 0.0;')
h=h.replace('（mm）','（pixel）').replace('（mm）：','（pixel）：')
h=replace(h,'    bool limit_regression_crossnight_energy = false;','    // Standalone axis option; paired State always enables this for X and disables it for Y.\n    bool limit_regression_crossnight_energy = false;')
h=replace(h,'    double velocity_damping_tau_min = 1.5;','    double x_enhancement_gap_min = 3.0;          // reset X temporal caches after an observed gap\n    double velocity_damping_tau_min = 1.5;')
# The complete mount reference collection buffer is part of the state.
old=s[s.index('class MountThermalDamping'):s.index('class MildVelocityDamping')]
new=v2[v2.index('class MountThermalDamping'):v2.index('class MildVelocityDamping')]
s=replace(s,old,new)
config='''std::string ConfigKey(const ModalSelfCalConfig& c) {
    std::ostringstream o;o.imbue(std::locale::classic());o<<std::setprecision(17);
    o<<c.tz_offset_h<<','<<c.ref_start_h<<','<<c.ref_end_h<<','<<c.learn_end_h<<','
     <<c.apply_end_h<<','<<c.ramp_min<<','<<c.cadence_s<<','<<c.K<<','<<c.guard<<','
     <<c.spread_k<<','<<c.history_nights<<','<<c.min_valid_ratio<<','<<c.min_learn_ratio<<','
     <<c.min_ref_frames<<','<<c.min_valid<<','<<c.max_frame_residual<<','<<c.max_frame_dev<<','<<c.enabled;
    o<<",Astra-history-energy-v1,"<<c.limit_regression_crossnight_energy<<','
     <<c.enable_x_w3_filter<<','<<c.enable_x_mount_drift_damping<<','<<c.mount_drift_shrinkage<<','
     <<c.enable_x_velocity_damping<<','<<c.velocity_damping_tau_min<<','<<c.x_enhancement_gap_min;
    for(const auto& p:c.fit_only_prefixes){o<<':'<<p.size()<<':'<<p;}return o.str();
}'''
s=replace(s,function(s,'std::string ConfigKey('),config)
s=replace(s,'const std::string MAGIC="MSC_STATE_V50R\\n";','const std::string MAGIC="MSC_STATE_V54_ASTRA_HISTORY1\\n";')
s=replace(s,'"invalid local V50 state format"','"invalid Astra history-energy state; replay raw history to rebuild legacy A/cbar"')
# Transactional enhancement restoration and exact roster order, with the X/Y
# axis configs explicitly rebuilt on ImportState as on Init.
imp=function(v2,'bool ModalSelfCalState::ImportState(')
imp=replace(imp,'        auto nx = std::make_unique<ModalSelfCalAxis>(p.config);\n        auto ny = std::make_unique<ModalSelfCalAxis>(p.config);','        auto x_config=p.config,y_config=p.config;\n        x_config.limit_regression_crossnight_energy=true;\n        y_config.limit_regression_crossnight_energy=false;\n        auto nx = std::make_unique<ModalSelfCalAxis>(x_config);\n        auto ny = std::make_unique<ModalSelfCalAxis>(y_config);')
imp=replace(imp,'bool guard_loaded=false, filter_loaded=false, mount_loaded=false, velocity_loaded=false;','bool filter_loaded=false, mount_loaded=false, velocity_loaded=false;')
imp=replace(imp,'        auto restored_guard=p.x_guard;\n','')
imp=replace(imp,'                } else if (d_line.rfind("astra=", 0) == 0) {\n                    Need(!guard_loaded,"duplicate Astra state");\n                    restored_guard.Deserialize(d_line.substr(6)); guard_loaded=true;','')
imp=replace(imp,'Need(guard_loaded && filter_loaded && mount_loaded && velocity_loaded,','Need(filter_loaded && mount_loaded && velocity_loaded,')
imp=replace(imp,'        p.x_guard=std::move(restored_guard);\n','')
assert 'x_guard' not in imp
s=replace(s,function(s,'bool ModalSelfCalState::ImportState('),imp)
# Validate and fingerprint every newly used temporal parameter.
s=replace(s,'c.min_learn_ratio, c.max_frame_residual, c.max_frame_dev}) {','c.min_learn_ratio, c.max_frame_residual, c.max_frame_dev,\n                         c.mount_drift_shrinkage,c.velocity_damping_tau_min,c.x_enhancement_gap_min}) {')
s=replace(s,'             c.min_learn_ratio <= 1, "invalid/enabled=false math config");','             c.min_learn_ratio <= 1, "invalid/enabled=false math config");\n        Need(c.mount_drift_shrinkage>=0 && c.mount_drift_shrinkage<=1 &&\n             c.velocity_damping_tau_min>0 && c.x_enhancement_gap_min>0,\n             "invalid Astra X enhancement config");')
s=replace(s,'        std::vector<double> fed_x = x;','        std::vector<double> fed_x = x;\n        if(p.x->last_ts()>0 && ts-p.x->last_ts()>p.config.x_enhancement_gap_min*60000.0) {\n            p.x_filter_bank.Reset();p.mount_damping.Reset();p.velocity_damping.Reset();\n        }')
assert 'XCorrectionGuard' not in s and 'x_guard' not in h
(ROOT/'src/ModalSelfCal.cpp').write_text(s,encoding='utf-8')
(ROOT/'src/ModalSelfCal.h').write_text(h,encoding='utf-8')
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'src/ModalSelfCal.cpp',ROOT/'src/ModalSelfCal.h']}
(ROOT/'build/final_source_assembly.json').write_text(json.dumps(dict(source_sha256=manifest,algorithm='crossnight_energy',runtime_state_fixes_from='experiments/guard_v2/src',physical_fidelity_claimed=False),indent=2),encoding='utf-8')
print(json.dumps(manifest))
