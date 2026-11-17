"""Decompose two worst added adjacent-jump cases from frozen shadow outputs."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import struct
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent
REPORTS = ROOT / "reports"
TZ = timezone(timedelta(hours=8))


def local_text(ts):
    return datetime.fromtimestamp(int(ts) / 1000, TZ).isoformat()


def main():
    report = json.loads((REPORTS / "reference_guard_field_audit.json").read_text(encoding="utf-8"))
    cases = []
    for row in report["largest_new_jumps"][:2]:
        line, dev = row["line"], row["device"]
        with np.load(BASE / "data" / line / dev / "input.npz") as z:
            ts, names, x, y = z["timestamp"], z["names"], z["x"], z["y"]
        j = list(names).index(row["marker"])
        frozen = BASE / "round2_waveform_10n/results/current_fade07" / line / dev / "output.bin"
        with frozen.open("rb") as f:
            m, n = struct.unpack("<II", f.read(8))
        native = np.memmap(frozen, dtype=np.dtype([("timestamp", "<i8"), ("xy", "<f8", (2, m))]),
                           offset=8, mode="r", shape=(n,))
        assert np.array_equal(ts, native["timestamp"])
        b = native["xy"][:, 0, j]
        with np.load(REPORTS / f"reference_guard_{line}_{dev}.npz") as z:
            assert np.array_equal(ts, z["timestamp"])
            shadow = z["shadow_x"][:, j]
            g, status, r, count = z["gain"], z["status"], z["activity_r"], z["valid_j_count"]
        start = int(datetime.fromisoformat(row["night"] + "T23:00").replace(tzinfo=TZ).timestamp() * 1000)
        window = (ts >= start) & (ts < start + 8 * 3_600_000)
        adjacent = window[1:] & window[:-1] & (np.diff(ts) <= 180_000)
        adjacent &= np.isfinite(shadow[1:]) & np.isfinite(shadow[:-1])
        size = np.where(adjacent, np.abs(np.diff(shadow)), -1)
        i = int(np.argmax(size)) + 1
        c0, c1 = float(x[i - 1, j] - b[i - 1]), float(x[i, j] - b[i])
        dr = float(x[i, j] - x[i - 1, j])
        correction_change_term = -float(g[i]) * (c1 - c0)
        gain_change_term = -c0 * float(g[i] - g[i - 1])
        dy = float(shadow[i] - shadow[i - 1])
        error = dy - dr - correction_change_term - gain_change_term
        assert abs(error) < 1e-9
        valid_indices = np.flatnonzero(window & np.isfinite(shadow))
        min_i = int(valid_indices[np.argmin(shadow[valid_indices])])
        max_i = int(valid_indices[np.argmax(shadow[valid_indices])])
        def frame(k):
            return {"timestamp": int(ts[k]), "local_time": local_text(ts[k]),
                    "raw_x": float(x[k, j]), "base_x": float(b[k]), "shadow_x": float(shadow[k]),
                    "gain": float(g[k]), "activity_r": float(r[k]) if np.isfinite(r[k]) else None,
                    "valid_j_count": int(count[k]), "status": str(status[k])}
        cases.append({"case_id": row["case_id"], "night_stats": {k: row[k] for k in ("raw", "base", "shadow")},
                      "max_shadow_jump": {"previous": frame(i - 1), "current": frame(i),
                          "delta_raw": dr, "delta_base": float(b[i] - b[i - 1]),
                          "previous_total_compensation": c0, "current_total_compensation": c1,
                          "minus_current_gain_times_delta_compensation": correction_change_term,
                          "minus_previous_compensation_times_delta_gain": gain_change_term,
                          "delta_shadow": dy, "decomposition_error": error},
                      "shadow_min_frame": frame(min_i), "shadow_max_frame": frame(max_i)})
    result = {"scope": "两项最大新增相邻变化；冻结raw/native/shadow数值代数分解，无新native回放",
              "identity": "delta_shadow = delta_raw - current_gain*delta_compensation - previous_compensation*delta_gain",
              "causality_boundary": "分解确定输出路由的数值贡献，不确定现场物理扰动原因；三个项不是独立物理成因",
              "cases": cases}
    path = REPORTS / "reference_guard_jump_audit.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
