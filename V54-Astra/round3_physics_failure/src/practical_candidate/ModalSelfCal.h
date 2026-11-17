#pragma once
// V54-Astra: X-only cross-night regression energy reliability control.
// Input/output x/y are PIXELS (user confirmed 2026-11-16).
// Preserve V54 W3/modal/S2/S1 processing for reliable rows. Only ordinary
// nonlearn regression rows receive a history-derived gain in [0,1].
// Historical full-basis energy is a reliability proxy, not physical truth
// or a guarantee for final nightly range. Intentional fit_only rows are unchanged.
// New snapshots are required. Legacy V54/earlier Astra states must be rebuilt
// by replaying raw history; their cached A/cbar values are not accepted.

#include <cstdint>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace gzmetro_msc {

struct ModalSelfCalConfig {
    // ---- 时钟（北京时间；夜内小时：次日 0~12 点记作 24~36，如 26 = 次日 02:00）----
    double tz_offset_h = 8.0;       // 时间戳 Unix 毫秒 → 本地时间的偏移（小时）
    double ref_start_h = 22.0;      // 基准窗起（含）
    double ref_end_h = 23.0;        // 基准窗止（不含）；同时是修正起点
    double learn_end_h = 26.0;      // 学习窗止（不含，次日 02:00）；学习窗 = [ref_start_h, learn_end_h)
    double apply_end_h = 31.0;      // 修正窗止（次日 07:00），之后 ramp_min 分钟内线性退出
    // Window diagnostic only: 0 inherits apply_end_h; positive values override X
    // through learn_end_h <= x_apply_end_h <= 36. Y keeps apply_end_h.
    // An explicit X end or enabled exit fade must finish its ramp by hour 36.
    double x_apply_end_h = 0.0;
    // Diagnostic: keep enhancement state through the exit ramp and blend its
    // contribution by gate. Entry ramp and default false behavior are unchanged.
    bool fade_x_enhancements_with_gate = false;
    double ramp_min = 20.0;         // 进 / 出斜坡时长（分钟）
    double cadence_s = 60.0;        // 现场帧间隔（秒），只用于估算期望帧数

    // ---- 模态 ----
    int K = 3;                      // 模态阶数
    double guard = 0.5;             // 独占保护阈值：某点在任一模态中能量占比 > guard 即剔出学习集
    double spread_k = 3.0;          // 离散度筛选：标准差 > spread_k × 中位 的点不进学习集（≤0 关闭）
    int history_nights = 3;         // 合并最近几夜的统计求模态
    double min_valid_ratio = 0.8;   // 点在学习窗有效率 ≥ 该值才建模（否则该点原样透传）
    double min_learn_ratio = 0.6;   // 本夜学习窗帧数 ≥ 该比例 × 期望帧数 才收入历史
    int min_ref_frames = 10;        // 点在基准窗内有效帧 ≥ 该值才有基线（否则本夜该点透传）
    int min_valid = 5;              // 单帧参与最小二乘的最少学习点数（实际取 max(min_valid, K+2)）

    // ---- 实时单帧抗差与离群剔除（防止单点突变/跳变污染全局模态反解）----
    double max_frame_residual = 2.5; // 单帧拟合残差门限（pixel）：|z_i - A_i v| > 该值时自动剔出求解并重算，<=0 关闭
    double max_frame_dev = 0.0;      // 单帧绝对偏差门限（pixel）：|z_i| > 该值时初检直接剔除，<=0 关闭

    // 外接 / 基准点前缀：不参与学模态与求 v，只按回归载荷扣公共项
    std::vector<std::string> fit_only_prefixes = {"YJ", "ZJ"};

    // Standalone axis option; paired State always enables this for X and disables it for Y.
    bool limit_regression_crossnight_energy = false;
    bool enabled = true;            // false：逐帧原样透传，state = DISABLED

    // =======================================================================
    // 方案 D (V54) 专用参数：X 向夜间温和物理增强开关
    // =======================================================================
    bool enable_x_w3_filter = true;              // X 向输入端 W=3 因果中值滤波
    bool enable_x_mount_drift_damping = true;    // X 向夜间 55% 支架温漂自校
    double mount_drift_shrinkage = 0.55;         // 温漂收缩系数 (0.55 即扣除 55% 共模慢漂)
    bool enable_x_velocity_damping = true;       // X 向夜间 1.5min 因果微阻尼
    double x_enhancement_gap_min = 3.0;          // reset X temporal caches after an observed gap
    double velocity_damping_tau_min = 1.5;       // 微阻尼时间常数 (分钟，对应 1 分钟采样 alpha 约 0.486)
};

struct ModalSelfCalFrameInfo {
    int64_t ts_ms = 0;
    std::string state;              // PASSTHROUGH / BASELINE / RAMP / CORRECTING / WAIT_MODES / DEGRADED_FRAME
                                    // / SKIP_BAD_TS / DISABLED / BAD_INPUT
    int64_t night_id = 0;           // 夜号：本地日期的 Unix 天数（20:00–次日 12:00 归同一夜）
    double night_hour = 0.0;        // 夜内小时（见 Config 说明）
    double gate = 0.0;              // 修正门值 0~1
    bool baseline_frozen = false;   // 本夜基线是否已冻结（23:00 后）
    bool modes_ready = false;       // 本夜是否有可用模态
    bool modes_from_tonight = false;// 模态来自本夜（冷启动，02:00 起修正）
    int n_history = 0;              // 历史统计夜数（0~history_nights）
    int n_learn_points = 0;         // 学习点数（剔除 YJ / 离散 / 独占后）
    int n_frame_learn_valid = 0;    // 本帧参与最小二乘的有效学习点数
    int n_corrected = 0;            // 本帧被修正的点数
    double v[3] = {0.0, 0.0, 0.0};  // 本帧模态时间系数（前 3 阶，诊断用）
};

