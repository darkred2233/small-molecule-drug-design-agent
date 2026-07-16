# BRAF 对接和外部细筛复现实验

目标：用项目里的对接工具和候选评估接口，复现 5 个 BRAF 候选分子的外部细筛结果，并和 `common/braf_external_tool_baseline.csv` 对比。

## 数据

- 受体：`student_tool_runs/data/3OG7_BRAF_receptor.pdb`
- 配体：`student_tool_runs/data/ligands/*.sdf`
- 已有 pose 对照：`student_tool_runs/data/poses/*.sdf`
- 结合口袋：`student_tool_runs/common/braf_binding_site.json`
- 基线结果：`student_tool_runs/common/braf_external_tool_baseline.csv`

## 要跑的内容

1. 先查 `/tools/status`，记录 GNINA、Vina、DiffDock、AiZynthFinder 是否可用。
2. 用 `single_docking_requests.jsonl` 逐个调用 `/tools/docking/run`。
3. 用 `candidate_assessment_fast_payload.json` 跑一次 fast 粗筛。
4. 用 `candidate_assessment_external_top5_payload.json` 跑一次 external 细筛。
5. 把结果填到 `result_template.csv`，重点比较 vina_score、cnn_score、pose_file、runtime_seconds、tool_name。

不建议默认跑 full 模式。

