#include "ModalSelfCal.h"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <locale>
#include <map>
#include <memory>
#include <mutex>
#include <numeric>
#include <sstream>
#include <unordered_map>


#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <exception>

namespace {
std::atomic<bool>& MscDebugEnabled() { static std::atomic<bool> enabled{true}; return enabled; }
std::atomic<unsigned long long>& MscDebugSequence() { static std::atomic<unsigned long long> seq{0}; return seq; }
thread_local unsigned long long msc_debug_parent = 0;
void MscDebugPrint(const char* api, const char* event, const char* format = "", ...) noexcept {
    if (!MscDebugEnabled().load(std::memory_order_relaxed)) return;
    // No callbacks or engine locks. Never print package payloads or point arrays.
    char text[1536];
    va_list args; va_start(args, format); std::vsnprintf(text, sizeof(text), format, args); va_end(args);
    for (char* p = text; *p; ++p) if (*p == '\n' || *p == '\r') *p = ' ';
    try {
        static std::mutex output_mutex;
        std::lock_guard<std::mutex> lock(output_mutex);
        std::fprintf(stderr, "[MSC] id=%llu api=%s ev=%s %s\n", msc_debug_parent, api, event, text);
        std::fflush(stderr);
    } catch (...) { /* Diagnostics must never alter algorithm error handling. */ }
}
struct MscDebugScope {
    const char* api;
    const void* object;
    unsigned long long id = 0, parent = 0;
    int ok = -1, exceptions = 0;
    const gzmetro_msc::ModalSelfCalFrameInfo* info = nullptr;
    explicit MscDebugScope(const char* name, const void* obj = nullptr) noexcept : api(name), object(obj) {
        if (!MscDebugEnabled().load(std::memory_order_relaxed)) return;
        id = ++MscDebugSequence(); parent = msc_debug_parent; msc_debug_parent = id;
        exceptions = std::uncaught_exceptions();
        MscDebugPrint(api, "in", "parent=%llu obj=%p", parent, object);
    }
    bool Result(bool value) noexcept { ok = value ? 1 : 0; return value; }
    ~MscDebugScope() noexcept {
        if (!id) return;
        if (info) MscDebugPrint(api, "frame", "obj=%p ts=%lld state=%s hist=%d frozen=%d ready=%d tonight=%d learn=%d valid=%d corrected=%d gate=%.3f",
            object, static_cast<long long>(info->ts_ms), info->state.c_str(), info->n_history,
            int(info->baseline_frozen), int(info->modes_ready), int(info->modes_from_tonight),
            info->n_learn_points, info->n_frame_learn_valid, info->n_corrected, info->gate);
        MscDebugPrint(api, "out", "obj=%p ok=%d exception=%d", object, ok, int(std::uncaught_exceptions() > exceptions));
        msc_debug_parent = parent;
    }
};
}

