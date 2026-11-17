"""Current-causal J-activity shadow gate, not a replacement correction solver.

Public API: apply_reference_activity_guard(timestamp_ms, names, raw_x, raw_y,
                                         base_x) -> dict

All coordinates are absolute pixels. raw_x/raw_y MUST already contain NaN for
invalid ROI observations; finite database coordinates do not establish validity.
base_x is the frozen current_fade07 final absolute X, on the exact same rows and
marker order. This module does not mutate inputs, core state, or Y. It is not a
physical-accuracy guarantee. In particular, a moving J can open a gate even when
the existing compensation has the wrong spatial shape, and changing gain can
create an output movement when raw and compensation themselves are constant.
"""

from collections import deque
from datetime import date, timedelta
import numpy as np


CONFIG = {
    "candidate": "reference_activity_shadow_v1",
    "timezone": "UTC+08:00",
    "reference_prefixes": ["YJ", "ZJ"],
    "exclude_name_contains": "XJ",
    "reference_window": "[22:00,23:00)",
    "publication_window": "[23:00,07:00)",
    "max_reference_device_frames": 60,
    "min_reference_samples_per_axis": 10,
    "min_current_valid_j": 3,
    "baseline": "per-axis median",
    "noise_scale": "per-axis P95 absolute deviation about median; linear quantile",
    "activity": "median across valid J of max(abs(dx)/qx95,abs(dy)/qy95)",
    "gain": "smoothstep(clip((activity-1)/2,0,1))",
    "near_zero_scale": "64*float64_eps*max(1,max_abs_baseline_samples); changed=>activity3, unchanged=>0",
    "reference_unavailable": "gain1; keep original candidate, not a safety guarantee",
    "outside_window": "gain0; publish raw X exactly",
    "invalid": "raw nonfinite or base nonfinite => NaN inside; raw nonfinite => NaN outside",
    "guard_applied": "inside window, reference available, gain<1",
    "causality": "current J observation plus same-night 22-23 past data only",
    "limitation": "reference activity is necessary evidence only; no waveform/physical-accuracy guarantee",
}


def _night_text(day_number):
    return (date(1970, 1, 1) + timedelta(days=int(day_number))).isoformat()


def _freeze_reference(frames, j_count):
    baseline = np.full((j_count, 2), np.nan, dtype=float)
    noise = np.full_like(baseline, np.nan)
    epsilon = np.full_like(baseline, np.nan)
    counts = np.zeros((j_count, 2), dtype=np.int64)
    if frames:
        values = np.stack(frames)
        for j in range(j_count):
            for axis in range(2):
                v = values[:, j, axis]
                v = v[np.isfinite(v)]
                counts[j, axis] = len(v)
                if len(v) < CONFIG["min_reference_samples_per_axis"]:
                    continue
                b = float(np.median(v))
                baseline[j, axis] = b
                noise[j, axis] = float(np.quantile(np.abs(v - b), 0.95))
                epsilon[j, axis] = 64 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(v))))
    return baseline, noise, epsilon, counts


