# Agent接手入口

先读 `V54-Astra/github_handoff_20261117/AGENT_SPEC_ZH.md` 和 `V54-Astra/round12_argon_review/README.md`。

- 当前交付源码位于 `V54-Astra/round8_release_111315/source`，只有一个cpp和一个h；R9–R12是诊断，不是已验证新版本。
- 所有新产物放V54-Astra的新轮次目录，保留R8、原始raw及历史证据。不得为凑通过率改变时间、ROI或点序。
- J默认固定；XJ是普通测点，不能当静止参考。保持真实波形及峰谷时间优先。
- 大冻结输入未随包上传。先核对SNAPSHOT_MANIFEST；缺数据时明确报告缺项，不能伪造全链回测、状态往返或物理验证。
- 该仓库main仅含轻量交接历史。原大仓库链接仅用于追溯，禁止作为隐式子模块或全量数据下载依赖。