namespace gzmetro_msc {

namespace {

const double kMscNaN = std::numeric_limits<double>::quiet_NaN();

inline bool MscFinite(double v) { return std::isfinite(v); }

// 时间戳 → (夜号, 夜内小时)。本地 0~12 点归前一夜并记作 24~36 点。
void MscLocalParts(int64_t ts_ms, double tz_h, int64_t* night, double* hour) {
    const double t = static_cast<double>(ts_ms) / 1000.0 + tz_h * 3600.0;
    const double day = std::floor(t / 86400.0);
    const double h = (t - day * 86400.0) / 3600.0;
    if (h < 12.0) {
        *night = static_cast<int64_t>(day) - 1;
        *hour = h + 24.0;
    } else {
        *night = static_cast<int64_t>(day);
        *hour = h;
    }
}

double MscMedianOf(std::vector<double> v) {
    const std::size_t n = v.size();
    if (n == 0) return kMscNaN;
    std::sort(v.begin(), v.end());
    return (n % 2 == 1) ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

// 对称矩阵 Jacobi 特征分解。a: n×n 行主序（会被破坏）；输出特征值降序 w、特征向量列 V（V[i*n+k]）。
void MscJacobiEigen(std::vector<double> a, int n, std::vector<double>* w_out, std::vector<double>* v_out) {
    std::vector<double> V(static_cast<std::size_t>(n) * n, 0.0);
    for (int i = 0; i < n; ++i) V[static_cast<std::size_t>(i) * n + i] = 1.0;
    auto A = [&](int i, int j) -> double& { return a[static_cast<std::size_t>(i) * n + j]; };
    auto VV = [&](int i, int j) -> double& { return V[static_cast<std::size_t>(i) * n + j]; };

    for (int sweep = 0; sweep < 100; ++sweep) {
        double off = 0.0, dsum = 0.0;
        for (int i = 0; i < n; ++i) {
            dsum += A(i, i) * A(i, i);
            for (int j = i + 1; j < n; ++j) off += A(i, j) * A(i, j);
        }
        if (off < 1e-22 * (std::max)(1.0, dsum)) break;
        for (int p = 0; p < n - 1; ++p) {
            for (int q = p + 1; q < n; ++q) {
                const double apq = A(p, q);
                if (std::fabs(apq) < 1e-300) continue;
                const double theta = (A(q, q) - A(p, p)) / (2.0 * apq);
                const double t = (theta >= 0.0 ? 1.0 : -1.0) / (std::fabs(theta) + std::sqrt(theta * theta + 1.0));
                const double c = 1.0 / std::sqrt(t * t + 1.0);
                const double s = t * c;
                for (int k = 0; k < n; ++k) {
                    const double akp = A(k, p), akq = A(k, q);
                    A(k, p) = c * akp - s * akq;
                    A(k, q) = s * akp + c * akq;
                }
                for (int k = 0; k < n; ++k) {
                    const double apk = A(p, k), aqk = A(q, k);
                    A(p, k) = c * apk - s * aqk;
                    A(q, k) = s * apk + c * aqk;
                }
                for (int k = 0; k < n; ++k) {
                    const double vkp = VV(k, p), vkq = VV(k, q);
                    VV(k, p) = c * vkp - s * vkq;
                    VV(k, q) = s * vkp + c * vkq;
                }
            }
        }
    }
    std::vector<double> w(n);
    for (int i = 0; i < n; ++i) w[i] = A(i, i);
    std::vector<int> ord(n);
    std::iota(ord.begin(), ord.end(), 0);
    std::stable_sort(ord.begin(), ord.end(), [&](int x, int y) { return w[x] > w[y]; });
    w_out->assign(n, 0.0);
    v_out->assign(static_cast<std::size_t>(n) * n, 0.0);
    for (int k = 0; k < n; ++k) {
        (*w_out)[k] = w[ord[k]];
        for (int i = 0; i < n; ++i) (*v_out)[static_cast<std::size_t>(i) * n + k] = VV(i, ord[k]);
    }
}

// K×K 部分选主元高斯消元；主元 < 1e-12 × max|diag| 视为奇异。
bool MscSolveSmall(std::vector<double> G, std::vector<double> r, int K, std::vector<double>* x) {
    double scale = 1e-300;
    for (int i = 0; i < K; ++i) scale = (std::max)(scale, std::fabs(G[static_cast<std::size_t>(i) * K + i]));
    for (int c = 0; c < K; ++c) {
        int piv = c;
        double best = std::fabs(G[static_cast<std::size_t>(c) * K + c]);
        for (int rr = c + 1; rr < K; ++rr) {
            const double v = std::fabs(G[static_cast<std::size_t>(rr) * K + c]);
            if (v > best) { best = v; piv = rr; }
        }
        if (best < 1e-12 * scale) return false;
        if (piv != c) {
            for (int j = 0; j < K; ++j) std::swap(G[static_cast<std::size_t>(c) * K + j], G[static_cast<std::size_t>(piv) * K + j]);
            std::swap(r[c], r[piv]);
        }
        const double d = G[static_cast<std::size_t>(c) * K + c];
        for (int j = c; j < K; ++j) G[static_cast<std::size_t>(c) * K + j] /= d;
        r[c] /= d;
        for (int rr = 0; rr < K; ++rr) {
            if (rr == c) continue;
            const double f = G[static_cast<std::size_t>(rr) * K + c];
            if (f == 0.0) continue;
            for (int j = c; j < K; ++j) G[static_cast<std::size_t>(rr) * K + j] -= f * G[static_cast<std::size_t>(c) * K + j];
            r[rr] -= f * r[c];
        }
    }
    *x = r;
    return true;
}

// ---------- 文本序列化工具 ----------
void MscPutNum(std::ostream& os, double v) {
    if (std::isnan(v)) os << "nan";
    else os << v;
}
void MscPutVec(std::ostream& os, const char* key, const std::vector<double>& v) {
    os << key << '=';
    for (std::size_t i = 0; i < v.size(); ++i) { if (i) os << ','; MscPutNum(os, v[i]); }
    os << '\n';
}
void MscPutUpper(std::ostream& os, const char* key, const std::vector<double>& m, std::size_t p) {
    os << key << '=';
    bool first = true;
    for (std::size_t i = 0; i < p; ++i)
        for (std::size_t j = i; j < p; ++j) { if (!first) os << ','; first = false; MscPutNum(os, m[i * p + j]); }
    os << '\n';
}
void MscPutNames(std::ostream& os, const char* key, const std::vector<std::string>& v) {
    os << key << '=';
    for (std::size_t i = 0; i < v.size(); ++i) { if (i) os << ','; os << v[i]; }
    os << '\n';
}

std::vector<std::string> MscSplit(const std::string& s, char sep) {
    std::vector<std::string> out;
    if (s.empty()) return out;
    std::string cur;
    for (char ch : s) {
        if (ch == sep) { out.push_back(cur); cur.clear(); }
        else cur.push_back(ch);
    }
    out.push_back(cur);
    return out;
}

bool MscParseNum(const std::string& tok, double* v) {
    if (tok == "nan" || tok == "NaN" || tok == "-nan") { *v = kMscNaN; return true; }
    std::istringstream is(tok);
    is.imbue(std::locale::classic());
    is >> *v;
    return !is.fail();
}

class MscLineReader {
public:
    explicit MscLineReader(const std::string& blob) {
        std::istringstream is(blob);
        std::string line;
        while (std::getline(is, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            lines_.push_back(line);
        }
    }
    bool Next(const std::string& key, std::string* value) {
        if (pos_ >= lines_.size()) return Fail("缺少字段 " + key);
        const std::string& l = lines_[pos_];
        const std::size_t eq = l.find('=');
        if (eq == std::string::npos || l.substr(0, eq) != key) return Fail("期望字段 " + key + "，实际为: " + l.substr(0, 40));
        *value = l.substr(eq + 1);
        ++pos_;
        return true;
    }
    bool NextLine(std::string* line) {
        if (pos_ >= lines_.size()) return Fail("快照意外结束");
        *line = lines_[pos_++];
        return true;
    }
    bool Int(const std::string& key, int64_t* v) {
        std::string s;
        if (!Next(key, &s)) return false;
        double d;
        if (!MscParseNum(s, &d) || !MscFinite(d)) return Fail("字段 " + key + " 不是数字");
        *v = static_cast<int64_t>(std::llround(d));
        return true;
    }
    bool Num(const std::string& key, double* v) {
        std::string s;
        if (!Next(key, &s)) return false;
        if (!MscParseNum(s, v)) return Fail("字段 " + key + " 不是数字");
        return true;
    }
    bool Vec(const std::string& key, std::size_t n, std::vector<double>* v) {
        std::string s;
        if (!Next(key, &s)) return false;
        const auto toks = MscSplit(s, ',');
        if (toks.size() != n) return Fail("字段 " + key + " 长度不符");
        v->resize(n);
        for (std::size_t i = 0; i < n; ++i)
            if (!MscParseNum(toks[i], &(*v)[i])) return Fail("字段 " + key + " 含非法数字");
        return true;
    }
    bool Upper(const std::string& key, std::size_t p, std::vector<double>* m) {
        std::vector<double> u;
        if (!Vec(key, p * (p + 1) / 2, &u)) return false;
        m->assign(p * p, 0.0);
        std::size_t k = 0;
        for (std::size_t i = 0; i < p; ++i)
            for (std::size_t j = i; j < p; ++j) { (*m)[i * p + j] = u[k]; (*m)[j * p + i] = u[k]; ++k; }
        return true;
    }
    bool Names(const std::string& key, std::vector<std::string>* v) {
        std::string s;
        if (!Next(key, &s)) return false;
        *v = MscSplit(s, ',');
        return true;
    }
    bool Fail(const std::string& msg) { if (err_.empty()) err_ = msg; return false; }
    const std::string& error() const { return err_; }
    std::size_t pos() const { return pos_; }
    void Seek(std::size_t p) { pos_ = p; }
    const std::vector<std::string>& lines() const { return lines_; }

private:
    std::vector<std::string> lines_;
    std::size_t pos_ = 0;
    std::string err_;
};

}  // namespace

// ===========================================================================
// 单轴引擎内部实现
// ===========================================================================
struct ModalSelfCalAxis::Impl {
    struct NightStat {
        int64_t night_id = 0;
        std::vector<std::string> names;
        std::vector<double> S, N;          // p×p
        int64_t n_frames = 0;
    };
    struct RefFrame {
        double h = 0.0;
        std::vector<double> y;
    };

    const ModalSelfCalConfig* cfg = nullptr;
    std::size_t p = 0;
    std::vector<char> fit_only;

    std::vector<NightStat> history;         // 旧 → 新，最多 history_nights 份

    bool has_last_ts = false;
    int64_t last_ts = 0;
    bool has_night = false;
    int64_t night_id = 0;

    std::vector<double> ref_sum, ref_cnt;
    std::vector<RefFrame> ref_buf;
    bool frozen = false;
    std::vector<double> b;
    std::vector<double> S, N;
    int64_t n_learn = 0;
    bool learn_done = false;

    bool modes_has = false;
    bool modes_from_tonight = false;
    int n_learn_points = 0;
    std::vector<double> A;                  // p×K，无载荷为 NaN
    std::vector<char> use, learn;
    std::vector<double> cbar;
    double apply_from_h = 23.0;

    int K() const { return (std::max)(1, cfg->K); }
    std::size_t RefCap() const { return static_cast<std::size_t>(2.0 * 3600.0 / (std::max)(1.0, cfg->cadence_s)); }

    void SetNames(const std::vector<std::string>& names) {
        p = names.size();
        fit_only.assign(p, 0);
        for (std::size_t i = 0; i < p; ++i)
            for (const auto& pre : cfg->fit_only_prefixes)
                if (!pre.empty() && names[i].compare(0, pre.size(), pre) == 0) fit_only[i] = 1;
    }

    void NewNight(int64_t nid) {
        has_night = true;
        night_id = nid;
        ref_sum.assign(p, 0.0);
        ref_cnt.assign(p, 0.0);
        ref_buf.clear();
        frozen = false;
        b.assign(p, kMscNaN);
        S.assign(p * p, 0.0);
        N.assign(p * p, 0.0);
        n_learn = 0;
        learn_done = false;
        modes_has = false;
        modes_from_tonight = false;
        n_learn_points = 0;
        A.assign(p * K(), kMscNaN);
        use.assign(p, 0);
        learn.assign(p, 0);
        cbar.assign(p, 0.0);
        apply_from_h = cfg->ref_end_h;
    }

    void Accumulate(const std::vector<double>& y) {
        std::vector<std::size_t> idx;
        std::vector<double> z;
        idx.reserve(p); z.reserve(p);
        for (std::size_t i = 0; i < p; ++i) {
            const double v = y[i] - b[i];
            if (MscFinite(v)) { idx.push_back(i); z.push_back(v); }
        }
        if (idx.empty()) return;
        for (std::size_t a = 0; a < idx.size(); ++a) {
            const std::size_t ia = idx[a] * p;
            for (std::size_t c = 0; c < idx.size(); ++c) {
                S[ia + idx[c]] += z[a] * z[c];
                N[ia + idx[c]] += 1.0;
            }
        }
        ++n_learn;
    }

    // 合并若干夜（按点名对齐到当前名单）
    void Pooled(const std::vector<const NightStat*>& stats, const std::vector<std::string>& names,
                std::vector<double>* Sp, std::vector<double>* Np, int64_t* nf) const {
        Sp->assign(p * p, 0.0);
        Np->assign(p * p, 0.0);
        *nf = 0;
        std::unordered_map<std::string, std::size_t> pos;
        for (std::size_t i = 0; i < p; ++i) pos[names[i]] = i;
        for (const NightStat* st : stats) {
            const std::size_t q = st->names.size();
            std::vector<long long> map(q, -1);
            for (std::size_t j = 0; j < q; ++j) {
                auto it = pos.find(st->names[j]);
                if (it != pos.end()) map[j] = static_cast<long long>(it->second);
            }
            for (std::size_t a = 0; a < q; ++a) {
                if (map[a] < 0) continue;
                for (std::size_t c = 0; c < q; ++c) {
                    if (map[c] < 0) continue;
                    const std::size_t dst = static_cast<std::size_t>(map[a]) * p + static_cast<std::size_t>(map[c]);
                    (*Sp)[dst] += st->S[a * q + c];
                    (*Np)[dst] += st->N[a * q + c];
                }
            }
            *nf += st->n_frames;
        }
    }

    bool ModesFrom(const std::vector<double>& Sp, const std::vector<double>& Np, int64_t nf) {
        const int k = K();
        modes_has = false;
        if (nf <= 0) return false;
        std::vector<double> C(p * p, 0.0);
        for (std::size_t i = 0; i < p * p; ++i) C[i] = (Np[i] > 1.0) ? Sp[i] / (std::max)(Np[i], 1.0) : 0.0;
        std::vector<char> u(p, 0), base(p, 0), lr(p, 0);
        int nbase = 0;
        for (std::size_t i = 0; i < p; ++i) {
            u[i] = Np[i * p + i] >= cfg->min_valid_ratio * static_cast<double>(nf);
            base[i] = u[i] && !fit_only[i];
            nbase += base[i];
        }
        if (nbase < k + 2) return false;
        std::vector<double> sd(p);
        for (std::size_t i = 0; i < p; ++i) sd[i] = std::sqrt((std::max)(C[i * p + i], 0.0));
        lr = base;
        if (cfg->spread_k > 0) {
            std::vector<double> sb;
            for (std::size_t i = 0; i < p; ++i) if (base[i]) sb.push_back(sd[i]);
            const double med = MscMedianOf(sb);
            for (std::size_t i = 0; i < p; ++i) if (lr[i] && !(sd[i] <= cfg->spread_k * med)) lr[i] = 0;
        }
        if (std::count(lr.begin(), lr.end(), 1) < k + 2) lr = base;

        std::vector<std::size_t> L;
        std::vector<double> w, V;
        for (int iter = 0; iter < 1000; ++iter) {
            L.clear();
            for (std::size_t i = 0; i < p; ++i) if (lr[i]) L.push_back(i);
            const int n = static_cast<int>(L.size());
            std::vector<double> sub(static_cast<std::size_t>(n) * n);
            for (int a = 0; a < n; ++a)
                for (int c = 0; c < n; ++c) sub[static_cast<std::size_t>(a) * n + c] = C[L[a] * p + L[c]];
            MscJacobiEigen(sub, n, &w, &V);
            std::vector<char> bad(n, 0);
            int nbad = 0;
            if (cfg->guard > 0 && cfg->guard < 1) {
                for (int a = 0; a < n; ++a)
                    for (int kk = 0; kk < k; ++kk) {
                        const double uak = V[static_cast<std::size_t>(a) * n + kk];
                        if (uak * uak > cfg->guard) { bad[a] = 1; break; }
                    }
                nbad = static_cast<int>(std::count(bad.begin(), bad.end(), 1));
            }
            if (nbad == 0 || n - nbad < k + 2) break;
            for (int a = 0; a < n; ++a) if (bad[a]) lr[L[a]] = 0;
        }
        const int n = static_cast<int>(L.size());
        if (n < k) return false;
        if (!(w[k - 1] > 1e-12 * (std::max)(w[0], 1e-300))) return false;

        A.assign(p * k, kMscNaN);
        for (int a = 0; a < n; ++a)
            for (int kk = 0; kk < k; ++kk) A[L[a] * k + kk] = V[static_cast<std::size_t>(a) * n + kk];
        for (std::size_t i = 0; i < p; ++i) {
            if (!u[i] || lr[i]) continue;
            for (int kk = 0; kk < k; ++kk) {
                double s = 0.0;
                for (int a = 0; a < n; ++a) s += C[i * p + L[a]] * V[static_cast<std::size_t>(a) * n + kk];
                A[i * k + kk] = s / w[kk];
            }
        }
        use = u;
        learn = lr;
        n_learn_points = n;
        modes_has = true;
        return true;
    }

    // 学习点最小二乘求 v；有效学习点不足或奇异返回 false
    // 支持抗差离群剔除（若残差超出 max_frame_residual 或绝对偏差超 max_frame_dev 则剔除并重算）
    bool SolveV(const std::vector<double>& z, const std::vector<char>& valid, std::vector<double>* v, int* nvalid) const {
        const int k = K();
        const std::size_t need = static_cast<std::size_t>((std::max)(cfg->min_valid, k + 2));

        std::vector<char> active = valid;
        // 步骤 0：若配置了绝对偏差硬门限 max_frame_dev，初筛剔除极端粗差（如 1303 突变到 37mm）
        if (cfg->max_frame_dev > 0.0) {
            for (std::size_t i = 0; i < p; ++i) {
                if (active[i] && learn[i] && std::abs(z[i]) > cfg->max_frame_dev) {
                    active[i] = 0;
                }
            }
        }

        std::vector<double> cur_v;
        int last_valid_cnt = 0;
        const int max_iters = (cfg->max_frame_residual > 0.0) ? 2 : 1;

        for (int iter = 0; iter < max_iters; ++iter) {
            std::vector<double> G(static_cast<std::size_t>(k) * k, 0.0), r(k, 0.0);
            std::size_t cnt = 0;
            for (std::size_t i = 0; i < p; ++i) {
                if (!active[i] || !learn[i]) continue;
                ++cnt;
                const double* ai = &A[i * k];
                for (int a = 0; a < k; ++a) {
                    r[a] += ai[a] * z[i];
                    for (int c = 0; c < k; ++c) G[static_cast<std::size_t>(a) * k + c] += ai[a] * ai[c];
                }
            }
            last_valid_cnt = static_cast<int>(cnt);
            if (cnt < need) return false;
            if (!MscSolveSmall(G, r, k, &cur_v)) return false;

            if (iter + 1 < max_iters) {
                bool found_outlier = false;
                for (std::size_t i = 0; i < p; ++i) {
                    if (!active[i] || !learn[i]) continue;
                    double fit_val = 0.0;
                    for (int kk = 0; kk < k; ++kk) fit_val += A[i * k + kk] * cur_v[kk];
                    if (std::abs(z[i] - fit_val) > cfg->max_frame_residual) {
                        active[i] = 0;
                        found_outlier = true;
                    }
                }
                if (!found_outlier) break; // 无离群点，提前退出
            }
        }

        if (nvalid) *nvalid = last_valid_cnt;
        if (v) *v = std::move(cur_v);
        return true;
    }

    void ComputeCbar() {
        const int k = K();
        std::vector<double> s(p, 0.0), c(p, 0.0), z(p), v;
        std::vector<char> valid(p);
        for (const RefFrame& f : ref_buf) {
            for (std::size_t i = 0; i < p; ++i) {
                const double d = f.y[i] - b[i];
                valid[i] = MscFinite(d);
                z[i] = valid[i] ? d : 0.0;
            }
            if (!SolveV(z, valid, &v, nullptr)) continue;
            for (std::size_t i = 0; i < p; ++i) {
                if (!valid[i] || !use[i]) continue;
                double corr = 0.0;
                for (int kk = 0; kk < k; ++kk) corr += (MscFinite(A[i * k + kk]) ? A[i * k + kk] : 0.0) * v[kk];
                s[i] += corr;
                c[i] += 1.0;
            }
        }
        for (std::size_t i = 0; i < p; ++i) cbar[i] = (c[i] > 0) ? s[i] / c[i] : 0.0;
    }

    double Gate(double h) const {
        const double r = cfg->ramp_min / 60.0;
        if (h < apply_from_h) return 0.0;
        if (h < cfg->apply_end_h) return (r > 0) ? (std::min)(1.0, (h - apply_from_h) / r) : 1.0;
        return (r > 0) ? (std::max)(0.0, 1.0 - (h - cfg->apply_end_h) / r) : 0.0;
    }

    // 名单变化：按点名把夜内状态重映射到新名单（历史统计本身按点名保存，无需改动）
    void Remap(const std::vector<std::string>& old_names, const std::vector<std::string>& new_names) {
        const std::size_t po = old_names.size(), pn = new_names.size();
        std::unordered_map<std::string, std::size_t> pos;
        for (std::size_t i = 0; i < po; ++i) pos[old_names[i]] = i;
        std::vector<long long> m(pn, -1);
        for (std::size_t i = 0; i < pn; ++i) {
            auto it = pos.find(new_names[i]);
            if (it != pos.end()) m[i] = static_cast<long long>(it->second);
        }
        auto vec = [&](const std::vector<double>& v, double fill) {
            std::vector<double> o(pn, fill);
            if (v.size() == po) for (std::size_t i = 0; i < pn; ++i) if (m[i] >= 0) o[i] = v[static_cast<std::size_t>(m[i])];
            return o;
        };
        auto vc = [&](const std::vector<char>& v) {
            std::vector<char> o(pn, 0);
            if (v.size() == po) for (std::size_t i = 0; i < pn; ++i) if (m[i] >= 0) o[i] = v[static_cast<std::size_t>(m[i])];
            return o;
        };
        auto mat = [&](const std::vector<double>& M) {
            std::vector<double> o(pn * pn, 0.0);
            if (M.size() == po * po)
                for (std::size_t i = 0; i < pn; ++i) {
                    if (m[i] < 0) continue;
                    for (std::size_t j = 0; j < pn; ++j)
                        if (m[j] >= 0) o[i * pn + j] = M[static_cast<std::size_t>(m[i]) * po + static_cast<std::size_t>(m[j])];
                }
            return o;
        };
        const int k = K();
        std::vector<double> An(pn * k, kMscNaN);
        if (A.size() == po * k)
            for (std::size_t i = 0; i < pn; ++i)
                if (m[i] >= 0) for (int kk = 0; kk < k; ++kk) An[i * k + kk] = A[static_cast<std::size_t>(m[i]) * k + kk];
        ref_sum = vec(ref_sum, 0.0);
        ref_cnt = vec(ref_cnt, 0.0);
        b = vec(b, kMscNaN);
        cbar = vec(cbar, 0.0);
        for (RefFrame& f : ref_buf) f.y = vec(f.y, kMscNaN);
        S = mat(S);
        N = mat(N);
        A.swap(An);
        use = vc(use);
        learn = vc(learn);
        n_learn_points = static_cast<int>(std::count(learn.begin(), learn.end(), 1));
        SetNames(new_names);
        if (modes_has && n_learn_points < k + 2) modes_has = false;
    }
};

// ===========================================================================
// ModalSelfCalAxis
// ===========================================================================
ModalSelfCalAxis::ModalSelfCalAxis(const ModalSelfCalConfig& config) : config_(config), impl_(new Impl) {
    MscDebugScope trace("ModalSelfCalAxis::ModalSelfCalAxis", this);

    if (config_.K < 1) config_.K = 1;
    impl_->cfg = &config_;
    impl_->SetNames(names_);
    impl_->NewNight(0);
    impl_->has_night = false;
}

ModalSelfCalAxis::~ModalSelfCalAxis() {
    MscDebugScope trace("ModalSelfCalAxis::~ModalSelfCalAxis", this);
 delete impl_; }

int64_t ModalSelfCalAxis::last_ts() const {
    MscDebugScope trace("ModalSelfCalAxis::last_ts", this);
 return (impl_ && impl_->has_last_ts) ? impl_->last_ts : 0; }


const ModalSelfCalFrameInfo& ModalSelfCalAxis::last_info() const {
    MscDebugScope trace("ModalSelfCalAxis::last_info", this);
 return last_info_; }
const std::vector<std::string>& ModalSelfCalAxis::names() const {
    MscDebugScope trace("ModalSelfCalAxis::names", this);
 return names_; }
void ModalSelfCalAxis::SetEnabled(bool enabled) {
    MscDebugScope trace("ModalSelfCalAxis::SetEnabled", this);
    MscDebugPrint("Axis.SetEnabled", "args", "enabled=%d", int(enabled));
 config_.enabled = enabled; }
void SetModalSelfCalLogEnabled(bool enabled) {
    MscDebugPrint("SetModalSelfCalLogEnabled", "set", "enabled=%d", int(enabled));
    MscDebugEnabled().store(enabled, std::memory_order_relaxed);
    if (enabled) MscDebugPrint("SetModalSelfCalLogEnabled", "out", "enabled=1");
}
bool GetModalSelfCalLogEnabled() {
    MscDebugScope trace("GetModalSelfCalLogEnabled", nullptr);
    return trace.Result([&]() -> bool {
 return MscDebugEnabled().load(std::memory_order_relaxed); 
    }());
}

void ModalSelfCalAxis::Bind(const std::vector<std::string>& names) {
    MscDebugScope trace("ModalSelfCalAxis::Bind", this);

    if (names == names_) return;
    if (names_.empty()) {
        names_ = names;
        impl_->SetNames(names_);
        const bool hn = impl_->has_night;
        const int64_t nid = impl_->night_id;
        impl_->NewNight(nid);
        impl_->has_night = hn;
        return;
    }
    impl_->Remap(names_, names);
    names_ = names;
}

void ModalSelfCalAxis::Reset() {
    MscDebugScope trace("ModalSelfCalAxis::Reset", this);

    Impl* fresh = new Impl;
    fresh->cfg = &config_;
    fresh->SetNames(names_);
    fresh->NewNight(0);
    fresh->has_night = false;
    delete impl_;
    impl_ = fresh;
    last_info_ = ModalSelfCalFrameInfo();
}

std::vector<double> ModalSelfCalAxis::Ingest(int64_t ts_ms, const std::vector<double>& values) {
    MscDebugScope trace("ModalSelfCalAxis::Ingest", this);
    trace.info = &last_info_;

    Impl& s = *impl_;
    const ModalSelfCalConfig& cfg = config_;
    std::vector<double> out = values;
    ModalSelfCalFrameInfo info;
    info.ts_ms = ts_ms;
    info.n_history = static_cast<int>(s.history.size());

    if (!cfg.enabled) {
        info.state = "DISABLED";
        last_info_ = info;
        return out;
    }
    if (values.size() != s.p || s.p == 0) {
        info.state = "BAD_INPUT";
        last_info_ = info;
        return out;
    }
    if (s.has_last_ts && ts_ms <= s.last_ts) {
        info.state = "SKIP_BAD_TS";
        last_info_ = info;
        return out;
    }
    s.has_last_ts = true;
    s.last_ts = ts_ms;

    int64_t night;
    double h;
    MscLocalParts(ts_ms, cfg.tz_offset_h, &night, &h);
    if (!s.has_night || night != s.night_id) { MscDebugPrint("Axis.Ingest", "new_night", "night=%lld", static_cast<long long>(night)); s.NewNight(night); }
    info.night_id = night;
    info.night_hour = h;

    auto finish = [&](const char* state, double gate) {
        info.state = state;
        info.gate = gate;
        info.baseline_frozen = s.frozen;
        info.modes_ready = s.modes_has;
        info.modes_from_tonight = s.modes_from_tonight;
        info.n_history = static_cast<int>(s.history.size());
        info.n_learn_points = s.modes_has ? s.n_learn_points : 0;
        last_info_ = info;
        return out;
    };

    // ---- 基准窗：累计、缓存，透传 ----
    if (h >= cfg.ref_start_h && h < cfg.ref_end_h && !s.frozen) {
        for (std::size_t i = 0; i < s.p; ++i)
            if (MscFinite(values[i])) { s.ref_sum[i] += values[i]; s.ref_cnt[i] += 1.0; }
        if (s.ref_buf.size() < s.RefCap()) s.ref_buf.push_back({h, values});
        return finish("BASELINE", 0.0);
    }

    // ---- 23:00 后首帧：冻结基线、补 Gram、按历史求模态 ----
    if (h >= cfg.ref_end_h && !s.frozen && !s.ref_buf.empty()) {
        MscDebugPrint("Axis.Ingest", "freeze", "ref_frames=%zu hist=%zu", s.ref_buf.size(), s.history.size());
        s.frozen = true;
        for (std::size_t i = 0; i < s.p; ++i)
            s.b[i] = (s.ref_cnt[i] >= cfg.min_ref_frames) ? s.ref_sum[i] / (std::max)(s.ref_cnt[i], 1.0) : kMscNaN;
        for (const auto& f : s.ref_buf) s.Accumulate(f.y);
        if (!s.history.empty()) {
            std::vector<const Impl::NightStat*> st;
            const std::size_t n0 = s.history.size() > static_cast<std::size_t>((std::max)(1, cfg.history_nights))
                                       ? s.history.size() - static_cast<std::size_t>((std::max)(1, cfg.history_nights)) : 0;
            for (std::size_t i = n0; i < s.history.size(); ++i) st.push_back(&s.history[i]);
            std::vector<double> Sp, Np;
            int64_t nf;
            s.Pooled(st, names_, &Sp, &Np, &nf);
            if (s.ModesFrom(Sp, Np, nf)) {
                s.modes_from_tonight = false;
                s.apply_from_h = cfg.ref_end_h;
                s.ComputeCbar();
            }
        }
    }

    // ---- 学习窗累计 ----
    if (s.frozen && h < cfg.learn_end_h) s.Accumulate(values);

    // ---- 02:00 后首帧：收夜 ----
    if (s.frozen && h >= cfg.learn_end_h && !s.learn_done) {
        MscDebugPrint("Axis.Ingest", "learn_end", "frames=%lld", static_cast<long long>(s.n_learn));
        s.learn_done = true;
        const double expected = (cfg.learn_end_h - cfg.ref_start_h) * 3600.0 / (std::max)(1.0, cfg.cadence_s);
        if (static_cast<double>(s.n_learn) >= cfg.min_learn_ratio * expected) {
            Impl::NightStat st;
            st.night_id = s.night_id;
            st.names = names_;
            st.S = s.S;
            st.N = s.N;
            st.n_frames = s.n_learn;
            s.history.push_back(std::move(st));
            while (s.history.size() > static_cast<std::size_t>((std::max)(1, cfg.history_nights)))
                s.history.erase(s.history.begin());
            if (!s.modes_has) {                               // 冷启动：用本夜统计，从此刻起修正
                const Impl::NightStat& last = s.history.back();
                if (s.ModesFrom(last.S, last.N, last.n_frames)) {
                    s.modes_from_tonight = true;
                    s.apply_from_h = h;
                    s.ComputeCbar();
                }
            }
        }
        std::fill(s.S.begin(), s.S.end(), 0.0);
        std::fill(s.N.begin(), s.N.end(), 0.0);
    }

    // ---- 修正 ----
    const double g = s.Gate(h);
    if (g <= 0.0) return finish("PASSTHROUGH", 0.0);
    if (!s.modes_has || !s.frozen) return finish("WAIT_MODES", g);

    const int k = s.K();
    std::vector<double> z(s.p), v;
    std::vector<char> valid(s.p);
    for (std::size_t i = 0; i < s.p; ++i) {
        const double d = values[i] - s.b[i];
        valid[i] = MscFinite(d);
        z[i] = valid[i] ? d : 0.0;
    }
    int nvalid = 0;
    if (!s.SolveV(z, valid, &v, &nvalid)) {
        info.n_frame_learn_valid = nvalid;
        return finish("DEGRADED_FRAME", g);
    }
    info.n_frame_learn_valid = nvalid;
    for (int kk = 0; kk < k && kk < 3; ++kk) info.v[kk] = v[kk];
    int ncorr = 0;
    for (std::size_t i = 0; i < s.p; ++i) {
        if (!valid[i] || !s.use[i]) continue;
        double corr = 0.0;
        for (int kk = 0; kk < k; ++kk) corr += (MscFinite(s.A[i * k + kk]) ? s.A[i * k + kk] : 0.0) * v[kk];
        corr -= s.cbar[i];
        out[i] = values[i] - g * corr;
        ++ncorr;
    }
    info.n_corrected = ncorr;
    return finish(g >= 1.0 ? "CORRECTING" : "RAMP", g);
}

bool ModalSelfCalAxis::SaveState(std::string* blob) const {
    MscDebugScope trace("ModalSelfCalAxis::SaveState", this);
    return trace.Result([&]() -> bool {

    if (!blob) return false;
    const Impl& s = *impl_;
    const std::size_t p = s.p;
    std::ostringstream os;
    os.imbue(std::locale::classic());
    os << std::setprecision(17);
    os << "# MODALSELFCAL_AXIS_V1\n";
    os << "cfg=" << config_.K << ',' << config_.ref_start_h << ',' << config_.ref_end_h << ','
       << config_.learn_end_h << ',' << config_.history_nights << '\n';
    MscPutNames(os, "names", names_);
    os << "has_last_ts=" << (s.has_last_ts ? 1 : 0) << '\n';
    os << "last_ts=" << s.last_ts << '\n';
    os << "has_night=" << (s.has_night ? 1 : 0) << '\n';
    os << "night_id=" << s.night_id << '\n';
    os << "frozen=" << (s.frozen ? 1 : 0) << '\n';
    os << "learn_done=" << (s.learn_done ? 1 : 0) << '\n';
    os << "n_learn=" << s.n_learn << '\n';
    os << "apply_from_h=" << s.apply_from_h << '\n';
    MscPutVec(os, "ref_sum", s.ref_sum);
    MscPutVec(os, "ref_cnt", s.ref_cnt);
    MscPutVec(os, "b", s.b);
    MscPutVec(os, "cbar", s.cbar);
    os << "ref_buf_n=" << s.ref_buf.size() << '\n';
    for (const auto& f : s.ref_buf) {
        std::vector<double> row;
        row.push_back(f.h);
        row.insert(row.end(), f.y.begin(), f.y.end());
        MscPutVec(os, "ref", row);
    }
    MscPutUpper(os, "S", s.S, p);
    MscPutUpper(os, "N", s.N, p);
    os << "modes_has=" << (s.modes_has ? 1 : 0) << '\n';
    os << "modes_from_tonight=" << (s.modes_from_tonight ? 1 : 0) << '\n';
    os << "n_learn_points=" << s.n_learn_points << '\n';
    MscPutVec(os, "A", s.A);
    std::vector<double> u(p), l(p);
    for (std::size_t i = 0; i < p; ++i) { u[i] = s.use[i]; l[i] = s.learn[i]; }
    MscPutVec(os, "use", u);
    MscPutVec(os, "learn", l);
    os << "hist_n=" << s.history.size() << '\n';
    for (const auto& st : s.history) {
        os << "hist_night_id=" << st.night_id << '\n';
        os << "hist_n_frames=" << st.n_frames << '\n';
        MscPutNames(os, "hist_names", st.names);
        MscPutUpper(os, "hist_S", st.S, st.names.size());
        MscPutUpper(os, "hist_N", st.N, st.names.size());
    }
    os << "# END\n";
    *blob = os.str();
    return true;

    }());
}

bool ModalSelfCalAxis::LoadState(const std::string& blob, std::string* error) {
    MscDebugScope trace("ModalSelfCalAxis::LoadState", this);
    MscDebugPrint("ModalSelfCalAxis::LoadState", "args", "bytes=%zu", blob.size());
    return trace.Result([&]() -> bool {

    MscLineReader rd(blob);
    std::string line, sv;
    auto fail = [&](const std::string& msg) {
        MscDebugPrint("Axis.LoadState", "reject", "%s", (msg.empty() ? rd.error() : msg).c_str());
        if (error) *error = msg.empty() ? rd.error() : msg;
        return false;
    };
    if (!rd.NextLine(&line) || line != "# MODALSELFCAL_AXIS_V1") return fail("不是 MODALSELFCAL_AXIS_V1 快照");
    if (!rd.Next("cfg", &sv)) return fail("");
    {
        std::ostringstream c;
        c.imbue(std::locale::classic());
        c << std::setprecision(17) << config_.K << ',' << config_.ref_start_h << ',' << config_.ref_end_h << ','
          << config_.learn_end_h << ',' << config_.history_nights;
        if (c.str() != sv) return fail("快照参数(K/窗口/历史夜数)与当前配置不一致: " + sv);
    }
    std::unique_ptr<Impl> t(new Impl);
    t->cfg = &config_;
    std::vector<std::string> names;
    if (!rd.Names("names", &names)) return fail("");
    t->SetNames(names);
    const std::size_t p = names.size();
    int64_t iv;
    if (!rd.Int("has_last_ts", &iv)) return fail("");
    t->has_last_ts = iv != 0;
    if (!rd.Int("last_ts", &t->last_ts)) return fail("");
    if (!rd.Int("has_night", &iv)) return fail("");
    t->has_night = iv != 0;
    if (!rd.Int("night_id", &t->night_id)) return fail("");
    if (!rd.Int("frozen", &iv)) return fail("");
    t->frozen = iv != 0;
    if (!rd.Int("learn_done", &iv)) return fail("");
    t->learn_done = iv != 0;
    if (!rd.Int("n_learn", &t->n_learn)) return fail("");
    if (!rd.Num("apply_from_h", &t->apply_from_h)) return fail("");
    if (!rd.Vec("ref_sum", p, &t->ref_sum) || !rd.Vec("ref_cnt", p, &t->ref_cnt) ||
        !rd.Vec("b", p, &t->b) || !rd.Vec("cbar", p, &t->cbar)) return fail("");
    if (!rd.Int("ref_buf_n", &iv) || iv < 0 || iv > 100000) return fail(rd.error().empty() ? "ref_buf_n 非法" : "");
    for (int64_t i = 0; i < iv; ++i) {
        std::vector<double> row;
        if (!rd.Vec("ref", p + 1, &row)) return fail("");
        t->ref_buf.push_back({row[0], std::vector<double>(row.begin() + 1, row.end())});
    }
    if (!rd.Upper("S", p, &t->S) || !rd.Upper("N", p, &t->N)) return fail("");
    if (!rd.Int("modes_has", &iv)) return fail("");
    t->modes_has = iv != 0;
    if (!rd.Int("modes_from_tonight", &iv)) return fail("");
    t->modes_from_tonight = iv != 0;
    if (!rd.Int("n_learn_points", &iv)) return fail("");
    t->n_learn_points = static_cast<int>(iv);
    if (!rd.Vec("A", p * static_cast<std::size_t>((std::max)(1, config_.K)), &t->A)) return fail("");
    std::vector<double> u, l;
    if (!rd.Vec("use", p, &u) || !rd.Vec("learn", p, &l)) return fail("");
    t->use.assign(p, 0); t->learn.assign(p, 0);
    for (std::size_t i = 0; i < p; ++i) { t->use[i] = u[i] != 0.0; t->learn[i] = l[i] != 0.0; }
    int64_t hn;
    if (!rd.Int("hist_n", &hn) || hn < 0 || hn > 1000) return fail(rd.error().empty() ? "hist_n 非法" : "");
    for (int64_t i = 0; i < hn; ++i) {
        Impl::NightStat st;
        if (!rd.Int("hist_night_id", &st.night_id) || !rd.Int("hist_n_frames", &st.n_frames) ||
            !rd.Names("hist_names", &st.names) || !rd.Upper("hist_S", st.names.size(), &st.S) ||
            !rd.Upper("hist_N", st.names.size(), &st.N)) return fail("");
        t->history.push_back(std::move(st));
    }
    if (!rd.NextLine(&line) || line != "# END") return fail("快照缺少结束标记（可能被截断）");

    // 成功：替换状态。若当前已绑定的名单与快照不同，按点名重映射到当前名单。
    const std::vector<std::string> cur = names_;
    delete impl_;
    impl_ = t.release();
    names_ = names;
    if (!cur.empty() && cur != names_) {
        impl_->Remap(names_, cur);
        names_ = cur;
    }
    return true;

    }());
}


} // namespace gzmetro_msc

// ===== V50 software-managed state facade =====

#include <cmath>
#include <cstdio>
#include <iomanip>
#include <locale>
#include <mutex>
#include <set>
#include <sstream>
#include <stdexcept>

namespace {
constexpr size_t LIMIT = 256ULL * 1024 * 1024;
void Need(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}
void Put64(std::string& b, uint64_t n) {
    for (int i=0;i<8;++i) b.push_back(char(n>>(i*8)));
}
void PutText(std::string& b, const std::string& s) {
    Put64(b,s.size());b+=s;
}
uint64_t Hash(const std::string& s) {
    uint64_t h=14695981039346656037ULL;
    for(unsigned char c:s){h^=c;h*=1099511628211ULL;}return h;
}
struct Reader {
    const std::string& b;size_t at;
    uint64_t U() {
        Need(at<=b.size()&&b.size()-at>=8,"truncated local state");
        uint64_t n=0;for(int i=0;i<8;++i)n|=uint64_t((unsigned char)b[at++])<<(i*8);return n;
    }
    std::string Text() {
        auto n=U();Need(n<=LIMIT&&at<=b.size()&&n<=b.size()-at,"invalid local state length");
        auto s=b.substr(at,size_t(n));at+=size_t(n);return s;
    }
};
std::string ConfigKey(const ModalSelfCalConfig& c) {
    std::ostringstream o;o.imbue(std::locale::classic());o<<std::setprecision(17);
    o<<c.tz_offset_h<<','<<c.ref_start_h<<','<<c.ref_end_h<<','<<c.learn_end_h<<','
     <<c.apply_end_h<<','<<c.ramp_min<<','<<c.cadence_s<<','<<c.K<<','<<c.guard<<','
     <<c.spread_k<<','<<c.history_nights<<','<<c.min_valid_ratio<<','<<c.min_learn_ratio<<','
     <<c.min_ref_frames<<','<<c.min_valid<<','<<c.max_frame_residual<<','<<c.max_frame_dev<<','<<c.enabled;
    for(const auto& p:c.fit_only_prefixes){o<<':'<<p.size()<<':'<<p;}return o.str();
}
struct Decoded {
    uint64_t revision=0;int64_t timestamp=0;
    std::string device,config,x,y;std::vector<std::string> names;
};
const std::string MAGIC="MSC_STATE_V50R\n";
Decoded Decode(const std::string& bytes) {
    Need(bytes.size()<=LIMIT&&bytes.size()>=MAGIC.size()+48&&bytes.compare(0,MAGIC.size(),MAGIC)==0,
         "invalid local V50 state format");
    Reader checksum{bytes,bytes.size()-8};Need(checksum.U()==Hash(bytes.substr(0,bytes.size()-8)),"local state checksum mismatch");
    Reader r{bytes,MAGIC.size()};Decoded d;
    d.revision=r.U();d.timestamp=int64_t(r.U());d.device=r.Text();d.config=r.Text();
    auto count=r.U();Need(count>0&&count<=10000,"invalid saved point count");
    for(uint64_t i=0;i<count;++i)d.names.push_back(r.Text());
    d.x=r.Text();d.y=r.Text();
    Need(r.at+8==bytes.size()&&d.timestamp>0,"invalid local state tail");return d;
}
int HistoryCount(const std::string& state) {
    auto p=state.find("\nhist_n=");Need(p!=std::string::npos,"history count missing");
    return std::stoi(state.substr(p+8));
}
const char* ApplyReason(const ModalSelfCalFrameInfo& info) {
    if (info.n_corrected > 0 && info.gate > 0.0) return "APPLIED";
    if (info.state == "BASELINE") return "COLLECT_BASELINE";
    if (info.state == "PASSTHROUGH" && info.gate <= 0.0) return "OUTSIDE_APPLY_WINDOW";
    if (!info.baseline_frozen) return "BASELINE_NOT_READY";
    if (!info.modes_ready) return "MODES_NOT_READY";
    if (info.state == "DEGRADED_FRAME") return "INSUFFICIENT_VALID_POINTS";
    if (info.gate <= 0.0) return "ZERO_GATE";
    return "NO_CORRECTABLE_POINTS";
}
} // namespace


// ===========================================================================
// 方案 D (V54): X 向预处理与夜间温和物理增强模块 (含完整快照序列化能力)
// ===========================================================================

namespace gzmetro_msc {
namespace {

const double kMscNaN_V54 = std::numeric_limits<double>::quiet_NaN();

class CausalMedianFilterBank {
public:
    void Init(const std::vector<std::string>& names) {
        names_ = names;
        buffers_.assign(names.size(), PointBuffer{});
    }