def apply_reference_activity_guard(timestamp_ms, names, raw_x, raw_y, base_x):
    """Return shadow X and diagnostics without changing any supplied array.

    timestamp_ms: strictly increasing int64 Unix milliseconds, shape (N,).
    names: unique marker strings in the common column order, shape (M,).
    raw_x, raw_y, base_x: float arrays (N,M); invalid ROI already replaced by NaN.

    Returned arrays: x (N,M), gain/activity_r (N,), valid_j_count (N,),
    status (N,) strings, guard_applied (N,) bool. Additional keys: j_names,
    night_summaries (list of JSON-compatible dicts), config (dict).

    status is OUTSIDE_WINDOW, REFERENCE_UNAVAILABLE, REFERENCE_QUIET,
    REFERENCE_TRANSITION, or REFERENCE_ACTIVE. The latter means only activity
    evidence exists, not that the candidate correction is physically correct.
    Missing base coordinates are never promoted to valid output, even at g=0.
    No output_ready is synthesized: caller must retain upstream no-output mask.
    """
    ts_in = np.asarray(timestamp_ms)
    if ts_in.ndim != 1 or not np.issubdtype(ts_in.dtype, np.integer):
        raise ValueError("timestamp_ms must be a one-dimensional integer array")
    ts = ts_in.astype(np.int64, copy=False)
    if np.any(ts[1:] <= ts[:-1]):
        raise ValueError("timestamp_ms must be strictly increasing, without duplicate/replay rows")
    marker_names = np.asarray(names)
    if marker_names.ndim != 1:
        raise ValueError("names must be one-dimensional")
    marker_names = [str(n) for n in marker_names]
    if len(set(marker_names)) != len(marker_names):
        raise ValueError("names must be unique")
    rx, ry, bx = (np.asarray(v, dtype=np.float64) for v in (raw_x, raw_y, base_x))
    expected = (len(ts), len(marker_names))
    if any(v.shape != expected for v in (rx, ry, bx)):
        raise ValueError(f"raw_x, raw_y, base_x must all have shape {expected}")
    j_indices = np.array([i for i, name in enumerate(marker_names)
                          if name.startswith(("YJ", "ZJ")) and "XJ" not in name], dtype=int)
    j_names = [marker_names[i] for i in j_indices]
    out = rx.copy()
    out[~np.isfinite(out)] = np.nan
    gain = np.zeros(len(ts), dtype=float)
    activity = np.full(len(ts), np.nan, dtype=float)
    valid_count = np.zeros(len(ts), dtype=np.int64)
    status = np.full(len(ts), "OUTSIDE_WINDOW", dtype="<U32")
    applied = np.zeros(len(ts), dtype=bool)
    summaries = []
    if len(ts) == 0:
        return {"x": out, "gain": gain, "activity_r": activity, "valid_j_count": valid_count,
                "status": status, "guard_applied": applied, "j_names": j_names,
                "night_summaries": summaries, "config": dict(CONFIG)}

    # Match the native local-night convention: before noon belongs to prior date.
    day_ms = 86_400_000
    local_ms = ts + 8 * 3_600_000
    days = np.floor_divide(local_ms, day_ms)
    within = np.mod(local_ms, day_ms)
    night_days = days - (within < 12 * 3_600_000).astype(np.int64)
    night_ms = within + (within < 12 * 3_600_000) * day_ms
    current_night = None
    refs = deque(maxlen=CONFIG["max_reference_device_frames"])
    frozen = None
    summary = None

    for i in range(len(ts)):
        nd = int(night_days[i])
        nh = int(night_ms[i])
        if nd != current_night:
            current_night = nd
            refs.clear()
            frozen = None
            summary = {"night": _night_text(nd), "reference_frames_observed": 0,
                       "reference_frames_retained": 0, "baseline_frozen": False,
                       "baseline_eligible_j_count": 0, "baseline_eligible_j_names": [],
                       "baseline_by_j": [], "inside_frames": 0, "reference_available_frames": 0,
                       "reference_unavailable_frames": 0, "quiet_frames": 0,
                       "transition_frames": 0, "active_frames": 0}
            summaries.append(summary)
        if 22 * 3_600_000 <= nh < 23 * 3_600_000:
            refs.append(np.column_stack((rx[i, j_indices], ry[i, j_indices])))
            summary["reference_frames_observed"] += 1
            summary["reference_frames_retained"] = len(refs)
        if nh >= 23 * 3_600_000 and frozen is None:
            frozen = _freeze_reference(refs, len(j_indices))
            baseline, noise, epsilon, counts = frozen
            eligible = np.all(np.isfinite(baseline), axis=1)
            summary["baseline_frozen"] = True
            summary["baseline_eligible_j_count"] = int(np.sum(eligible))
            summary["baseline_eligible_j_names"] = [j_names[k] for k in np.flatnonzero(eligible)]
            for k, name in enumerate(j_names):
                def finite_list(values):
                    return [float(v) if np.isfinite(v) else None for v in values]
                summary["baseline_by_j"].append({"name": name, "counts_xy": counts[k].tolist(),
                    "median_xy": finite_list(baseline[k]), "q95_absdev_xy": finite_list(noise[k]),
                    "epsilon_xy": finite_list(epsilon[k])})
        if not (23 * 3_600_000 <= nh < 31 * 3_600_000):
            continue

        summary["inside_frames"] += 1
        gain[i] = 1.0
        status[i] = "REFERENCE_UNAVAILABLE"
        current = np.column_stack((rx[i, j_indices], ry[i, j_indices]))
        baseline, noise, epsilon, counts = frozen
        good = np.all(np.isfinite(current) & np.isfinite(baseline), axis=1)
        valid_count[i] = int(np.sum(good))
        if valid_count[i] >= CONFIG["min_current_valid_j"]:
            delta = np.abs(current[good] - baseline[good])
            q = noise[good]
            eps = epsilon[good]
            near_zero = q <= eps
            normalized = np.zeros_like(delta)
            np.divide(delta, q, out=normalized, where=~near_zero)
            # Exact/roundoff-quiet references remain quiet; a resolved change in
            # a zero-noise reference opens its activity to at least full gain.
            normalized[near_zero] = np.where(delta[near_zero] > eps[near_zero], 3.0, 0.0)
            activity[i] = float(np.median(np.max(normalized, axis=1)))
            u = float(np.clip((activity[i] - 1.0) / 2.0, 0.0, 1.0))
            g = u * u * (3.0 - 2.0 * u)
            gain[i] = g
            applied[i] = g < 1.0
            summary["reference_available_frames"] += 1
            if g == 0.0:
                status[i] = "REFERENCE_QUIET"
                summary["quiet_frames"] += 1
            elif g == 1.0:
                status[i] = "REFERENCE_ACTIVE"
                summary["active_frames"] += 1
            else:
                status[i] = "REFERENCE_TRANSITION"
                summary["transition_frames"] += 1
        else:
            summary["reference_unavailable_frames"] += 1

        finite = np.isfinite(rx[i]) & np.isfinite(bx[i])
        out[i] = np.nan
        if gain[i] == 0.0:
            out[i, finite] = rx[i, finite]
        elif gain[i] == 1.0:
            out[i, finite] = bx[i, finite]
        else:
            out[i, finite] = rx[i, finite] - gain[i] * (rx[i, finite] - bx[i, finite])

    return {"x": out, "gain": gain, "activity_r": activity, "valid_j_count": valid_count,
            "status": status, "guard_applied": applied, "j_names": j_names,
            "night_summaries": summaries, "config": dict(CONFIG)}
