"""Small synthetic truth/contract tests. No native solver or DLL is executed."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import numpy as np
from reference_activity_guard import apply_reference_activity_guard


LOCAL = timezone(timedelta(hours=8))
NAMES = np.array(["ZJ1", "ZJ2", "ZJ3", "ZD4201", "ZXJ1"])


def ms(hour=22, minute=0, day=6):
    return int(datetime(2026, 11, day, hour, minute, tzinfo=LOCAL).timestamp() * 1000)


def example(post_count=3, noisy_reference=False):
    ts = np.r_[ms() + np.arange(60, dtype=np.int64) * 60_000,
               ms(23) + np.arange(post_count, dtype=np.int64) * 60_000]
    x = np.full((len(ts), len(NAMES)), 100.0)
    y = np.full_like(x, 200.0)
    if noisy_reference:
        x[:60, :3] += np.where(np.arange(60)[:, None] % 2, 1.0, -1.0)
    return ts, x, y, x.copy()


def run_tests():
    checks = []

    ts, x, y, base = example()
    base[60:, 3:] += np.array([[-0.2], [0.3], [-0.1]])
    r = apply_reference_activity_guard(ts, NAMES, x, y, base)
    assert np.all(r["gain"][60:] == 0)
    np.testing.assert_array_equal(r["x"], x)
    assert r["j_names"] == ["ZJ1", "ZJ2", "ZJ3"]
    checks.append({"name": "all_quiet", "pass": True,
                   "claim": "静止J令gain=0，能抑制冻结候选中人为注入的输出波动；不代表原核心会凭空生成该波动"})

    ts, x, y, base = example()
    x[61:, 3] += 1.0
    r = apply_reference_activity_guard(ts, NAMES, x, y, base)
    np.testing.assert_array_equal(r["x"][61:, 3], x[61:, 3])
    assert r["gain"][61] == 0.0
    checks.append({"name": "ordinary_true_step_with_quiet_j", "pass": True,
                   "claim": "J静止时即使既有候选删除普通点+1阶跃，shadow仍保留当前raw阶跃"})

    ts, x, y, base = example()
    x[61:, :3] -= 1.0
    base[61:, 3] += 1.0
    r = apply_reference_activity_guard(ts, NAMES, x, y, base)
    assert r["gain"][60] == 0.0 and r["gain"][61] == 1.0
    assert x[61, 3] == 100.0 and r["x"][61, 3] == 101.0
    checks.append({"name": "motion_artifact_cancellation", "pass": True,
                   "claim": "目标真实+1与设备-1相消使raw为0变化，J动仍同帧开门，允许正确候选恢复+1；未保证既有核心能求出此候选"})
    checks.append({"name": "current_frame_event_no_detector_delay", "pass": True,
                   "claim": "当前J首次变化的同帧gain由0到1；不代表原W3/S1或整体输出无相位差"})

    ts, x, y, base = example()
    x[60, 0] = np.nan
    base[60:, 3] = 99.5
    r = apply_reference_activity_guard(ts, NAMES, x, y, base)
    assert r["status"][60] == "REFERENCE_UNAVAILABLE" and r["valid_j_count"][60] == 2
    assert r["gain"][60] == 1 and r["x"][60, 3] == 99.5 and np.isnan(r["x"][60, 0])
    no_j = apply_reference_activity_guard(ts, ["ZD1", "ZD2", "ZD3", "ZD4", "ZXJ1"], x, y, base)
    assert np.all(no_j["status"][60:] == "REFERENCE_UNAVAILABLE")
    assert np.all(no_j["gain"][60:] == 1)
    checks.append({"name": "missing_j_fallback", "pass": True,
                   "claim": "少于3个当前有效J或无J维持原候选并明示REFERENCE_UNAVAILABLE；不声称安全"})

    ts, x, y, base = example(noisy_reference=True)
    x[60:, :3] += np.array([[1.0], [2.0], [3.0]])
    base[60:, 3] = 99.0
    r = apply_reference_activity_guard(ts, NAMES, x, y, base)
    np.testing.assert_array_equal(r["gain"][60:], [0.0, 0.5, 1.0])
    np.testing.assert_array_equal(r["x"][60:, 3], [100.0, 99.5, 99.0])
    checks.append({"name": "gain_transition_counterexample", "pass": True,
                   "claim": "明确复现风险：目标raw恒100、原候选恒99，J活动变化使shadow100→99.5→99。smoothstep不保证不制造波形",
                   "raw_target_range": 0.0, "base_target_range": 0.0, "shadow_target_range": 1.0,
                   "max_shadow_adjacent_change": 0.5})

    ts, x, y, base = example()
    ts = np.r_[ts, ms(7, 0, 7), ms(7, 1, 7)]
    x = np.vstack([x, np.full((2, len(NAMES)), 100.0)])
    y = np.vstack([y, np.full((2, len(NAMES)), 200.0)])
    base = np.vstack([base, np.full((2, len(NAMES)), 97.0)])
    x[-1, 0] = np.nan
    base[60, 3] = np.nan
    r = apply_reference_activity_guard(ts, NAMES, x, y, base)
    np.testing.assert_array_equal(r["x"][-2:], x[-2:])
    assert np.isnan(r["x"][60, 3])
    assert np.all(r["status"][-2:] == "OUTSIDE_WINDOW")
    for end in (60, 61, 62, len(ts)):
        prefix = apply_reference_activity_guard(ts[:end], NAMES, x[:end], y[:end], base[:end])
        for key in ("x", "gain", "activity_r", "valid_j_count", "status", "guard_applied"):
            np.testing.assert_array_equal(prefix[key], r[key][:end])
    checks.append({"name": "causality_boundary_invalid_masks", "pass": True,
                   "claim": "前缀与全量重放逐数组相同；精确07发布raw；raw/base非有限不提升为有效坐标"})

    ts, x, y, base = example()
    keep = np.r_[np.arange(9), np.arange(60, 63)]
    r = apply_reference_activity_guard(ts[keep], NAMES, x[keep], y[keep], base[keep])
    assert np.all(r["status"][9:] == "REFERENCE_UNAVAILABLE")
    checks.append({"name": "insufficient_reference_baseline", "pass": True,
                   "claim": "每轴仅9个基准样本时不生成基准，夜间保留原候选且明确不可用"})

    ts = ms() + np.arange(123, dtype=np.int64) * 30_000
    x = np.full((len(ts), len(NAMES)), 100.0)
    y = np.full_like(x, 200.0)
    x[:60, :3] = 90.0
    r = apply_reference_activity_guard(ts, NAMES, x, y, x.copy())
    ns = r["night_summaries"][0]
    assert ns["reference_frames_observed"] == 120 and ns["reference_frames_retained"] == 60
    assert ns["baseline_by_j"][0]["median_xy"] == [100.0, 200.0]
    assert np.all(r["gain"][120:] == 0)
    checks.append({"name": "reference_last_60_device_frames", "pass": True,
                   "claim": "高于每分钟一帧时仅保留22–23最后60设备帧；缺失样本不会倒取更早帧补满"})

    return {"candidate": "reference_activity_shadow_v1", "test_scope": "纯Python合成真值及输出契约；未执行native核心",
            "all_assertions_passed": True, "check_count": len(checks), "checks": checks,
            "adoption_recommendation": "仅作shadow对照。gain_transition反例未解决，不应凭范围改善直接上线。",
            "physical_boundary": "J活动不能判定既有补偿形状正确；J活动期间仍可能删除真实扰动或保留错误补偿。"}


if __name__ == "__main__":
    report = run_tests()
    destination = Path(__file__).resolve().parents[1] / "reports" / "reference_activity_guard_tests.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"all_assertions_passed": report["all_assertions_passed"],
                      "check_count": report["check_count"], "report": str(destination)}, ensure_ascii=False))
