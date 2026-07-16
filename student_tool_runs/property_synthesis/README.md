# Top1 类似物性质、ADMET、合成可行性小实验

目标：围绕当前 BRAF Top1 `MOL-D87CC67DED` 做一个小型类似物面板，使用项目的 RDKit 和 ADMET 接口筛选，再结合已有 AiZynthFinder route JSON 判断哪些分子更适合作为下一轮优化起点。

## 数据

- 类似物面板：`top1_analog_panel.csv`
- RDKit 参考基线：`top1_analog_rdkit_baseline.csv`
- RDKit 请求：`rdkit_validate_requests.jsonl`
- ADMET 请求：`admet_predict_payload.json`
- 现有合成路线对照：`student_tool_runs/data/retrosynthesis/*/aizynthfinder_routes.json`
- 当前 Agent Top10：`student_tool_runs/common/braf_top10_agent_baseline.csv`

## 要跑的内容

1. 用 `rdkit_validate_requests.jsonl` 逐个调用 `/tools/rdkit/validate`。
2. 用 `admet_predict_payload.json` 调 `/tools/admet/predict`。
3. 读取已有 `aizynthfinder_routes.json`，比较 route_found、route_steps、route_confidence。
4. 选出 3 个你认为值得进入下一轮局部优化的分子，并填入 `result_template.csv`。

重点不是追求最高 docking 分，而是解释“性质、ADMET、合成可行性”之间的取舍。