    void Reset() {
        for (auto& b : buffers_) {
            b.count = 0;
            b.buf[0] = b.buf[1] = b.buf[2] = 0.0;
        }
    }

    std::vector<double> Filter(int64_t ts_ms, const std::vector<double>& raw_x) {
        if (raw_x.size() != buffers_.size()) {
            return raw_x;
        }
        std::vector<double> clean_x(raw_x.size());
        for (size_t i = 0; i < raw_x.size(); ++i) {
            double v = raw_x[i];
            auto& b = buffers_[i];
            if (!std::isfinite(v)) {
                b.count = 0;
                clean_x[i] = kMscNaN_V54;
                continue;
            }
            if (b.count == 0) {
                b.buf[0] = v;
                b.count = 1;
                clean_x[i] = v;
            } else if (b.count == 1) {
                b.buf[1] = v;
                b.count = 2;
                clean_x[i] = 0.5 * (b.buf[0] + b.buf[1]);
            } else if (b.count == 2) {
                b.buf[2] = v;
                b.count = 3;
                clean_x[i] = Median3(b.buf[0], b.buf[1], b.buf[2]);
            } else {
                b.buf[0] = b.buf[1];
                b.buf[1] = b.buf[2];
                b.buf[2] = v;
                clean_x[i] = Median3(b.buf[0], b.buf[1], b.buf[2]);
            }
        }
        return clean_x;
    }

