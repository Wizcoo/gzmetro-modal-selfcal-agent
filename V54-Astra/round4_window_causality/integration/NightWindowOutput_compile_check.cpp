#include "NightWindowOutput.h"

using astra_publication::IsNightCorrectionHour;
static_assert(!IsNightCorrectionHour(22.0), "22-23 still publishes raw");
static_assert(!IsNightCorrectionHour(22.999999), "before 23 stays raw");
static_assert(IsNightCorrectionHour(23.0), "23 is included");
static_assert(IsNightCorrectionHour(24.0), "midnight uses native hour 24");
static_assert(IsNightCorrectionHour(30.999999), "before 07 uses corrected X");
static_assert(!IsNightCorrectionHour(31.0), "exactly 07 publishes raw");
static_assert(!IsNightCorrectionHour(31.333333), "core exit ramp is not published");

// Syntax-only interface check; no executable is linked or run.
void CompileIntegrationContract(ModalSelfCalState& engine,
                                int64_t ts,
                                const std::vector<double>& x,
                                const std::vector<double>& y) {
    astra_publication::NightWindowOutput out;
    std::string error;
    const bool ok = astra_publication::ProcessForPublication(engine, ts, x, y, &out, &error);
    if (ok && out.output_ready) {
        const auto& published_x = out.x;
        const auto& published_y = out.y();
        const auto& correction_x = out.correction_x;
        const auto& correction_y = out.correction_y();
        (void)published_x; (void)published_y; (void)correction_x; (void)correction_y;
    }
}
