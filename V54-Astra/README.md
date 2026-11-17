# V54-Astra 当前交付与研究入口

本次GitHub提交包含当前源码、12设备状态/备份、研究脚本和诊断报告；**未上传本次新增的冻结input.npz/input.bin、原生output.bin、除小型合成冻结模型外的NPZ中间数组、大日志及部分大型JSON/CSV数值明细**。它们保留在原本地工作区。原大仓库Wizcoo/gzmetro-modal-selfcal的旧data目录日期不同，不能冒充本轮输入。完整依赖清单见snapshot_audit，实际已上传/省略清单见SNAPSHOT_MANIFEST。云端可审查代码与证据，完整重跑R9–R12前须按哈希补齐省略数据。

快照日期：2026-11-17。当前可交接源码是 **round8_release_111315/source 的一个 cpp 和一个 h**；R9–R12为后续诊断，未替换R8，尚未得到可上线的“当前历史关系失效保护”方案。

- [接手 Agent：完整中文 Spec / Memory](github_handoff_20261117/AGENT_SPEC_ZH.md)
- [可复制启动 Prompt](github_handoff_20261117/PROMPT_ZH.md)
- [R8接入说明及验证边界](round8_release_111315/接入说明.md)
- [Argon建议与增量反例最新审查](round12_argon_review/README.md)
- [R11问题、历史长度与已否决保护候选](round11_current_applicability/index.html)
- [327479 / 42–47断面诊断](round9_left_42_47_1112/分析结论.md)
- [快照范围与依赖](github_handoff_20261117/snapshot_audit.md)
- [文件完整性清单](SNAPSHOT_MANIFEST.json)

主窗为北京时间23:00含至次07:00不含。普通点范围尽量1、最多2 pixel，J基准点1 pixel；XJ是普通点，允许与设备共同趋势一致的波动，需检查相对观测。保持真实波形及峰谷时间优先。07后发布raw X。

R8附12设备13/14/15夜（各22–02）的状态及精确点序，截止11/16早间，用于11/16夜及以后。它们不适合回推11/12独立验证。新R8封装已编译但未完成原生运行与逐份Import/Export验证；不要把静态校验冒充运行通过。

## 编译当前双文件

```sh
cmake -S V54-Astra -B build/V54-Astra
cmake --build build/V54-Astra --config Release
```

默认只构建当前R8静态库。可在允许执行的环境增加 `-DASTRA_BUILD_STATE_VERIFIER=ON` 构建原有验证器；使用说明在 `round8_release_111315/tools/验证工具运行说明.txt`。本次发布未执行新原生程序。

## 复现已完成的离线诊断

先按SNAPSHOT_MANIFEST的omitted_replay_files补齐原本地冻结数据。仅完整性检查可在当前Git快照直接执行；后面的回放命令缺输入时不能运行。从仓库根执行，Python 3.10+，安装 `V54-Astra/requirements-replay.txt`。下面命令会在相应reports目录生成结果；需保留冻结数据，重新核对本机结果。

```sh
python V54-Astra/github_handoff_20261117/verify_snapshot.py
python V54-Astra/round11_current_applicability/tools/quiet_inventory.py
python V54-Astra/round11_current_applicability/tools/history_length_audit.py
python V54-Astra/round11_current_applicability/tools/history_length_report.py
python V54-Astra/round11_current_applicability/tools/synthetic_constant_core.py
```

`reference_activity_guard.py` 及其field audit仅用于复现 **REJECTED** 实验；不是新版算法。原始SQLite身份复核仍需原库，旧生成脚本中机器绝对路径只保留为来源，不承诺所有历史脚本直接跨平台运行。精确范围见snapshot_audit。

本次GitHub提交包含当前源码、12设备状态/备份、研究脚本和诊断报告；**未上传本次新增的冻结input.npz/input.bin、原生output.bin、除小型合成冻结模型外的NPZ中间数组、大日志及部分大型JSON/CSV数值明细**。它们保留在原本地工作区。原大仓库Wizcoo/gzmetro-modal-selfcal的旧data目录日期不同，不能冒充本轮输入。完整依赖清单见snapshot_audit，实际已上传/省略清单见SNAPSHOT_MANIFEST。云端可审查代码与证据，完整重跑R9–R12前须按哈希补齐省略数据。 另省略重复完整图册/解算CSV导出、原始数据库和编译产物。旧轮次说明保留为 [README.early_round.md](README.early_round.md)，其中旧时段、XJ阈值及“最终源码”用语不能覆盖本入口。

本快照在独立轻量仓库 `Wizcoo/gzmetro-modal-selfcal-agent` 的main发布。旧snapshot_audit记录全量本地依赖；以根PACKAGE_MANIFEST为本包大小/文件范围依据。R12的LOO和增量反例脚本可直接复查，gain_probe及完整历史回放仍缺大输入。
