#pragma once

// Publication adapter only. The ModalSelfCal engine still ingests every frame.
// Use the same ModalSelfCal.h/.cpp as the reviewed Astra implementation.
#include "ModalSelfCal.h"

#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>

namespace astra_publication {

enum class XSource {
    NoOutput,
    RawObservation,
    NightCorrection
};

// Native night_hour already applies the engine's configured timezone:
// 00:00 is 24, 06:59 is about 30.9833, and 07:00 is exactly 31.
// This fixed publication interval adds no operator-maintained parameter.
constexpr bool IsNightCorrectionHour(double night_hour) noexcept {
    return night_hour >= 23.0 && night_hour < 31.0;
}

struct NightWindowOutput {
    // Unmodified engine result, including core.x, core.y and internal diagnostics.
    // core.info_x describes internal computation, NOT the published X source.
    ModalSelfCalResult core;

    // These fields alone describe published X. A non-ready frame is not publishable.
    bool output_ready = false;
    XSource x_source = XSource::NoOutput;
    std::vector<double> x;
    std::vector<double> correction_x;

    // Y remains exactly the existing engine output; no Y window is introduced.
    const std::vector<double>& y() const noexcept { return core.y; }
    const std::vector<double>& correction_y() const noexcept { return core.correction_y; }
};

// Use this helper only AFTER the engine has processed this same frame into out->core.
// Before invoking the engine, the caller must represent ROI-invalid/missing X as NaN,
// as required by ModalSelfCal. This adapter does not have access to database ROI flags.
inline bool SelectPublishedX(const std::vector<double>& raw_x,
                             NightWindowOutput* out,
                             std::string* error = nullptr) {
    if (error) error->clear();
    if (!out) {
        if (error) *error = "null publication output";
        return false;
    }
    out->output_ready = false;
    out->x_source = XSource::NoOutput;
    out->x.clear();
    out->correction_x.clear();

    // Preserve the engine's no-publication semantics for replay and duplicate frames.
    if (!out->core.output_ready || out->core.duplicate || out->core.replayed) return true;
    if (out->core.x.size() != raw_x.size()) {
        if (error) *error = "raw/core X length mismatch";
        return false;
    }

    const bool use_night = IsNightCorrectionHour(out->core.info_x.night_hour);
    out->x_source = use_night ? XSource::NightCorrection : XSource::RawObservation;
    out->x = use_night ? out->core.x : raw_x;
    out->correction_x.resize(raw_x.size());
    const double missing = std::numeric_limits<double>::quiet_NaN();
    for (std::size_t i = 0; i < raw_x.size(); ++i) {
        // An invalid input is never promoted to a valid coordinate by routing.
        if (!std::isfinite(raw_x[i])) {
            out->x[i] = missing;
            out->correction_x[i] = missing;
        } else {
            out->correction_x[i] = raw_x[i] - out->x[i];
        }
    }
    out->output_ready = true;
    return true;
}

// Preferred entry point: always advance the existing engine before selecting X.
// Returns processing success, NOT publication readiness. Check out->output_ready.
// Input vectors must be separate from out's storage (same requirement as Process).
inline bool ProcessForPublication(ModalSelfCalState& engine,
                                  int64_t timestamp_ms,
                                  const std::vector<double>& raw_x,
                                  const std::vector<double>& raw_y,
                                  NightWindowOutput* out,
                                  std::string* error = nullptr,
                                  bool history_replay = false) {
    if (!out) {
        if (error) *error = "null publication output";
        return false;
    }
    *out = NightWindowOutput{};
    if (!engine.Process(timestamp_ms, raw_x, raw_y, &out->core, error, history_replay))
        return false;
    return SelectPublishedX(raw_x, out, error);
}

} // namespace astra_publication