// 单轴引擎（内部基础轴）
class ModalSelfCalAxis {
public:
    explicit ModalSelfCalAxis(const ModalSelfCalConfig& config = ModalSelfCalConfig());
    ~ModalSelfCalAxis();
    ModalSelfCalAxis(const ModalSelfCalAxis&) = delete;
    ModalSelfCalAxis& operator=(const ModalSelfCalAxis&) = delete;

    void Bind(const std::vector<std::string>& names);
    std::vector<double> Ingest(int64_t ts_ms, const std::vector<double>& values);

    const ModalSelfCalFrameInfo& last_info() const;
    const std::vector<std::string>& names() const;
    int64_t last_ts() const;

    void SetEnabled(bool enabled);
    void Reset();

    bool SaveState(std::string* blob) const;
    bool LoadState(const std::string& blob, std::string* error = nullptr);

    struct Impl;
private:
    ModalSelfCalConfig config_;
    std::vector<std::string> names_;
    ModalSelfCalFrameInfo last_info_;
    Impl* impl_ = nullptr;
};

// 状态诊断输出结构体
struct ModalSelfCalResumeInfo {
    int64_t last_timestamp_ms = 0;
    int history_x = 0, history_y = 0;
    bool baseline_x = false, baseline_y = false;
    bool modes_x = false, modes_y = false;
};

struct ModalSelfCalResult {
    bool output_ready = false;
    bool duplicate = false;
    bool replayed = false;
    std::vector<double> x;
    std::vector<double> y;
    std::vector<double> correction_x;
    std::vector<double> correction_y;
    ModalSelfCalFrameInfo info_x;
    ModalSelfCalFrameInfo info_y;
};

// ===========================================================================
// 面向对象式状态类 (与 V50/V51/V52/V53 接口 100% 兼容)
// ===========================================================================
class ModalSelfCalState {
public:
    explicit ModalSelfCalState(const ModalSelfCalConfig& config = ModalSelfCalConfig());
    ~ModalSelfCalState();
    ModalSelfCalState(const ModalSelfCalState&) = delete;
    ModalSelfCalState& operator=(const ModalSelfCalState&) = delete;

    // 初始化：names 为点名单。allow_new_stream=true 即可完全自主在线冷启动，无需任何外部状态包！
    bool Init(const std::string& device_id, const std::vector<std::string>& names,
              std::string* error = nullptr, bool allow_new_stream = true);

    // 导入状态快照（可选，若有则加速热启动；若无则自动在线自学）
    bool ImportState(const std::string& bytes, ModalSelfCalResumeInfo* resume,
                     std::string* error = nullptr);

    // 单帧处理核心接口：内部执行 W=3预处理 -> V51模态求解 -> 方案D温和物理后处理
    bool Process(int64_t timestamp_ms, const std::vector<double>& raw_x,
                 const std::vector<double>& raw_y, ModalSelfCalResult* result,
                 std::string* error = nullptr, bool history_replay = false);

    // 导出状态快照
    bool ExportState(std::string* bytes, int64_t* last_timestamp_ms,
                     std::string* error = nullptr) const;

    bool GetResumeTs(int64_t* last_timestamp_ms, std::string* error = nullptr) const;
    void Destroy();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// ===========================================================================
// 函数式全局接口 (与 modelselfcal-1016 全局单例接口 100% 兼容)
// ===========================================================================
bool InitModalSelfCal(const std::string& device_id, const std::vector<std::string>& names,
                      std::string* err = nullptr);

bool ApplyModalSelfCal(const std::string& device_id, int64_t ts_ms,
                       const std::vector<double>& x, const std::vector<double>& y,
                       std::vector<double>* x_out, std::vector<double>* y_out,
                       const std::vector<std::string>* names = nullptr);

bool GetLastModalSelfCalInfo(const std::string& device_id, int axis, ModalSelfCalFrameInfo* out);
bool ResetModalSelfCal(const std::string& device_id = "");
bool SaveModalSelfCalState(const std::string& device_id, std::string* blob);
bool LoadModalSelfCalState(const std::string& device_id, const std::string& blob,
                           std::string* err = nullptr);
bool GetModalSelfCalResumeTs(const std::string& device_id, int64_t* ts_ms);

void SetModalSelfCalConfig(const ModalSelfCalConfig& config);
ModalSelfCalConfig GetModalSelfCalConfig();
void SetModalSelfCalEnabled(bool enabled);
void SetModalSelfCalLogEnabled(bool enabled);
bool GetModalSelfCalLogEnabled();

} // namespace gzmetro_msc

// 全局命名空间导出
using gzmetro_msc::ModalSelfCalConfig;
using gzmetro_msc::ModalSelfCalFrameInfo;
using gzmetro_msc::ModalSelfCalResumeInfo;
using gzmetro_msc::ModalSelfCalResult;
using gzmetro_msc::ModalSelfCalState;
using gzmetro_msc::ModalSelfCalAxis;
using gzmetro_msc::InitModalSelfCal;
using gzmetro_msc::ApplyModalSelfCal;
using gzmetro_msc::GetLastModalSelfCalInfo;
using gzmetro_msc::ResetModalSelfCal;
using gzmetro_msc::SaveModalSelfCalState;
using gzmetro_msc::LoadModalSelfCalState;
using gzmetro_msc::GetModalSelfCalResumeTs;
using gzmetro_msc::SetModalSelfCalConfig;
using gzmetro_msc::GetModalSelfCalConfig;
using gzmetro_msc::SetModalSelfCalEnabled;
using gzmetro_msc::SetModalSelfCalLogEnabled;
using gzmetro_msc::GetModalSelfCalLogEnabled;
