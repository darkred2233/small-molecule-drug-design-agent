# 候选分子综合排序开发记录

日期：2026-07-09

本次完成 M5 候选评估阶段的收口模块：综合排序与 Top candidates。模块命名为
`candidate_ranking`，避免继续使用里程碑编号命名，方便后续迁移和扩展。

## 1. 当前实现状态

已完成：

- 新增综合排序服务：`src/medagent/services/candidate_ranking.py`
- `POST /projects/{project_id}/candidate-assessment/run` 结束时自动生成排名。
- 新增独立重排入口：

```http
POST /projects/{project_id}/rankings/generate
```

- 新增排名查询入口：

```http
GET /projects/{project_id}/rankings
```

- `rankings` 表新增 `project_id` 字段，按项目保存结果，支持项目迁移和多项目并行。
- `ensure_relational_schema` 已补轻量迁移，旧 SQLite 启动时会自动补 `rankings.project_id`。

## 2. 排序输入

当前排序会综合读取以下结果：

- `rule_filter_results`：规则过滤是否通过、失败规则、结构规则风险。
- `docking_results`：`vina_score`、`cnn_score`、关键氢键、clash、pose 标签。
- `admet_results`：hERG、Ames、溶解度、渗透性、ADMET 风险分数。
- `synthesis_routes`：路线是否找到、路线步数、路线置信度、SA/SCScore、危险反应。
- `molecule_properties`：MW、LogP、TPSA、HBD、HBA、SA score。

如果某一类证据缺失，ranking 仍会运行，但会降低 `evidence_confidence`，并在 summary
warnings 中写入类似：

```text
missing_docking_evidence
missing_admet_evidence
missing_synthesis_evidence
missing_rule_filter_evidence
missing_properties_evidence
```

## 3. 排序输出

`GET /projects/{project_id}/rankings` 返回：

```json
[
  {
    "molecule_id": "MOL-...",
    "rank": 1,
    "pro_score": 72.3,
    "con_score": 24.1,
    "evidence_confidence": 1.0,
    "overall_score": 67.045,
    "final_decision": "watch",
    "score_breakdown": {
      "adapter_mode": "heuristic_candidate_ranking",
      "docking": {},
      "admet": {},
      "synthesis": {},
      "rule_filter": {},
      "properties": {},
      "blockers": []
    }
  }
]
```

`final_decision` 当前有四类：

- `advance`：综合分高、风险低、证据置信度足够，可进入下一轮优化或实验优先级。
- `watch`：整体可继续观察，适合等 RAG 或真实工具结果补强后再决策。
- `deprioritize`：分数或证据不足，暂时降低优先级。
- `reject`：结构无效、高风险 ADMET、严重合成/规则 blocker 等。

## 4. 当前评分策略

adapter mode：

```text
heuristic_candidate_ranking
```

这是可追踪启发式排序，不伪装成真实 ML 模型或专家系统。当前权重：

| 维度 | pro 权重 | con 权重 |
|---|---:|---:|
| Docking | 0.35 | 0.25 |
| ADMET | 0.25 | 0.35 |
| Synthesis | 0.20 | 0.20 |
| Rule filter | 0.10 | 0.10 |
| Properties | 0.10 | 0.10 |

综合分：

```text
overall_score = clamp(pro_score - con_score * 0.55 + evidence_confidence * 8, 0, 100)
```

后续接入真实工具或 RAG 后，建议仍保留 `score_breakdown` 的结构，把真实证据作为 component
details 写入，避免前端和报告层反复改 schema。

## 5. 文件变更

| 文件 | 作用 |
|---|---|
| `src/medagent/services/candidate_ranking.py` | 综合排序服务、评分策略、AgentRun 记录 |
| `src/medagent/services/candidate_assessment.py` | 候选评估完成后自动调用 ranking |
| `src/medagent/db/models.py` | `Ranking` 增加 `project_id` 和项目内唯一约束 |
| `src/medagent/services/database.py` | 旧库自动补 `rankings.project_id` |
| `src/medagent/domain/schemas.py` | 新增 ranking request/response/read schema |
| `src/medagent/api/app.py` | 新增 ranking 生成和查询 API |
| `tests/test_candidate_assessment.py` | 覆盖自动排名、查询排名、重复重排不堆重复数据 |
| `docs/CANDIDATE_RANKING_BUILD.md` | 本开发记录 |

## 6. 已验证测试

已执行：

```text
.\.venv\Scripts\python.exe -m pytest tests\test_candidate_assessment.py -q
```

结果：

```text
4 passed, 1 warning
```

warning 来自 FastAPI/TestClient 依赖链中的 Starlette deprecation，不是业务失败。

## 7. 给 RAG 模块的衔接点

RAG 完成后建议优先接这三处：

1. 在 `score_breakdown` 中新增 `rag_evidence` component，记录文献 chunk、claim、confidence。
2. 在 `evidence_confidence` 中加入 RAG 证据权重，区别“工具分数充分”和“文献证据充分”。
3. 把 `/projects/{project_id}/rankings/generate` 作为 RAG 更新后的重排入口，而不是重复跑 docking/ADMET/synthesis。
