#include "ModalSelfCal.h"
#include <limits>
#include <type_traits>

static_assert(!IsAstraNightCorrectionHour(22.999999), "before 23 is raw");
static_assert(IsAstraNightCorrectionHour(23.0), "23 is included");
static_assert(IsAstraNightCorrectionHour(24.0), "midnight is included");
static_assert(IsAstraNightCorrectionHour(30.999999), "before 07 is included");
static_assert(!IsAstraNightCorrectionHour(31.0), "07 is excluded");
static_assert(!IsAstraNightCorrectionHour(32.0), "after 07 is raw");
static_assert(!IsAstraNightCorrectionHour(std::numeric_limits<double>::quiet_NaN()), "NaN is not night");
static_assert(!IsAstraNightCorrectionHour(std::numeric_limits<double>::infinity()), "infinity is not night");
static_assert(std::is_same<decltype(ModalSelfCalResult().x_source),ModalSelfCalXSource>::value,"output source API");

void existing_api_compile_check() {
    ModalSelfCalConfig cfg;
    ModalSelfCalState state(cfg);
    std::string error,bytes;
    std::vector<std::string> names{"TEST1","TEST2","TEST3","TEST4","TEST5"};
    state.Init("compile-only",names,&error,false);
    ModalSelfCalResumeInfo resume;
    state.ImportState(bytes,&resume,&error);
    ModalSelfCalResult result;
    std::vector<double> raw(5,0.0);
    state.Process(1,raw,raw,&result,&error);
    int64_t cutoff=0;
    state.ExportState(&bytes,&cutoff,&error);
}
