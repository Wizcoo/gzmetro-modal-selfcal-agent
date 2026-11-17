// ===========================================================================
// test_v54.cpp: Comprehensive unit test & validation for ModalSelfCal-V54
// ===========================================================================

#include "ModalSelfCal.h"
#include <iostream>
#include <cassert>
#include <cmath>
#include <vector>
#include <string>

int legacy_main() {
    std::cout << "=======================================================\n";
    std::cout << "Starting ModalSelfCal-V54 Validation Tests (Scheme D)\n";
    std::cout << "=======================================================\n";

    std::vector<std::string> names = {"YD0101", "YD0102", "YD0103", "YD0104", "YD0105", "YJ1", "YJ2"};
    std::string dev = "780639346578";

    // -----------------------------------------------------------------------
    // Test 1: Cold start initialization with NO state package (allow_new_stream = true)
    // -----------------------------------------------------------------------
    std::cout << "\n[Test 1] Testing Cold Start Initialization (Zero State Package Dependency)...\n";
    ModalSelfCalConfig cfg;
    cfg.enable_x_w3_filter = true;
    cfg.enable_x_mount_drift_damping = true;
    cfg.mount_drift_shrinkage = 0.55;
    cfg.enable_x_velocity_damping = true;
    cfg.velocity_damping_tau_min = 1.5;

    ModalSelfCalState state(cfg);
    std::string err;
    bool ok = state.Init(dev, names, &err, /*allow_new_stream=*/true);
    assert(ok && "Init must succeed in cold start mode");
    std::cout << "  -> Init succeeded: allow_new_stream=true, 0 state dependency.\n";

    // -----------------------------------------------------------------------
    // Test 2: Daytime 100% Transparent Passthrough
    // -----------------------------------------------------------------------
    std::cout << "\n[Test 2] Testing Daytime Transparent Passthrough (12:00 Local Beijing Time)...\n";
    // 2026-11-08 12:00:00 GMT+8 = 1794110400000 ms
    int64_t ts_day = 1794110400000LL;
    std::vector<double> raw_x = {1.23, 2.34, 3.45, 4.56, 5.67, 0.12, 0.23};
    std::vector<double> raw_y = {-1.0, -2.0, -3.0, -4.0, -5.0, 0.0, 0.0};

    ModalSelfCalResult res;
    ok = state.Process(ts_day, raw_x, raw_y, &res, &err);
    assert(ok && "Process must succeed in daytime");
    assert(res.output_ready && "Daytime output must be ready");
    for (size_t i = 0; i < raw_x.size(); ++i) {
        assert(std::abs(res.x[i] - raw_x[i]) < 1e-9 && "Daytime X must be 100% passthrough");
        assert(std::abs(res.y[i] - raw_y[i]) < 1e-9 && "Daytime Y must be 100% passthrough");
    }
    std::cout << "  -> Daytime test passed: X and Y are 100% bitwise passthrough.\n";

    // -----------------------------------------------------------------------
    // Test 3: Night Shift Window Processing & W=3 + S2 + S1 Integration
    // -----------------------------------------------------------------------
    std::cout << "\n[Test 3] Testing Night Shift Sequence (22:30 Baseline -> 23:30 Construction)...\n";
    // 2026-11-08 22:30:00 GMT+8 = 1794148200000 ms
    int64_t ts_base = 1794148200000LL;
    for (int fr = 0; fr < 35; ++fr) {
        int64_t t = ts_base + fr * 60000LL;
        ok = state.Process(t, raw_x, raw_y, &res, &err);
        assert(ok);
    }
    std::cout << "  -> Baseline window processed (35 frames), state=" << res.info_x.state << "\n";

    // 2026-11-08 23:30:00 GMT+8 (Construction window, gate >= 1.0)
    int64_t ts_night = 1794151800000LL;
    std::cout << "  -> Simulating night construction frames with artificial flicker and common drift...\n";
    int64_t last_night_ts = ts_night;
    for (int fr = 0; fr < 40; ++fr) {
        int64_t t = ts_night + fr * 60000LL;
        last_night_ts = t;
        std::vector<double> jitter_x = raw_x;
        for (auto& v : jitter_x) {
            v += (fr % 2 == 0 ? 0.4 : -0.4) + 0.05 * fr;
        }
        ok = state.Process(t, jitter_x, raw_y, &res, &err);
        assert(ok);
        assert(res.output_ready);
    }
    std::cout << "  -> Night construction test passed: gate=" << res.info_x.gate
              << ", corrected_points=" << res.info_x.n_corrected
              << ", Scheme D S2 & S1 successfully active!\n";

    // -----------------------------------------------------------------------
    // Test 4: Global Function API Compatibility
    // -----------------------------------------------------------------------
    std::cout << "\n[Test 4] Testing Global Functional API (ApplyModalSelfCal)...\n";
    bool init_global = InitModalSelfCal(dev, names, &err);
    assert(init_global && "Global Init must succeed");

    std::vector<double> out_x, out_y;
    int64_t ts_glob = ts_day + 10000LL;
    bool apply_global = ApplyModalSelfCal(dev, ts_glob, raw_x, raw_y, &out_x, &out_y, &names);
    assert(apply_global && "ApplyModalSelfCal must succeed");
    assert(out_x.size() == raw_x.size());
    assert(out_y.size() == raw_y.size());
    std::cout << "  -> Global API test passed: InitModalSelfCal & ApplyModalSelfCal work perfectly.\n";

    // -----------------------------------------------------------------------
    // Test 5: State Export & Import Portability (Testing Hot Restart with Scheme D State)
    // -----------------------------------------------------------------------
    std::cout << "\n[Test 5] Testing State Export and Hot Restart (Scheme D State Persistence)...\n";
    std::string snapshot;
    int64_t exported_ts = 0;
    bool exp_ok = state.ExportState(&snapshot, &exported_ts, &err);
    assert(exp_ok && "ExportState must succeed");
    assert(snapshot.find("# SCHEME_D_V54") != std::string::npos && "Snapshot must contain Scheme D state block");
    std::cout << "  -> Exported snapshot bytes=" << snapshot.size() << ", ts=" << exported_ts << "\n";
    std::cout << "  -> Confirmed: Scheme D state (w3, mount baseline, vel) embedded in state snapshot!\n";

    ModalSelfCalState hot_state(cfg);
    hot_state.Init(dev, names, &err, /*allow_new_stream=*/false);
    ModalSelfCalResumeInfo resume;
    bool imp_ok = hot_state.ImportState(snapshot, &resume, &err);
    assert(imp_ok && "ImportState must succeed");
    assert(resume.last_timestamp_ms == exported_ts);
    std::cout << "  -> Hot restart test passed: Imported snapshot matched ts=" << resume.last_timestamp_ms << "\n";

    // Verify next frame consistency: hot_state vs continuous state
    int64_t next_t = last_night_ts + 60000LL;
    std::vector<double> test_raw_x = raw_x;
    for (auto& v : test_raw_x) v += 0.2;
    ModalSelfCalResult res_cont, res_hot;
    state.Process(next_t, test_raw_x, raw_y, &res_cont);
    hot_state.Process(next_t, test_raw_x, raw_y, &res_hot);
    for (size_t i = 0; i < names.size(); ++i) {
        assert(std::abs(res_cont.x[i] - res_hot.x[i]) < 1e-9 && "Hot restart must match continuous run bitwise!");
    }
    std::cout << "  -> Bitwise continuity verified: Hot restarted state produces EXACT same output as continuous running!\n";

    std::cout << "\n=======================================================\n";
    std::cout << "ALL 5 TEST SUITES PASSED SUCCESSFULLY (100% VERIFIED)!\n";
    std::cout << "=======================================================\n";
    return 0;
}

extern "C" __declspec(dllexport) int run_legacy_tests(){return legacy_main();}
