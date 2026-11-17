# 平稳夜与历史强扰动后的适用性测试清单

只读使用冻结12台输入与current_fade07输出。目标夜11/06–15，窗口23–次07；普通/J为主统计，XJ单列。raw范围≤1 pixel且有效≥384/480定义为平稳点夜，不回看候选结果改定义。

主统计有121个平稳点夜（普通115、J6），XJ另有3个；current_fade07对主统计既无峰谷差放大，也无跨越1 pixel。严格整台平稳夜共有0个，不能把单点平稳替代为整台设备平稳。

| 固定分组 | 合格点夜 | 有意义范围放大 | 有意义P95−P5放大 | 新范围>1 |
|---|---:|---:|---:|---:|
| all_ordinary_J | 4851 | 2 | 1 | 1313 |
| quiet_ordinary_J | 121 | 0 | 0 | 0 |
| nonquiet_ordinary_J | 4730 | 2 | 1 | 1313 |
| quiet_history_median_gt2_22_02 | 0 | 0 | 0 | 0 |
| quiet_history_median_gt2_23_07 | 1 | 0 | 0 | 0 |
| quiet_all3_history_gt2_22_02 | 0 | 0 | 0 | 0 |
| quiet_all3_history_gt2_23_07 | 0 | 0 | 0 | 0 |
| quiet_baseline_shift_like | 0 | 0 | 0 | 0 |
| quiet_local_step_like | 0 | 0 | 0 | 0 |
| quiet_with_any_invalid_ROI | 57 | 0 | 0 | 0 |
| quiet_with_missing_baseline | 0 | 0 | 0 | 0 |
| all_primary_baseline_shift_like | 140 | 1 | 0 | 140 |
| all_primary_local_step_like | 1068 | 0 | 0 | 655 |
| all_primary_missing_baseline | 0 | 0 | 0 | 0 |
| all_primary_missing_or_low_coverage | 0 | 0 | 0 | 0 |
| quiet_XJ_separate | 3 | 0 | 0 | 0 |

历史前3夜按设备数据有效性挑选，必须有22–23基准、22–02至少144帧可累计数据及02点后真实收夜帧；各点历史22–02范围与23–07范围分别存储，历史强弱比仅诊断，不用于校准算法。完整3夜且各点有效率≥80%才进入“历史中位范围>2”分组；另列三个历史夜全都>2。

基准偏移和局部step-like是观测形态标签，不是假定真实位移。基准偏移用当夜首30分钟中位数减22–23固定基准；局部跃迁用相邻10样本中位数之差并扣除设备共趋势作辅助判别，未平滑原始回放数据。

除平稳集外，另固定观测到的局部跃迁/基准偏移作为补充场景。它们没有独立物理真值，不能称为真实位移，也不能将相关性低直接等同于算法应保留或应扣除。

## 固定代表案例

