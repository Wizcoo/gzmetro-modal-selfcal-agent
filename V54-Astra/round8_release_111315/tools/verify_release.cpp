// Standalone, opt-in runtime verifier. Compile separately from the two-file SDK.
// This source has been compiled only in the delivery environment, NOT executed.
#include "ModalSelfCal.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

using gzmetro_msc::ModalSelfCalXSource;
using gzmetro_msc::IsAstraNightCorrectionHour;

static_assert(!IsAstraNightCorrectionHour(22.999999), "before 23 is raw");
static_assert(IsAstraNightCorrectionHour(23.0), "23 is included");
static_assert(IsAstraNightCorrectionHour(30.999999), "before 07 is night");
static_assert(!IsAstraNightCorrectionHour(31.0), "07 is excluded");

namespace {
void Require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

std::string ReadBytes(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    Require(bool(in), "cannot open state: " + path);
    std::string bytes{std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
    Require(!in.bad() && !bytes.empty(), "empty or unreadable state: " + path);
    return bytes;
}

std::vector<std::string> ReadNames(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    Require(bool(in), "cannot open marker list: " + path);
    std::vector<std::string> names;
    std::unordered_set<std::string> unique;
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (names.empty() && line.compare(0, 3, "\xEF\xBB\xBF") == 0) line.erase(0, 3);
        Require(!line.empty(), "blank marker-list line; preserve exact snapshot order");
        Require(unique.insert(line).second, "duplicate marker name: " + line);
        names.push_back(line);
        Require(names.size() <= 10000, "marker list too large");
    }
    Require(!in.bad() && !names.empty(), "empty or unreadable marker list");
    return names;
}

void ExpectRejected(const std::string& state, const std::string& device,
                    const std::vector<std::string>& names,
                    const ModalSelfCalConfig& config, const std::string& expected,
                    const char* label) {
    ModalSelfCalState other(config);
    std::string error;
    Require(other.Init(device, names, &error), std::string(label) + " Init failed: " + error);
    ModalSelfCalResumeInfo resume;
    Require(!other.ImportState(state, &resume, &error), std::string(label) + " unexpectedly imported");
    Require(error.find(expected) != std::string::npos,
            std::string(label) + " rejected for unexpected reason: " + error);
    std::cout << "PASS " << label << '\n';
}

void VerifySnapshot(const std::string& state, const std::string& device,
                    const std::vector<std::string>& names) {
    ModalSelfCalState engine; // Release defaults, no CandidateProfiles.h required.
    std::string error;
    Require(engine.Init(device, names, &error), "default Init failed: " + error);
    ModalSelfCalResumeInfo resume;
    Require(engine.ImportState(state, &resume, &error), "Import failed: " + error);
    Require(resume.last_timestamp_ms > 1, "invalid resume timestamp");
    int64_t queried_ts = 0;
    Require(engine.GetResumeTs(&queried_ts, &error), "GetResumeTs failed: " + error);
    Require(queried_ts == resume.last_timestamp_ms, "resume timestamp API mismatch");
    std::string exported;
    int64_t exported_ts = 0;
    Require(engine.ExportState(&exported, &exported_ts, &error), "Export failed: " + error);
    Require(exported == state && exported_ts == resume.last_timestamp_ms,
            "Import/Export not byte-identical or cutoff changed");
    std::cout << "PASS state_roundtrip device=" << device << " markers=" << names.size()
              << " resume_ms=" << exported_ts << " history=" << resume.history_x
              << '/' << resume.history_y << '\n';

    const double missing = std::numeric_limits<double>::quiet_NaN();
    const std::vector<double> empty_frame(names.size(), missing);
    for (const int64_t ts : {resume.last_timestamp_ms, resume.last_timestamp_ms - 1}) {
        ModalSelfCalResult out;
        Require(engine.Process(ts, empty_frame, empty_frame, &out, &error),
                "duplicate/old Process failed: " + error);
        Require(out.duplicate && !out.output_ready && !out.replayed,
                "duplicate/old timestamp incorrectly publishable");
        Require(out.x_source == ModalSelfCalXSource::NoOutput && out.x.empty() && out.y.empty()
                    && out.correction_x.empty() && out.correction_y.empty(),
                "duplicate/old frame leaked published values or source");
        Require(engine.ExportState(&exported, &exported_ts, &error),
                "post-duplicate Export failed: " + error);
        Require(exported == state && exported_ts == resume.last_timestamp_ms,
                "duplicate/old frame mutated snapshot");
    }
    std::cout << "PASS duplicate_and_old_no_output_state_unchanged\n";

    ModalSelfCalConfig defaults;
    ExpectRejected(state, device + "__WRONG_DEVICE", names, defaults,
                   "saved device differs", "wrong_device_rejected");
    auto wrong_names = names;
    if (wrong_names.size() > 1) std::swap(wrong_names[0], wrong_names[1]);
    else wrong_names[0] += "__WRONG_MARKER";
    ExpectRejected(state, device, wrong_names, defaults,
                   "saved marker order differs", "wrong_marker_order_rejected");
    auto wrong_config = defaults;
    wrong_config.max_frame_dev = defaults.max_frame_dev == 0.0 ? 1.0 : 0.0;
    ExpectRejected(state, device, names, wrong_config,
                   "saved math parameters differ", "wrong_config_rejected");
}

void VerifySyntheticBoundaries() {
    // Independent cold stream. These values do not continue the supplied real state.
    // This checks publication boundaries/masks only, not learned model quality or speed.
    const std::vector<std::string> names{"SYN_A", "SYN_B", "SYN_C", "SYN_D", "SYN_E", "SYN_F"};
    const double missing = std::numeric_limits<double>::quiet_NaN();
    const std::vector<double> raw_x{missing, 1.0, -2.0, 3.0, 4.0, 5.0};
    const std::vector<double> raw_y{missing, 11.0, 12.0, 13.0, 14.0, 15.0};
    struct Boundary { int64_t timestamp; bool night; };
    // UTC milliseconds, evaluated in release UTC+8; 2026-11-16/17 local dates.
    const Boundary cases[] = {
        {1794837600000LL, false}, // 11/16 22:00
        {1794841199999LL, false}, // 11/16 22:59:59.999
        {1794841200000LL, true},  // 11/16 23:00
        {1794869999999LL, true},  // 11/17 06:59:59.999
        {1794870000000LL, false}, // 11/17 07:00
        {1794871200000LL, false}  // 11/17 07:20
    };
    ModalSelfCalState engine;
    std::string error;
    Require(engine.Init("SYNTHETIC_BOUNDARY_ONLY", names, &error), "synthetic Init: " + error);
    for (const auto& c : cases) {
        ModalSelfCalResult out;
        Require(engine.Process(c.timestamp, raw_x, raw_y, &out, &error), "synthetic Process: " + error);
        Require(out.output_ready && !out.duplicate && !out.replayed, "synthetic frame not ready");
        Require(out.x_source == (c.night ? ModalSelfCalXSource::NightCorrection
                                        : ModalSelfCalXSource::RawObservation),
                "wrong source at boundary " + std::to_string(c.timestamp));
        Require(out.x.size() == names.size() && out.y.size() == names.size()
                    && out.correction_x.size() == names.size(), "synthetic output shape mismatch");
        Require(std::isnan(out.x[0]) && std::isnan(out.y[0]) && std::isnan(out.correction_x[0]),
                "invalid synthetic point became finite");
        if (!c.night) for (std::size_t i = 1; i < names.size(); ++i) {
            Require(out.x[i] == raw_x[i] && out.correction_x[i] == 0.0,
                    "outside-window X is not exact raw");
        }
    }
    // Separate synthetic new timestamp advances state but must not publish replay values.
    ModalSelfCalResult replay;
    Require(engine.Process(1794871260000LL, raw_x, raw_y, &replay, &error, true),
            "synthetic replay failed: " + error);
    Require(!replay.output_ready && replay.replayed && !replay.duplicate
                && replay.x_source == ModalSelfCalXSource::NoOutput
                && replay.x.empty() && replay.y.empty()
                && replay.correction_x.empty() && replay.correction_y.empty(),
            "synthetic history replay leaked published output");
    std::cout << "PASS SYNTHETIC_ONLY publication_boundaries_nan_and_replay"
                 " (not real continuation, model quality, or performance)\n";
}
} // namespace

int main(int argc, char** argv) {
    if ((argc != 4 && argc != 5) || (argc == 5 && std::string(argv[4]) != "--synthetic-boundaries")) {
        std::cerr << "Usage: verify_release.exe state_file device_id marker.txt [--synthetic-boundaries]\n";
        return 2;
    }
    try {
        const auto state = ReadBytes(argv[1]);
        const auto names = ReadNames(argv[3]);
        VerifySnapshot(state, argv[2], names);
        if (argc == 5) VerifySyntheticBoundaries();
        else std::cout << "SKIP synthetic_boundary_tests (optional flag not supplied)\n";
        std::cout << "SKIP real_2026_11_16_22_23_continuation (not supplied; no fabricated frames)\n";
        std::cout << "PASS requested_checks; no state or database file was modified\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "FAIL " << e.what() << '\n';
        return 1;
    }
}
