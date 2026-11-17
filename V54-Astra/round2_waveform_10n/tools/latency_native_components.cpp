// Component attribution only: exact original implementation, without modal fitting.
// Source remains unchanged. Inputs/outputs are doubles in pixels at 1 min cadence.
#include "../baseline_src/ModalSelfCal.cpp"

extern "C" __declspec(dllexport) int latency_components(
    int n, const double* input, int isolated_point, double* output) {
    try {
        if (n <= 0 || !input || !output) return 1;
        std::vector<std::string> names;
        for (int j = 0; j < 9; ++j) names.push_back("P" + std::to_string(j));
        gzmetro_msc::CausalMedianFilterBank w3, w3s1, all_w3;
        gzmetro_msc::MildVelocityDamping s1, w3s1_damp, s2s1_damp, all_s1;
        gzmetro_msc::MountThermalDamping s2, s2s1_mount, all_s2;
        w3.Init(names); w3s1.Init(names); all_w3.Init(names);
        s1.Init(names); w3s1_damp.Init(names); s2s1_damp.Init(names); all_s1.Init(names);
        s2.Init(names); s2s1_mount.Init(names); all_s2.Init(names);
        for (int i = 0; i < n; ++i) {
            const int64_t ts = 1793592000000LL + int64_t(i) * 60000;
            std::vector<double> raw(9, isolated_point ? 0.0 : input[i]);
            raw[0] = input[i];
            auto a = w3.Filter(ts, raw);
            auto b = raw; s1.Apply(ts, 1.0, 1.5, &b);
            auto c = w3s1.Filter(ts, raw); w3s1_damp.Apply(ts, 1.0, 1.5, &c);
            auto d = raw; s2.Apply(ts, 1.0, 1, .55, &d);
            auto e = raw; s2s1_mount.Apply(ts, 1.0, 1, .55, &e); s2s1_damp.Apply(ts, 1.0, 1.5, &e);
            auto f = all_w3.Filter(ts, raw); all_s2.Apply(ts, 1.0, 1, .55, &f); all_s1.Apply(ts, 1.0, 1.5, &f);
            output[6*i+0] = a[0]; output[6*i+1] = b[0]; output[6*i+2] = c[0];
            output[6*i+3] = d[0]; output[6*i+4] = e[0]; output[6*i+5] = f[0];
        }
        return 0;
    } catch (...) { return 2; }
}
