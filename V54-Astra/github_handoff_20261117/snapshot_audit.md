> 发布范围更新：这是完整本地依赖清单，不是本次已上传文件清单。大数据推送因传输速度低已终止，实际提交范围以SNAPSHOT_MANIFEST为准。

# V54-Astra 发布快照只读审查

当前整个目录 11176 文件、8.848 GB。建议精选 521 文件、1070.82 MB（未压缩），最大单文件 30.95 MB，均低于100 MiB。

机器可读清单见 snapshot_audit.json 的 files；每项含相对于 V54-Astra 的 path、bytes、sha256，可直接复制后逐项核验。

| 分组 | 文件数 | MB |
|---|---:|---:|
| base_source_helpers | 31 | 0.41 |
| round11_current_applicability | 57 | 114.03 |
| release_r8 | 60 | 8.61 |
| round9_left_42_47_1112 | 36 | 19.77 |
| data | 48 | 309.76 |
| round10_history_design | 4 | 0.79 |
| source_helpers | 46 | 0.55 |
| r9_extra_native_profiles | 63 | 238.82 |
| r11_native_baselines | 120 | 338.38 |
| r8_initial_state_sources | 12 | 4.08 |
| r9_native_gain_logs | 6 | 25.92 |
| r9_plot_helpers | 38 | 9.70 |

## 可重现边界
- R11 main computations and R9 algorithm-stage diagnosis are included with all required frozen profiles; R9 source_data_audit still requires original SQLite files at local source paths to repeat DB identity checks.
- R9 build_report has its exact 37 SVG inputs and manifest; the rest of the 5240-point atlas is intentionally omitted.
- R4 yd_stage_audit is included as AST function source. Running its own standalone YD1102 main needs additional right-device ablation output profiles, intentionally not included.
- R8 re-packaging scripts read absolute source_state paths recorded in original audit JSON; packaged state bytes are included and directly usable, but do not claim all historical generator scripts are portable.
- R11 history_length_report.py reads artifact paths serialized in its JSON; regenerate history_length_audit first or resolve those old provenance paths before rebuilding that report on another machine.
- R8 is the current release snapshot. R11 reference_activity_shadow_v1 is explicitly REJECTED; no research file replaces the R8 source.
- Original SQLite, previous rejected prototype result sets, repeated atlas/CSV exports/ZIP archives and native compiled outputs are excluded.
- All selected files are below 100 MiB. Total uncompressed tree exceeds preferred 700 MB because required input.bin/input.npz and independent frozen native baselines are preserved; Git compression is not measured here.

## 凭据和机器路径审查
- 已扫描精选文本 335 文件、56.62 MB；高信号/字面量规则命中 0 个文件类型项。匹配内容未输出。
- 全目录敏感配置文件名命中 0；结果仅是规则扫描，不是无凭据证明。
- 17 个脚本含绝对机器路径；详细文件名列入 JSON。这些主要是编译工具、原始数据库路径和历史来源，需与可移植回测入口区分。
- 二进制数据/状态与压缩归档未做语义凭据扫描；本次未改或上传任何文件。
