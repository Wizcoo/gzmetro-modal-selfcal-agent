# 当前J活动门控：shadow API与已知边界

**本轮全量回测后已判定REJECTED，不进入交付；结论见 `reference_activity_guard_verdict.md`。以下保留实验API及复查契约，不代表推荐使用。**

本候选仅用于离线对照，不修改Astra核心、历史、状态或Y。它要求当前J提供活动证据，再缩放原候选的整机X总补偿；**它没有独立重新求解补偿，也不能证明原补偿的空间形状正确**。不能把它等同于 `guard_design_review.md` 候选C中的“参考独立估计、只更新有支持的补偿增量”。

```python
from reference_activity_guard import apply_reference_activity_guard

r = apply_reference_activity_guard(
    timestamp_ms,  # (N,) int64 Unix毫秒，严格递增，无重复/回放行
    names,         # (M,) 唯一测点名，与三个坐标数组同列顺序
    raw_x,         # (N,M) pixel，ROI无效已经置NaN
    raw_y,         # (N,M) pixel，ROI无效已经置NaN
    base_x,        # (N,M) 冻结current_fade07最终绝对X，同帧同列
)
shadow_x = r["x"]
```

不作像素/毫米换算，不重新对齐基准，不用数据库有限坐标替代ROI有效性。调用方仍须保留原 `output_ready`/无输出掩码；函数不构造可发布状态。输入数组不会被修改。

|返回键|类型/含义|
|---|---|
|`x`|`(N,M)` shadow绝对X；Y由调用方保持原值|
|`gain`|`(N,)`：窗外0；参考不足1；参考有效时smoothstep结果|
|`activity_r`|`(N,)`：当前J活动中位数；未评估时NaN|
|`valid_j_count`|`(N,)`：夜间当帧基准与当前XY均有效的J数量；窗外0|
|`status`|`OUTSIDE_WINDOW`、`REFERENCE_UNAVAILABLE`、`REFERENCE_QUIET`、`REFERENCE_TRANSITION`、`REFERENCE_ACTIVE`|
|`guard_applied`|`(N,) bool`：夜间参考可用且gain<1；不是物理安全标志|
|`j_names`|仅前缀YJ/ZJ且不包含XJ的测点名|
|`night_summaries`|逐夜基准样本数、中位数、P95偏差、epsilon和状态计数；可直接JSON序列化|
|`config`|固定版本规则，无逐设备/逐点运维参数|

时间按固定UTC+8；当地12点前归前一夜。每夜只收集22:00≤t<23:00的最后最多60个设备帧，每J每轴至少10个有限样本，取median及围绕median的绝对偏差P95。23点后第一次调用冻结基准，不用未来帧补基准，不跨夜借用。高于一分钟一帧时，“最后60帧”覆盖的分钟数会短于60分钟，数据报告可见帧数；这仍是版本内部采样规则，不是连续时间覆盖保证。

当帧每个J要求raw X/Y均有效，且两轴基准均有效。每J取两轴归一偏差最大值，跨至少3个有效J取median为r，gain为 `smoothstep(clip((r-1)/2,0,1))`。基准P95小于浮点可分辨尺度时，当前变化在该尺度内记0，超过记3；不添加人为像素噪声下限。此规则对严格静止基准敏感，应连同真实数据结果检查。

23:00≤t<次日07:00时，shadow为 `raw - gain*(raw-base)`；gain0精确选择raw，gain1精确选择base。raw或base非有限时夜间输出NaN，即使gain0也不提升缺失base为有效坐标。其他时段精确发布raw，仅raw非有限置NaN。07切换按用户已确定的观测段切换契约处理，不作渐退。

参考不可用包括没有J、少于3个当帧有效J、基准不足。这时维持原候选并标 `REFERENCE_UNAVAILABLE`；这是可比性回退，绝不是安全证明。J在参考窗口漂移会增大噪声带，J离群/有效成员变化也可能改变gain；不能用J数量代替对J物理稳定性的核实。

## 已运行的小型测试

`tools/test_reference_activity_guard.py` 已运行，9项断言通过，记录在 `reference_activity_guard_tests.json`。包括静止、J静止时普通点真阶跃、目标真实+1与设备-1抵消、当前帧活动检测、J缺失、因果前缀一致、07端点、NaN、不足基准和最后60帧规则。这些是纯Python构造的已知输入/候选输出测试，未运行native求解器，不能替代原始输入注入后重跑全链路的保真验证。

一个必须保留的**失败反例已被测试明确复现**：目标raw恒100、原候选恒99，只令J活动r从1→2→3，则gain从0→0.5→1，shadow从100→99.5→99。目标本来两条曲线都没有波动，门控却制造了1pixel范围和0.5pixel相邻变化。smoothstep只有对活动分数的连续性，不能保证时间波形不出现新增变化；J缺测导致回退gain1也有同类风险。

当前帧用J计算没有额外“等待未来帧”的检测延迟，但这不代表整条Astra/W3/S1无延迟，亦不代表变增益后峰谷时刻不变。J活跃时gain1，不修复ZXJ6等既有空间补偿失配；J活跃同时普通点真实位移也可能继续被原候选扣除。离线验收应同时报告范围改善、静夜新增波动、相邻变化、参考缺失、J/XJ差分和对上述反例的承认。

因此本候选可以回答“当前J不动时，缩小历史驱动补偿会发生什么”，还不足以回答“今日历史关系正确且物理波形已被保留”。如果全量回测出现明显新增波形，应拒绝该直接乘gain形式，优先研究独立参考支持的补偿增量及必要状态，而不是再叠加一个平滑器掩盖风险。
