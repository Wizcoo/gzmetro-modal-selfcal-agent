# V54-Astra 轻量 Agent 交接仓库

本仓库为解决100 MB导入限制而独立建立，不继承原仓库的大体积提交历史。当前权威算法仍是R8；R9–R12为诊断与研究，未形成新的可上线保护方案。

- **仓库：** `Wizcoo/gzmetro-modal-selfcal-agent`；**分支：** `main`
- [先读：完整中文Spec / Memory](V54-Astra/github_handoff_20261117/AGENT_SPEC_ZH.md)
- [可直接复制的启动Prompt](V54-Astra/github_handoff_20261117/PROMPT_ZH.md)
- [当前一个cpp + 一个h](V54-Astra/round8_release_111315/source/)
- [12设备13/14/15夜状态包与接入说明](V54-Astra/round8_release_111315/接入说明.md)
- [327479 / ZXJ6反向残留原因](V54-Astra/round9_left_42_47_1112/分析结论.md)
- [最新：Argon建议审查与反例](V54-Astra/round12_argon_review/README.md)
- [Astra详细目录与历史实验](V54-Astra/README.md)

## 包含与缺项

包含当前源码、12份状态及备份/点序、历史诊断脚本、关键报告与图、小型合成冻结模型。完整数据库、input.npz/input.bin、原生output.bin、大型中间数组/日志和完整CSV/图册仍在原本地工作区，没有放进此仓库。各省略文件的路径、字节数和SHA256保留在[V54-Astra/SNAPSHOT_MANIFEST.json](V54-Astra/SNAPSHOT_MANIFEST.json)。历史snapshot_audit记录全量本地依赖，不能作为本包上传大小。

云端可审查代码和证据、编译R8、复查有限LOO与增量反例；完整12设备10夜回测仍需按清单补齐输入。不能拿原大仓库旧data替代，不能把小型反例当成完整回测或现场物理验证。

## 直接复查

```sh
python V54-Astra/github_handoff_20261117/verify_snapshot.py
python -m pip install -r V54-Astra/requirements-replay.txt
python V54-Astra/round12_argon_review/loo_diagnostic.py
python V54-Astra/round12_argon_review/increment_counterexamples.py
cmake -S V54-Astra -B V54-Astra/build
cmake --build V54-Astra/build --config Release
```

反例脚本会重写对应报告/JSON，请保留原始快照供比较。本次整理未重新验证原生状态Import/Export；先前环境阻止新原生程序执行，编译成功不等于设备接入通过。

原完整仓库保留：[Wizcoo/gzmetro-modal-selfcal](https://github.com/Wizcoo/gzmetro-modal-selfcal/tree/collab/v54-astra-20261117)。它仅作为来源追溯，不是此轻量仓库的Git父历史，也不要再将它作为100 MB限制下的导入入口。
