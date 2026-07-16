# 三类分子生成开发记录

初始日期：2026-07-09；工具链加固：2026-07-16

本次实现对应开发说明 M4 的 Molecule Generator Agent：从项目 seed ligand 或内置靶点药物库出发，生成三类候选分子，并把结果写入 `molecules`、`agent_runs`，后续可以继续运行结构校验和规则过滤。

## 1. 当前实现状态

已完成：

- 新增 `POST /projects/{project_id}/molecules/generate`。
- 默认一次调用运行 `reinvent4`、`crem`、`autogrow4` 三类生成策略。
- 已安装并使用 `RDKit`、`Datamol`。
- 已接入 CReM Python 包，并把 fragment 数据库放入项目 `database/chembl22_sa2.db`。
- CReM 策略优先调用真实 fragment DB；如果某个 seed 没有产出，则用 RDKit/Datamol surrogate 候选补足请求数量。
- REINVENT4、AutoGrow4 在运行时可用且前置条件完整时会调用真实外部工具；否则保留 RDKit/Datamol surrogate 回退，并把具体失败原因写入 warning。
- 外部生成结果会再次经过 SMILES、Tanimoto 和性质约束，不满足项目约束的结果不会直接入库。
- 生成结果支持幂等重试：同一项目、相同 seed 和相同请求重复调用时，不会重复写入相同 SMILES。

## 2. CReM Fragment DB 放置

用户已有数据库：

```text
C:\Users\zhihong\Desktop\drugdesign-agentpro\backend\chembl22_sa2.db
```

已在当前项目创建硬链接：

```text
C:\Users\zhihong\Desktop\small-molecule-drug-design-agent\database\chembl22_sa2.db
```

该路径位于项目目录内，后续迁移整个项目目录时会一起带走。服务默认会优先检测这个路径；也支持通过环境变量覆盖：

```text
MEDAGENT_CREM_DB
CREM_DB
```

## 3. 新增和修改文件

| 文件 | 作用 |
|---|---|
| `src/medagent/services/molecule_generation.py` | 三类分子生成、seed 收集、RDKit/Datamol 标准化、CReM DB 调用、相似度/性质约束、去重和入库 |
| `src/medagent/domain/schemas.py` | 新增生成请求、生成响应、每类策略统计、工具状态字段 |
| `src/medagent/api/app.py` | 新增候选分子生成 API |
| `src/medagent/services/decision_cards.py` | 在 RDKit 可用时保留下游 docking/ADMET 风险提示 |
| `src/medagent/services/tool_config.py` | 统一读取工具命令、镜像、超时及环境变量覆盖 |
| `src/medagent/services/reinvent4_adapter.py` | REINVENT4 prior sampling、执行证据和失败状态 |
| `src/medagent/services/autogrow4_adapter.py` | AutoGrow4 docking-guided 生成、执行证据和失败状态 |
| `tests/test_molecule_generation.py` | 覆盖三类生成、工具状态、CReM DB 检测、幂等、目标库 seed、后续校验和过滤 |
| `docs/MOLECULE_GENERATION_BUILD.md` | 本开发记录 |

## 4. API

```http
POST /projects/{project_id}/molecules/generate
```

请求示例：

```json
{
  "generation_size": 9,
  "strategies": ["reinvent4", "crem", "autogrow4"],
  "constraints": {
    "keep_core": true,
    "min_tanimoto_to_seed": 0.1,
    "max_tanimoto_to_seed": 0.95
  },
  "include_target_library_seeds": true
}
```

响应会返回：

- 总请求数、提出候选数、入库数、重复数、非法数。
- `strategy_summaries`：每类策略的入库分子 ID、adapter 模式、工具状态、warning、候选来源统计和 provenance。
- `tool_status`：RDKit、Datamol、CReM、REINVENT4、AutoGrow4 当前是否可用。

当前 `generation_size` 限制为 `1..500`。

## 5. Seed 来源

默认 seed 来源：

1. 项目上传文件解析出的 `seed_ligands.smiles`。
2. 当 `include_target_library_seeds=true` 时，读取内置 `target_drug_library` 的 `smiles/canonical_smiles/isomeric_smiles`。
3. 如果指定靶点暂时没有内置 SMILES，则使用小型 fallback seed。

为了保证重试幂等，当前不会默认把本项目已生成的候选分子再次作为 seed。后续如果需要多轮扩展，建议新增显式开关，例如 `include_existing_molecules_as_seeds`。

## 6. 三类策略

### REINVENT4

真实工具可用时，adapter mode 为：

```text
reinvent4_local
reinvent4_docker
```

否则回退为：

```text
rdkit_datamol_scored_reinvent4_surrogate
```

真实模式的作用与边界：

- 使用配置的 prior 执行 REINVENT4 `sampling`。
- 当前 sampling 不使用 seed 作为生成条件，也没有运行靶点导向强化学习；warning 会明确标记这一点。
- 真实输出仍要通过项目约束过滤，过滤后没有候选时再回退 surrogate。

surrogate 作用：