| 选择理由 | 设备/点/夜 | raw→新范围 | 前3夜22–02中位范围 | 历史/当夜比 |
|---|---|---:|---:|---:|
| largest_prior22_02_to_current_ratio | left/780638310097/ZD3704/2026-11-14 | 0.9220 → 0.2560 | 1.8124 | 1.97 |
| largest_prior22_02_to_current_ratio | left/780638310097/ZD4204/2026-11-14 | 0.9264 → 0.3133 | 1.7941 | 1.94 |
| largest_prior22_02_to_current_ratio | left/780638349768/ZD4404/2026-11-14 | 0.9850 → 0.1397 | 1.8947 | 1.92 |
| largest_prior22_02_to_current_ratio | left/780638310097/ZD3904/2026-11-14 | 0.9205 → 0.2741 | 1.7612 | 1.91 |
| largest_prior23_07_to_current_ratio | right/780639333715/YD1302/2026-11-12 | 0.6177 → 0.2905 | 0.8813 | 1.43 |
| largest_prior23_07_to_current_ratio | right/780639333715/YD1405/2026-11-12 | 0.8367 → 0.5959 | 1.3376 | 1.60 |
| largest_prior23_07_to_current_ratio | left/780638310097/ZD2202/2026-11-14 | 0.9864 → 0.2465 | 1.7471 | 1.77 |
| smallest_existing_range_improvement | right/780639414923/YD4501/2026-11-09 | 0.6678 → 0.6358 | 0.6098 | 0.91 |
| smallest_existing_range_improvement | right/780639414923/YD4601/2026-11-09 | 0.7614 → 0.6128 | 0.8497 | 1.12 |
| smallest_existing_range_improvement | right/780639333715/YD1402/2026-11-06 | 0.9360 → 0.6860 | 0.6209 | 0.66 |
| largest_baseline_offset_in_quiet | left/780638327479/ZD3705/2026-11-07 | 0.9875 → 0.4038 | 0.9206 | 0.93 |
| largest_baseline_offset_in_quiet | left/780638327479/ZD3805/2026-11-07 | 0.9706 → 0.3700 | 0.9921 | 1.02 |
| largest_baseline_offset_in_quiet | right/780639346578/YD2301/2026-11-06 | 0.9531 → 0.5823 | 1.0159 | 1.07 |
| lowest_valid_coverage_in_quiet | right/780639333715/YD1302/2026-11-14 | 0.8805 → 0.3559 | 0.7293 | 0.83 |
| lowest_valid_coverage_in_quiet | left/780638327479/ZD3503/2026-11-15 | 0.9928 → 0.2868 | 1.3015 | 1.31 |
| ordinary_J_material_p95_regression | right/780639298317/YD1102/2026-11-06 | 1.6338 → 1.8365 | 2.0025 | 1.23 |
| nonquiet_observed_local_step_no_physical_truth | left/780638327479/ZD4104/2026-11-09 | 11.4455 → 5.0370 | 4.0184 | 0.35 |
| nonquiet_observed_local_step_no_physical_truth | left/780638327479/ZD3204/2026-11-09 | 7.7959 → 3.5798 | 2.3115 | 0.30 |
| nonquiet_observed_local_step_no_physical_truth | left/780638310097/ZD2602/2026-11-09 | 8.2007 → 1.8389 | 2.5740 | 0.31 |
| nonquiet_baseline_shift_no_physical_truth | right/780639376393/YD4605/2026-11-11 | 8.1708 → 6.6100 | 8.9756 | 1.10 |
| nonquiet_baseline_shift_no_physical_truth | right/780639376393/YD4305/2026-11-11 | 5.3381 → 5.1657 | 5.5150 | 1.03 |

全部121个固定平稳案例见quiet_inventory_fixed_tests.json；全5240点夜baseline数值见quiet_inventory_all_point_baseline.json。候选必须继续跑完整10夜，不能只在这个平稳子集上报告通过率。

## 有已知真值的合成验证建议

- 真实历史后整台固定：保持真实三夜，下一夜22–07每点固定为自身单独的常数，连基准窗也固定；零位移是已知真值。另设真实22–23基准后23–07恒定的边界过渡变体，避免把两个场景混淆。ROI/gap另做独立变体，不改变真实数据回测。
- 强历史后真实平稳：冻结真实历史和当前平稳样本；这仅证明不放大观测波动，不证明真实位移为零。若没有整台平稳真夜，明确使用合成整台固定补充。
- 局部真实step与设备共扰动分开：构造局部位移真值、全点相同相机扰动、两者叠加三份独立fixture；固定J物理真值保持不动。要求保留局部step幅度和发生时间，不能以全部修平为通过。
- 基准跨界偏移与缺测：分别构造整台偏移、单点偏移、ROI掉线，不混成一个无法解释的测试。

本清单没有改算法、运行新DLL或改数据库；所有源hash、缺测、具体历史日期及诊断定义在quiet_inventory.json。