    std::string Serialize() const {
        std::ostringstream os;
        os.imbue(std::locale::classic());
        os << std::setprecision(17);
        for (size_t i = 0; i < buffers_.size(); ++i) {
            if (i > 0) os << ';';
            os << buffers_[i].count << ',' << buffers_[i].buf[0] << ','
               << buffers_[i].buf[1] << ',' << buffers_[i].buf[2];
        }
        return os.str();
    }

    void Deserialize(const std::string& line) {
        std::istringstream is(line);
        is.imbue(std::locale::classic());
        std::string token;
        size_t idx = 0;
        while (std::getline(is, token, ';') && idx < buffers_.size()) {
            std::istringstream ts(token);
            ts.imbue(std::locale::classic());
            int c = 0;
            char comma;
            double b0 = 0, b1 = 0, b2 = 0;
            if (ts >> c >> comma >> b0 >> comma >> b1 >> comma >> b2) {
                buffers_[idx].count = c;
                buffers_[idx].buf[0] = b0;
                buffers_[idx].buf[1] = b1;
                buffers_[idx].buf[2] = b2;
            }
            ++idx;
        }
    }

private:
    struct PointBuffer {
        double buf[3] = {0.0, 0.0, 0.0};
        int count = 0;
    };
    static double Median3(double a, double b, double c) {
        return (std::max)((std::min)(a, b), (std::min)((std::max)(a, b), c));
    }
    std::vector<std::string> names_;
    std::vector<PointBuffer> buffers_;
};

class MountThermalDamping {
public:
    void Init(const std::vector<std::string>& names) {
        names_ = names;
        Reset();
    }

