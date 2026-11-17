# V54-Astra

已完成历史污染引起的回归过度修复的针对性修改，以及12设备连续回放和状态恢复验证。**这是离线候选；尚未达到“每天所有点都在2/1 pixel以内”，未部署。**

## 先看这里

- [完整图册：总览、重点反例、最新夜524点](plots/index.html)
- [最终源码](src/ModalSelfCal.cpp) / [接口和默认参数](src/ModalSelfCal.h)
- [算法依据与边界](reports/design.md)
- [全部逐点逐夜指标](reports/metrics_point_nights.csv)
- [最新夜未达标清单](reports/latest_night_failures.csv) / [覆盖不足](reports/latest_night_incomplete.csv)
- [仍存在的波形放大](reports/remaining_waveform_regressions.csv)
- [相对旧V54波动增加的全部记录](reports/increases_relative_to_v54.csv)
- [最新夜三曲线CSV.gz，12设备、314400行](exports/2026-11-15/manifest.json)
- [机器可读交付摘要](reports/delivery_summary.json)

## 口径与结果

用户确认x/y就是pixel，未换算scale。普通点目标为修后X整夜max−min≤2px；J/XJ点≤1px。`max_frame_dev=0`；该参数与整夜范围目标是不同概念。Y与**同配置V54离线回放**逐值一致，不冒充与现场另一版本/状态完全相同。

原V54数据来自指定源码独立编译回放。11/02–04用于预热，左线11/06夜缺失。仅覆盖达到80%的点夜计入以下分母。后期数据是时间复核，不是严格盲测。

| 时段 | 验收窗口 | V54达标点夜 | Astra达标点夜 |
|---|---|---:|---:|
| 11/05–11 开发检查 | 23:20–07:00 | 3261/3400 | 3264/3400 (96.00%) |
| 11/05–11 开发检查 | 22:00–08:00 | 2800/3403 | 2803/3403 (82.37%) |
| 11/12–15 后期复核 | 23:20–07:00 | 2037/2087 | 2037/2087 (97.60%) |
| 11/12–15 后期复核 | 22:00–08:00 | 1709/2089 | 1709/2089 (81.81%) |

最新11/15夜：23:20–07:00为506/522达标，仍有16点未达标；22–08整夜为443/522，仍有79点未达标。另2个名单点覆盖不足，不能计作通过。全部检查期间没有丢失V54原有达标修复，也没有新增“比原始输入明显更差”的点夜。这里“明显”定义为P95−P5增加超过max(0.05px,原始P95−P5的10%)。部分点相对旧V54仍有小幅波动增加，全部列在上面的相对变化清单中，不声称所有曲线均逐点优于旧版。

YD2603（右线780639346578）的**22–08整夜max−min，单位pixel**：

| 夜号 | V54 | Astra |
|---|---:|---:|
| 2026-11-05 | 4.315 | 1.740 |
| 2026-11-06 | 7.288 | 1.675 |
| 2026-11-07 | 9.179 | 1.711 |

YD1102（右线780639298317）11/05、11/06的P95−P5仍从原始0.406/1.026变成约0.576/1.479，虽最大最小范围仍在2px内，仍作为未解决的波形放大列出。不能把范围达标等同物理波形保真。

## 改了什么

有效测点因spread/guard退出学习后，原代码仍会给它回归载荷。新增X专用跨夜能量检验，对有效、非学习且非fit_only的回归点按`gamma=clip(2*min(q_n),0,1)`收缩不可靠载荷，可靠载荷保持1；该分类与2px普通点/1px J点的验收分类不同，不按测点名修补，也没有把所有曲线硬截平。原W3/模态/S2/S1链保留，零gate仍含原有W3。状态缓存、完整指纹、导入事务和断采缓存同时修复。

验证包括原生C++全流回放、3955项历史机制检查、原V54测试、8个真实重启检查点及损坏/不兼容状态拒绝。污染合成场景中安静点范围从旧模态6.300px恢复到原始0.100px。证据见[test_runs.json](reports/test_runs.json)、[真实恢复](reports/test_real_restart_manifest.json)、[历史增益审计](reports/metrics_energy_audit.json)。

## 集成与复现

集成只需`src/ModalSelfCal.cpp`和`src/ModalSelfCal.h`，标准C++17；本次使用GCC原生执行验证。可用根目录CMakeLists创建静态库，或把cpp加入现有工程。新快照魔数为`MSC_STATE_V54_ASTRA_HISTORY1`，旧状态明确拒绝；应回放原始历史重建，不能改指纹后强行导入。

`tools/run_replay.py --variant both`编译并回放，`tools/analyze_history_guard.py`生成指标，`tools/run_tests.py`和`tools/run_real_restart.py`验证状态，`tools/plot_report.py`生成图册。脚本需要Python、NumPy/Pandas及图形依赖；数据准备脚本的原库路径与SHA记录于reports。build中的replay DLL是离线工具。

原算法目录和数据库未修改。baseline保存原源码，data保存只读抽取，results保存原生结果，reports/plots/exports是审查入口；被否决的限幅和硬剔除试验在experiments。

## 尚不能承诺

未取得独立位移真值，未联调下游x0/y0；历史代理能量边界不等于未来每日全点达标或现场安全认证。剩余超标及波形问题已经保留在清单中，不能据此直接宣布满足全部上线条件。