- 用 RDKit/Datamol 枚举和标准化 seed 周边 analog。
- 用 RDKit descriptors 与 Morgan fingerprint Tanimoto 做基础筛选。
- 在标签和 warning 中明确标记 `external_reinvent4_pending`，避免误认为已经启动真实 REINVENT4 强化学习流程。

### CReM

当前 adapter mode 根据运行情况可能为：

```text
crem_fragment_database
crem_fragment_database_with_rdkit_surrogate_fill
rdkit_datamol_crem_fragment_surrogate
```

作用：

- 优先使用 `database/chembl22_sa2.db` 运行 CReM fragment replacement。
- 对 EGFR 代表结构可以从 fragment DB 真实生成 analog。
- 对太小或无法匹配 DB 的 seed，用 RDKit/Datamol surrogate 补足数量，并在 warning 中写明。

### AutoGrow4

真实工具可用且提供受体与网格时，adapter mode 为：

```text
autogrow4_local
autogrow4_docker
```

否则回退为：

```text
rdkit_datamol_grow_link_autogrow4_surrogate
```

真实模式的作用与边界：

- 使用受体结构、`grid_center`、`grid_size`、Vina 与 Open Babel，通过 AutoGrow4 正式的 `-j config.json` 入口运行遗传优化。
- 当前适配器只声明支持 `genetic` 模式，不把普通遗传运行误标为 MCTS。
- Docker 镜像默认固定到 AutoGrow4 `v4.0.3` 提交。
- 缺少受体、网格、运行时依赖或有效输出时会记录具体 warning。

surrogate 作用：

- 用 RDKit/Datamol 枚举模拟 grow/link 风格候选。
- 保留 `external_autogrow4_pending` 标签，等待后续接入真实 docking-guided AutoGrow4 流程。

## 7. 数据库写入

每个成功入库分子写入：

```text
status = generated
source_agent = generator_agent:<strategy>
labels = [
  "generated",
  "candidate_generated",
  "requires_structure_validation",
  "generator_strategy_<strategy>",
  ...
]
```

如果真实外部系统尚未接入，会额外带：

```text
external_generation_adapter_pending
external_generation_fallback_used
external_reinvent4_pending
external_autogrow4_pending
crem_fragment_database_pending
```

每次生成都会创建一条 `agent_runs`：

```text
agent_name = generator_agent
model_name = tool-adapter
status = success
```

`input_json` 和 `output_json` 会记录请求参数、seed 数量、工具状态、每类策略统计、warning、provenance 和外部 adapter 是否已连接。

## 8. 约束支持

当前生成器支持以下约束键：

```text
keep_core
protected_motif
min_tanimoto_to_seed
max_tanimoto_to_seed
min_mw / max_mw
min_logp / max_logp
min_tpsa / max_tpsa
min_hbd / max_hbd
min_hba / max_hba
```

Tanimoto 使用 RDKit Morgan fingerprint；性质约束使用 RDKit descriptors。Datamol 用于标准化和 canonical SMILES。

## 9. 推荐调用顺序

从上传 seed 文件开始：

```text
POST /projects
POST /projects/{project_id}/files
POST /projects/{project_id}/ingest
GET  /projects/{project_id}/seed-ligands
POST /projects/{project_id}/molecules/generate
GET  /projects/{project_id}/molecules
POST /projects/{project_id}/molecules/validate
POST /projects/{project_id}/molecules/filter-rules
```

从内置靶点库直接开始：

```text
POST /projects
POST /projects/{project_id}/molecules/generate
POST /projects/{project_id}/molecules/validate
POST /projects/{project_id}/molecules/filter-rules
```

## 10. 历史验证记录

以下是初始实现阶段的历史结果。本次 2026-07-16 工具链加固按要求未重新运行测试套件，不能把下列数字当成本次改动的验证结果。

已执行：

```text
.\.venv\Scripts\python.exe -m pytest tests\test_molecule_generation.py -q
```

结果：

```text
3 passed, 1 warning
```

已执行：

```text
.\.venv\Scripts\python.exe -m ruff check .
```

结果：

```text
All checks passed!
```

已执行：

```text
.\.venv\Scripts\python.exe -m pytest -q
```

结果：

```text
24 passed, 1 warning
```

warning 来自 FastAPI/TestClient 依赖链中的 Starlette deprecation，不是业务失败。

## 11. API Key 说明

本阶段分子生成不需要千问或 DeepSeek API key。按照开发说明，LLM 不直接“想象”分子；分子生成应由化学工具链完成。千问和 DeepSeek key 更适合后续对话约束解析、自我反驳、报告生成等模块。

## 12. 后续建议

- 在目标 GPU 主机上构建镜像并保存 DiffDock、REINVENT4、AutoGrow4 的小规模真实运行记录。
- 为 REINVENT4 增加独立的靶点评分/RL 配置模板；在完成前继续把当前模式称为 prior sampling。
- 为 AutoGrow4 增加经过复核的受体和 docking grid 配置包。
- 增加显式多轮扩展开关，让已通过过滤的分子可以作为下一轮 seed。
- 给 CReM DB 路径增加启动时健康检查接口，方便前端显示工具链状态。