    void Reset() {
        current_night_id_ = -1;
        in_night_shift_ = false;
        baseline_frames_.clear();
        baseline_reference_.assign(names_.size(), kMscNaN_V54);
        baseline_ready_ = false;
        rolling_drift_.clear();
    }

    void NotifyDaytime() {
        in_night_shift_ = false;
    }

    void Apply(int64_t ts_ms, double gate, int64_t night_id, double shrinkage, std::vector<double>* x_vec) {
        if (!x_vec || x_vec->size() != names_.size()) return;

        if (gate < 1.0) {
            in_night_shift_ = false;
            return;
        }

        if (!in_night_shift_ || night_id != current_night_id_) {
            current_night_id_ = night_id;
            in_night_shift_ = true;
            baseline_frames_.clear();
            baseline_reference_.assign(names_.size(), kMscNaN_V54);
            baseline_ready_ = false;
            rolling_drift_.clear();
        }

        if (!baseline_ready_) {
            baseline_frames_.push_back(*x_vec);
            if (baseline_frames_.size() >= 30) {
                for (size_t j = 0; j < names_.size(); ++j) {
                    std::vector<double> vals;
                    vals.reserve(baseline_frames_.size());
                    for (const auto& fr : baseline_frames_) {
                        if (std::isfinite(fr[j])) vals.push_back(fr[j]);
                    }
                    if (vals.size() >= 10) {
                        std::sort(vals.begin(), vals.end());
                        baseline_reference_[j] = vals[vals.size() / 2];
                    }
                }
                baseline_ready_ = true;
            }
            return;
        }

        std::vector<double> devs;
        devs.reserve(names_.size());
        for (size_t j = 0; j < names_.size(); ++j) {
            double v = (*x_vec)[j];
            double b = baseline_reference_[j];
            if (std::isfinite(v) && std::isfinite(b)) {
                devs.push_back(v - b);
            }
        }

        if (devs.empty()) return;

        std::sort(devs.begin(), devs.end());
        double common_drift = devs[devs.size() / 2];

        rolling_drift_.push_back(common_drift);
        if (rolling_drift_.size() > 15) {
            rolling_drift_.erase(rolling_drift_.begin());
        }

        std::vector<double> sorted_window = rolling_drift_;
        std::sort(sorted_window.begin(), sorted_window.end());
        double smoothed_drift = sorted_window[sorted_window.size() / 2];

        for (size_t j = 0; j < names_.size(); ++j) {
            double& val = (*x_vec)[j];
            if (std::isfinite(val)) {
                val -= shrinkage * smoothed_drift;
            }
        }
    }

    std::string Serialize() const {
        std::ostringstream os;
        os.imbue(std::locale::classic());
        os << std::setprecision(17);
        os << current_night_id_ << '|' << (in_night_shift_ ? 1 : 0) << '|'
           << (baseline_ready_ ? 1 : 0) << '|';
        for (size_t i = 0; i < baseline_reference_.size(); ++i) {
            if (i > 0) os << ',';
            if (std::isfinite(baseline_reference_[i])) os << baseline_reference_[i];
            else os << "nan";
        }
        os << '|';
        for (size_t i = 0; i < rolling_drift_.size(); ++i) {
            if (i > 0) os << ',';
            os << rolling_drift_[i];
        }
        return os.str();
    }

    void Deserialize(const std::string& line) {
        std::istringstream is(line);
        is.imbue(std::locale::classic());
        std::string part;
        // part 1: current_night_id_
        if (std::getline(is, part, '|')) current_night_id_ = std::stoll(part);
        // part 2: in_night_shift_
        if (std::getline(is, part, '|')) in_night_shift_ = (part == "1");
        // part 3: baseline_ready_
        if (std::getline(is, part, '|')) baseline_ready_ = (part == "1");
        // part 4: baseline_reference_
        if (std::getline(is, part, '|')) {
            std::istringstream ts(part);
            ts.imbue(std::locale::classic());
            std::string val_str;
            size_t idx = 0;
            while (std::getline(ts, val_str, ',') && idx < baseline_reference_.size()) {
                if (val_str == "nan" || val_str.empty()) baseline_reference_[idx] = kMscNaN_V54;
                else baseline_reference_[idx] = std::stod(val_str);
                ++idx;
            }
        }
        // part 5: rolling_drift_
        rolling_drift_.clear();
        if (std::getline(is, part, '|')) {
            std::istringstream ts(part);
            ts.imbue(std::locale::classic());
            std::string val_str;
            while (std::getline(ts, val_str, ',')) {
                if (!val_str.empty() && val_str != "nan") {
                    rolling_drift_.push_back(std::stod(val_str));
                }
            }
        }
    }

private:
    std::vector<std::string> names_;
    int64_t current_night_id_ = -1;
    bool in_night_shift_ = false;
    std::vector<std::vector<double>> baseline_frames_;
    std::vector<double> baseline_reference_;
    bool baseline_ready_ = false;
    std::vector<double> rolling_drift_;
};

class MildVelocityDamping {
public:
    void Init(const std::vector<std::string>& names) {
        names_ = names;
        states_.assign(names.size(), MarkerState{});
    }

    void Reset() {
        for (auto& st : states_) {
            st.s = kMscNaN_V54;
            st.last_ts = -1;
        }
    }

    void NotifyDaytime(int64_t ts_ms, const std::vector<double>& x_vec) {
        for (size_t j = 0; j < states_.size() && j < x_vec.size(); ++j) {
            states_[j].s = x_vec[j];
            states_[j].last_ts = ts_ms;
        }
    }

    void Apply(int64_t ts_ms, double gate, double tau_min, std::vector<double>* x_vec) {
        if (!x_vec || x_vec->size() != states_.size()) return;

        for (size_t j = 0; j < x_vec->size(); ++j) {
            double x = (*x_vec)[j];
            auto& st = states_[j];

            if (!std::isfinite(x)) {
                st.s = kMscNaN_V54;
                st.last_ts = ts_ms;
                continue;
            }

            if (gate < 1.0) {
                st.s = x;
                st.last_ts = ts_ms;
                continue;
            }

            if (!std::isfinite(st.s) || st.last_ts < 0 || (ts_ms - st.last_ts > 180000) || (ts_ms < st.last_ts)) {
                st.s = x;
                st.last_ts = ts_ms;
                continue;
            }

            double dt_min = static_cast<double>(ts_ms - st.last_ts) / 60000.0;
            double alpha = 1.0 - std::exp(-dt_min / tau_min);
            st.s = st.s + alpha * (x - st.s);
            st.last_ts = ts_ms;
            (*x_vec)[j] = st.s;
        }
    }

    std::string Serialize() const {
        std::ostringstream os;
        os.imbue(std::locale::classic());
        os << std::setprecision(17);
        for (size_t i = 0; i < states_.size(); ++i) {
            if (i > 0) os << ';';
            if (std::isfinite(states_[i].s)) os << states_[i].s;
            else os << "nan";
            os << ',' << states_[i].last_ts;
        }
        return os.str();
    }

    void Deserialize(const std::string& line) {
        std::istringstream is(line);
        is.imbue(std::locale::classic());
        std::string token;
        size_t idx = 0;
        while (std::getline(is, token, ';') && idx < states_.size()) {
            std::istringstream ts(token);
            ts.imbue(std::locale::classic());
            std::string s_val;
            int64_t last_t = -1;
            if (std::getline(ts, s_val, ',') && (ts >> last_t)) {
                states_[idx].last_ts = last_t;
                if (s_val == "nan" || s_val.empty()) states_[idx].s = kMscNaN_V54;
                else states_[idx].s = std::stod(s_val);
            }
            ++idx;
        }
    }

private:
    struct MarkerState {
        double s = kMscNaN_V54;
        int64_t last_ts = -1;
    };
    std::vector<std::string> names_;
    std::vector<MarkerState> states_;
};

} // namespace

struct ModalSelfCalState::Impl {
    ModalSelfCalConfig config;
    std::string device;
    std::vector<std::string> names;
    std::unique_ptr<ModalSelfCalAxis> x, y;
    CausalMedianFilterBank x_filter_bank;
    MountThermalDamping mount_damping;
    MildVelocityDamping velocity_damping;
    mutable std::mutex calls;
    bool initialized = false, valid = false, processed = false, processing_ready = false;
    uint64_t revision = 0;

    explicit Impl(const ModalSelfCalConfig& c) : config(c) {}

    std::string Snapshot() const {
        std::string a, b;
        Need(x->SaveState(&a) && y->SaveState(&b), "axis serialization failed");
        Need(x->last_ts() == y->last_ts() && x->last_ts() > 0, "no valid paired processed state");

        // 方案 D (V54): 将温漂自校基准、滑动窗口、阻尼状态与 W=3 缓存追加至快照
        std::ostringstream os_d;
        os_d.imbue(std::locale::classic());
        os_d << "\n# SCHEME_D_V54\n";
        os_d << "w3=" << x_filter_bank.Serialize() << "\n";
        os_d << "mount=" << mount_damping.Serialize() << "\n";
        os_d << "vel=" << velocity_damping.Serialize() << "\n";
        os_d << "# SCHEME_D_END\n";
        a += os_d.str();

        std::string bytes = MAGIC;
        Put64(bytes, revision);
        Put64(bytes, uint64_t(x->last_ts()));
        PutText(bytes, device);
        PutText(bytes, ConfigKey(config));
        Put64(bytes, names.size());
        for (const auto& n : names) PutText(bytes, n);
        PutText(bytes, a);
        PutText(bytes, b);
        Put64(bytes, Hash(bytes));
        Need(bytes.size() <= LIMIT, "state exceeds size limit");
        return bytes;
    }
};

ModalSelfCalState::ModalSelfCalState(const ModalSelfCalConfig& c) : impl_(new Impl(c)) {}
ModalSelfCalState::~ModalSelfCalState() = default;

bool ModalSelfCalState::Init(const std::string& device, const std::vector<std::string>& names,
                             std::string* error, bool allow_new_stream) {
    if (error) error->clear();
    auto& p = *impl_;
    std::lock_guard<std::mutex> lock(p.calls);
    try {
        Need(!p.initialized, "already initialized; Destroy before recreating");
        gzmetro_msc::SetModalSelfCalLogEnabled(false);
        Need(!device.empty() && device.size() <= 1024, "device ID required");
        Need(!names.empty() && names.size() <= 10000 &&
             std::set<std::string>(names.begin(), names.end()).size() == names.size(),
             "empty/duplicate marker list");
        for (const auto& n : names) {
            Need(!n.empty() && n.find_first_of(",\r\n") == std::string::npos, "invalid marker name");
        }
        const auto& c = p.config;
        for (double v : {c.tz_offset_h, c.ref_start_h, c.ref_end_h, c.learn_end_h, c.apply_end_h,
                         c.ramp_min, c.cadence_s, c.guard, c.spread_k, c.min_valid_ratio,
                         c.min_learn_ratio, c.max_frame_residual, c.max_frame_dev}) {
            Need(std::isfinite(v), "nonfinite math config");
        }
        Need(c.enabled && c.K >= 1 && c.K <= 3 && c.history_nights >= 1 && c.history_nights <= 1000 &&
             c.min_ref_frames >= 1 && c.min_valid >= 1 && c.cadence_s > 0 && c.ramp_min >= 0 &&
             std::abs(c.tz_offset_h) <= 24 && c.ref_start_h >= 12 && c.ref_start_h < c.ref_end_h &&
             c.ref_end_h < c.learn_end_h && c.learn_end_h <= c.apply_end_h && c.apply_end_h <= 36 &&
             c.min_valid_ratio >= 0 && c.min_valid_ratio <= 1 && c.min_learn_ratio >= 0 &&
             c.min_learn_ratio <= 1, "invalid/enabled=false math config");

        auto x = std::make_unique<ModalSelfCalAxis>(p.config);
        auto y = std::make_unique<ModalSelfCalAxis>(p.config);
        x->Bind(names);
        y->Bind(names);
        p.x = std::move(x);
        p.y = std::move(y);

        p.x_filter_bank.Init(names);
        p.mount_damping.Init(names);
        p.velocity_damping.Init(names);

        p.device = device;
        p.names = names;
        p.initialized = true;
        p.valid = true;
        p.processed = false;
        p.processing_ready = allow_new_stream;
        p.revision = 0;

        std::fprintf(stderr, "[MSC] dev=%s Init=OK points=%zu new_stream=%d state=EMPTY applied=0/0 reason=%s\n",
                     device.c_str(), names.size(), int(allow_new_stream),
                     allow_new_stream ? "WAIT_LIVE_FRAME" : "WAIT_STATE_IMPORT");
        return true;
    } catch (const std::exception& e) {
        if (error) *error = e.what();
        std::fprintf(stderr, "[MSC] dev=%s Init=FAILED error=%s\n", device.c_str(), e.what());
        return false;
    }
}

bool ModalSelfCalState::ImportState(const std::string& bytes, ModalSelfCalResumeInfo* resume,
                                   std::string* error) {
    if (error) error->clear();
    if (resume) *resume = ModalSelfCalResumeInfo();
    auto& p = *impl_;
    std::lock_guard<std::mutex> lock(p.calls);
    try {
        Need(p.initialized && p.valid && resume != nullptr && !p.processed,
             "Import only after valid Init, before processing");
        auto d = Decode(bytes);
        Need(d.device == p.device, "saved device differs");
        Need(d.config == ConfigKey(p.config), "saved math parameters differ");
        Need(d.names.size() == p.names.size() &&
             std::set<std::string>(d.names.begin(), d.names.end()) ==
             std::set<std::string>(p.names.begin(), p.names.end()),
             "saved marker set differs");

        auto nx = std::make_unique<ModalSelfCalAxis>(p.config);
        auto ny = std::make_unique<ModalSelfCalAxis>(p.config);
        std::string e;
        Need(nx->LoadState(d.x, &e), e);
        Need(ny->LoadState(d.y, &e), e);
        Need(nx->names() == d.names && ny->names() == d.names, "saved axis roster differs from snapshot header");
        Need(nx->last_ts() == d.timestamp && ny->last_ts() == d.timestamp, "saved axis timestamp mismatch");

        nx->Bind(p.names);
        ny->Bind(p.names);

        // 方案 D (V54): 若快照包含 Scheme D 状态，直接恢复温漂基准、滑动窗口与阻尼
        size_t pos_d = d.x.find("\n# SCHEME_D_V54\n");
        if (pos_d != std::string::npos) {
            std::istringstream is_d(d.x.substr(pos_d));
            std::string d_line;
            while (std::getline(is_d, d_line)) {
                if (d_line.rfind("w3=", 0) == 0) {
                    p.x_filter_bank.Deserialize(d_line.substr(3));
                } else if (d_line.rfind("mount=", 0) == 0) {
                    p.mount_damping.Deserialize(d_line.substr(6));
                } else if (d_line.rfind("vel=", 0) == 0) {
                    p.velocity_damping.Deserialize(d_line.substr(4));
                }
            }
        }

        auto flag = [](const std::string& text, const std::string& key) {
            return text.find("\n" + key + "=1\n") != std::string::npos;
        };

        ModalSelfCalResumeInfo r;
        r.last_timestamp_ms = d.timestamp;
        r.history_x = HistoryCount(d.x);
        r.history_y = HistoryCount(d.y);
        r.baseline_x = flag(d.x, "frozen");
        r.baseline_y = flag(d.y, "frozen");
        r.modes_x = flag(d.x, "modes_has");
        r.modes_y = flag(d.y, "modes_has");

        p.x = std::move(nx);
        p.y = std::move(ny);
        p.valid = true;
        p.processing_ready = true;
        p.revision = d.revision;
        *resume = r;

        std::fprintf(stderr, "[MSC] dev=%s Import=OK resume=%lld hist=%d/%d frozen=%d/%d ready=%d/%d applied=0/0 reason=WAIT_LIVE_FRAME\n",
                     p.device.c_str(), (long long)r.last_timestamp_ms, r.history_x, r.history_y,
                     int(r.baseline_x), int(r.baseline_y), int(r.modes_x), int(r.modes_y));
        return true;
    } catch (const std::exception& e) {
        if (error) *error = e.what();
        std::fprintf(stderr, "[MSC] dev=%s Import=FAILED error=%s\n", p.device.c_str(), e.what());
        return false;
    }
}

bool ModalSelfCalState::Process(int64_t ts, const std::vector<double>& x, const std::vector<double>& y,
                               ModalSelfCalResult* result, std::string* error, bool replay) {
    if (error) error->clear();
    if (result) *result = ModalSelfCalResult();
    auto& p = *impl_;
    std::lock_guard<std::mutex> lock(p.calls);
    bool advancing = false;
    try {
        Need(p.initialized && p.valid && result != nullptr, "not initialized/valid or null result");
        Need(p.processing_ready, "state not imported; explicit new-stream permission required for cold warmup");
        Need(ts > 0, "timestamp must be positive Unix milliseconds");
        if (ts <= p.x->last_ts() || ts <= p.y->last_ts()) {
            result->duplicate = true;
            result->replayed = replay;
            std::fprintf(stderr, "[MSC] dev=%s Process=SKIP_OLD_TS ts=%lld applied=0/0 reason=DUPLICATE_OR_OLD_TS publish=0\n",
                         p.device.c_str(), (long long)ts);
            return true;
        }
        Need(x.size() == p.names.size() && y.size() == p.names.size(), "input vector length differs");
        for (const auto* v : {&x, &y}) {
            for (double a : *v) {
                Need(!std::isinf(a), "infinite input; invalid point must be NaN");
            }
        }
        Need(p.revision < std::numeric_limits<uint64_t>::max(), "state revision exhausted");

        // 方案 D (V54) Step 1: X 向输入端 W=3 因果中值滤波 (Y 向 100% 透传)
        std::vector<double> fed_x = x;
        if (p.config.enable_x_w3_filter) {
            fed_x = p.x_filter_bank.Filter(ts, x);
        }

        ModalSelfCalResult r;
        advancing = true;
        try {
            r.x = p.x->Ingest(ts, fed_x);
            r.y = p.y->Ingest(ts, y);
        } catch (...) {
            p.valid = false;
            throw;
        }

        if (p.x->last_ts() != ts || p.y->last_ts() != ts) {
            p.valid = false;
            throw std::runtime_error("core did not accept paired frame");
        }
        p.processed = true;
        ++p.revision;
        r.info_x = p.x->last_info();
        r.info_y = p.y->last_info();

        // 方案 D (V54) Step 2: X 向夜间温和物理增强 (S2 支架温漂自校 + S1 弱阻尼)
        // 白天 (gate < 1.0) 100% 透传，仅在夜间施工窗口对 X 生效
        if (p.config.enabled && r.info_x.gate >= 1.0) {
            if (p.config.enable_x_mount_drift_damping) {
                p.mount_damping.Apply(ts, r.info_x.gate, r.info_x.night_id,
                                      p.config.mount_drift_shrinkage, &r.x);
            }
            if (p.config.enable_x_velocity_damping) {
                p.velocity_damping.Apply(ts, r.info_x.gate,
                                         p.config.velocity_damping_tau_min, &r.x);
            }
        } else {
            p.mount_damping.NotifyDaytime();
            p.velocity_damping.NotifyDaytime(ts, r.x);
        }

        double maxc = 0;
        for (size_t i = 0; i < x.size(); ++i) {
            double a = x[i] - r.x[i];
            double b = y[i] - r.y[i];
            r.correction_x.push_back(a);
            r.correction_y.push_back(b);
            if (std::isfinite(a)) maxc = (std::max)(maxc, std::abs(a));
            if (std::isfinite(b)) maxc = (std::max)(maxc, std::abs(b));
        }
        r.replayed = replay;
        r.output_ready = !replay;

        std::fprintf(stderr,
                     "[MSC] dev=%s Process=%s ts=%lld applied=%d/%d reason=%s/%s state=%s/%s "
                     "baseline=%d/%d modes=%d/%d hist=%d/%d valid=%d/%d corrected=%d/%d gate=%.2f/%.2f maxcorr=%.6g publish=%d save=SOFTWARE\n",
                     p.device.c_str(), replay ? "REPLAY" : "LIVE", (long long)ts,
                     int(r.info_x.n_corrected > 0 && r.info_x.gate > 0.0),
                     int(r.info_y.n_corrected > 0 && r.info_y.gate > 0.0),
                     ApplyReason(r.info_x), ApplyReason(r.info_y),
                     r.info_x.state.c_str(), r.info_y.state.c_str(),
                     int(r.info_x.baseline_frozen), int(r.info_y.baseline_frozen),
                     int(r.info_x.modes_ready), int(r.info_y.modes_ready),
                     r.info_x.n_history, r.info_y.n_history,
                     r.info_x.n_frame_learn_valid, r.info_y.n_frame_learn_valid,
                     r.info_x.n_corrected, r.info_y.n_corrected,
                     r.info_x.gate, r.info_y.gate, maxc, int(r.output_ready));

        if (replay) {
            r.x.clear();
            r.y.clear();
            r.correction_x.clear();
            r.correction_y.clear();
        }
        *result = std::move(r);
        return true;
    } catch (const std::exception& e) {
        if (advancing) p.valid = false;
        if (error) *error = e.what();
        std::fprintf(stderr, "[MSC] dev=%s Process=FAILED ts=%lld applied=0/0 reason=PROCESS_FAILED valid=%d publish=0 error=%s\n",
                     p.device.c_str(), (long long)ts, int(p.valid), e.what());
        return false;
    }
}

bool ModalSelfCalState::ExportState(std::string* bytes, int64_t* timestamp, std::string* error) const {
    if (error) error->clear();
    if (bytes) bytes->clear();
    if (timestamp) *timestamp = 0;
    auto& p = *impl_;
    std::lock_guard<std::mutex> lock(p.calls);
    try {
        Need(p.initialized && p.valid && bytes != nullptr && timestamp != nullptr,
             "not initialized/valid or null output");
        auto snapshot = p.Snapshot();
        const auto ts = p.x->last_ts();
        *bytes = std::move(snapshot);
        *timestamp = ts;
        std::fprintf(stderr, "[MSC] dev=%s Export=OK ts=%lld mem_rev=%llu bytes=%zu save=SOFTWARE\n",
                     p.device.c_str(), (long long)ts, (unsigned long long)p.revision, bytes->size());
        return true;
    } catch (const std::exception& e) {
        if (error) *error = e.what();
        std::fprintf(stderr, "[MSC] dev=%s Export=FAILED error=%s\n", p.device.c_str(), e.what());
        return false;
    }
}

bool ModalSelfCalState::GetResumeTs(int64_t* timestamp, std::string* error) const {
    if (error) error->clear();
    if (timestamp) *timestamp = 0;
    auto& p = *impl_;
    std::lock_guard<std::mutex> lock(p.calls);
    try {
        Need(p.initialized && p.valid && timestamp != nullptr, "not initialized/valid or null output");
        Need(p.x->last_ts() == p.y->last_ts(), "axis timestamps differ");
        *timestamp = p.x->last_ts();
        std::fprintf(stderr, "[MSC] dev=%s Resume=OK ts=%lld\n", p.device.c_str(), (long long)*timestamp);
        return true;
    } catch (const std::exception& e) {
        if (error) *error = e.what();
        std::fprintf(stderr, "[MSC] dev=%s Resume=FAILED error=%s\n", p.device.c_str(), e.what());
        return false;
    }
}

void ModalSelfCalState::Destroy() {
    auto& p = *impl_;
    std::lock_guard<std::mutex> lock(p.calls);
    p.x.reset();
    p.y.reset();
    p.x_filter_bank.Reset();
    p.mount_damping.Reset();
    p.velocity_damping.Reset();
    p.initialized = false;
    p.valid = false;
    p.processed = false;
    p.processing_ready = false;
    p.revision = 0;
}

// ===========================================================================
// 全局函数接口实现
// ===========================================================================
namespace {
struct MscGlobalRegistry {
    std::mutex mu;
    ModalSelfCalConfig cfg;
    std::map<std::string, std::unique_ptr<ModalSelfCalState>> instances;
    std::map<std::string, std::vector<std::string>> device_names;
    bool enabled = true;
};
MscGlobalRegistry& MscGlobal() {
    static MscGlobalRegistry reg;
    return reg;
}
} // namespace

bool InitModalSelfCal(const std::string& device_id, const std::vector<std::string>& names, std::string* err) {
    auto& reg = MscGlobal();
    std::lock_guard<std::mutex> lk(reg.mu);
    auto& inst = reg.instances[device_id];
    if (!inst) {
        inst = std::make_unique<ModalSelfCalState>(reg.cfg);
    } else {
        inst->Destroy();
    }
    reg.device_names[device_id] = names;
    return inst->Init(device_id, names, err, /*allow_new_stream=*/true);
}

bool ApplyModalSelfCal(const std::string& device_id, int64_t ts_ms,
                       const std::vector<double>& x, const std::vector<double>& y,
                       std::vector<double>* x_out, std::vector<double>* y_out,
                       const std::vector<std::string>* names) {
    if (x_out) *x_out = x;
    if (y_out) *y_out = y;
    if (!x_out || !y_out) return false;

    auto& reg = MscGlobal();
    std::lock_guard<std::mutex> lk(reg.mu);
    auto it = reg.instances.find(device_id);
    if (it == reg.instances.end() || !it->second) {
        if (names && !names->empty()) {
            auto& inst = reg.instances[device_id];
            inst = std::make_unique<ModalSelfCalState>(reg.cfg);
            if (!inst->Init(device_id, *names, nullptr, true)) return false;
            reg.device_names[device_id] = *names;
            it = reg.instances.find(device_id);
        } else {
            return false;
        }
    }

    ModalSelfCalResult res;
    std::string err;
    if (!it->second->Process(ts_ms, x, y, &res, &err)) {
        return false;
    }
    if (res.output_ready) {
        *x_out = res.x;
        *y_out = res.y;
    }
    return true;
}

bool GetLastModalSelfCalInfo(const std::string& device_id, int axis, ModalSelfCalFrameInfo* out) {
    if (!out) return false;
    return true;
}

bool ResetModalSelfCal(const std::string& device_id) {
    auto& reg = MscGlobal();
    std::lock_guard<std::mutex> lk(reg.mu);
    if (device_id.empty()) {
        for (auto& kv : reg.instances) {
            if (kv.second) kv.second->Destroy();
        }
        reg.instances.clear();
        reg.device_names.clear();
        return true;
    }
    auto it = reg.instances.find(device_id);
    if (it == reg.instances.end() || !it->second) return false;
    it->second->Destroy();
    reg.instances.erase(it);
    reg.device_names.erase(device_id);
    return true;
}

bool SaveModalSelfCalState(const std::string& device_id, std::string* blob) {
    if (!blob) return false;
    auto& reg = MscGlobal();
    std::lock_guard<std::mutex> lk(reg.mu);
    auto it = reg.instances.find(device_id);
    if (it == reg.instances.end() || !it->second) return false;
    int64_t ts = 0;
    return it->second->ExportState(blob, &ts);
}

bool LoadModalSelfCalState(const std::string& device_id, const std::string& blob, std::string* err) {
    auto& reg = MscGlobal();
    std::lock_guard<std::mutex> lk(reg.mu);
    auto it = reg.instances.find(device_id);
    if (it == reg.instances.end() || !it->second) {
        if (err) *err = "device not initialized";
        return false;
    }
    ModalSelfCalResumeInfo resume;
    return it->second->ImportState(blob, &resume, err);
}

bool GetModalSelfCalResumeTs(const std::string& device_id, int64_t* ts_ms) {
    if (!ts_ms) return false;
    auto& reg = MscGlobal();
    std::lock_guard<std::mutex> lk(reg.mu);
    auto it = reg.instances.find(device_id);
    if (it == reg.instances.end() || !it->second) return false;
    return it->second->GetResumeTs(ts_ms);
}

void SetModalSelfCalConfig(const ModalSelfCalConfig& config) {
    auto& reg = MscGlobal();
    std::lock_guard<std::mutex> lk(reg.mu);
    reg.cfg = config;
}

ModalSelfCalConfig GetModalSelfCalConfig() {
    auto& reg = MscGlobal();
    std::lock_guard<std::mutex> lk(reg.mu);
    return reg.cfg;
}

void SetModalSelfCalEnabled(bool enabled) {
    auto& reg = MscGlobal();
    std::lock_guard<std::mutex> lk(reg.mu);
    reg.enabled = enabled;
    reg.cfg.enabled = enabled;
}

} // namespace gzmetro_msc
