# 候选分子计算评估开发记录

日期：2026-07-09

本次实现开发说明中 Docking、ADMET、合成可及性阶段的 MVP 版本。模块命名为 `candidate_assessment`，避免把长期业务能力命名成里程碑编号。

## 1. 当前实现状态

已完成：

- 新增候选分子计算评估入口：

```http
POST /projects/{project_id}/candidate-assessment/run
```

- 新增四类结果查询接口：

```http
GET /projects/{project_id}/conformer-results
GET /projects/{project_id}/docking-results
GET /projects/{project_id}/admet-results
GET /projects/{project_id}/synthesis-routes
```

- 新增 `src/medagent/services/candidate_assessment.py`。
- 新增 `conformer_results` 表，用于记录 3D 构象生成和几何质量。
- `docking_results`、`admet_results`、`synthesis_routes` 采用 upsert 方式按 molecule 更新，重复运行不会堆重复结果。
- 每个阶段都会写入 `agent_runs`，保留 adapter mode、输入分子、工具状态和执行统计。

## 2. 工具边界

当前本机已可用：

- RDKit：用于 ETKDG 构象生成、MMFF/UFF 优化、descriptor、规则告警和 surrogate 评分。

当前未接入真实外部系统：

- GNINA / AutoDock Vina / DiffDock
- ADMETlab / Chemprop / DeepChem
- AiZynthFinder / ASKCOS

因此当前结果是可追踪的 RDKit surrogate，不伪装为真实 docking、真实 ADMETlab 或真实 retrosynthesis。结果标签和 warning 会保留：

```text
external_docking_adapter_pending
external_admet_adapter_pending
external_retrosynthesis_adapter_pending
```

## 3. API 请求示例

```json
{
  "molecule_ids": null,
  "max_molecules": 50,
  "binding_site_id": "SITE-0001",
  "grid_center": [23.4, 18.9, 44.2],
  "grid_size": [20, 20, 20],
  "key_residues": ["Met793", "Lys745", "Asp855"],
  "admet_properties": [
    "solubility",
    "permeability",
    "hERG",
    "CYP3A4",
    "CYP2D6",
    "Ames",
    "DILI",
    "Pgp_substrate"
  ],
  "max_synthesis_steps": 5,
  "prefer_buyable_building_blocks": true
}
```

如果不传 `molecule_ids`，默认评估当前项目中状态为以下值的分子：

```text
generated
imported_from_seed
structure_validated
passed_filter
candidate_assessed
```

## 4. 构象生成

adapter mode：

```text
rdkit_etkdg_conformer
```

计算内容：

- `conformer_generated`
- `conformer_count`
- `lowest_energy`
- `strain_energy`
- `rmsd_between_conformers`
- `chiral_centers`
- `undefined_stereo_centers`

标签：

```text
conformer_ok
conformer_failed
high_strain
stereo_undefined
too_many_stereocenters
```

## 5. Docking Surrogate

adapter mode：

```text
rdkit_surrogate_docking
```

当前以 RDKit descriptors 和构象质量估算：

- `vina_score`
- `cnn_score`
- `key_hbond_count`
- `clash_count`
- `pose_file`

`pose_file` 当前指向数据库构象记录：

```text
db://conformer_results/{molecule_id}
```

真实 GNINA/Vina 接入后可替换为 SDF/PDBQT pose 文件路径。

## 6. ADMET Surrogate

adapter mode：

```text
rdkit_surrogate_admet
```

当前计算：

- `hERG_probability`
- `hERG_risk`
- `Ames_probability`
- `Ames_risk`
- `solubility`
- `permeability`
- `admet_risk_score`

`raw_output` 额外包含 CYP、DILI、Pgp、BBB 等 surrogate 概率和风险标签。

## 7. 合成可及性 Surrogate

adapter mode：

```text
rdkit_surrogate_synthesis
```

当前计算：

- `SA_score`
- `SCScore`
- `route_found`
- `route_steps`
- `buyable_building_blocks`
- `route_confidence`
- `hazardous_reaction_count`
- `protecting_group_count`

`MoleculeProperty.sa_score` 会同步更新，供后续排序和报告复用。

## 8. 文件变更

| 文件 | 作用 |
|---|---|
| `src/medagent/services/candidate_assessment.py` | 构象、Docking、ADMET、合成可及性的统一候选评估服务 |
| `src/medagent/db/models.py` | 新增 `ConformerResult`，并为候选评估结果表增加按 molecule upsert 的唯一约束定义 |
| `src/medagent/domain/schemas.py` | 新增候选评估请求/响应和四类结果读取 schema |
| `src/medagent/api/app.py` | 新增运行和结果查询 API |
| `tests/test_candidate_assessment.py` | 覆盖候选评估运行、结果查询和幂等性 |
| `docs/CANDIDATE_ASSESSMENT_BUILD.md` | 本开发记录 |

## 9. 测试结果

已执行：

```text
.\.venv\Scripts\python.exe -m pytest tests\test_candidate_assessment.py -q
```

结果：

```text
2 passed, 1 warning
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
26 passed, 1 warning
```

warning 来自 FastAPI/TestClient 依赖链中的 Starlette deprecation，不是业务失败。

## 10. 后续真实工具接入建议

下一步优先级：

1. 接入 GNINA 或 AutoDock Vina，把 `rdkit_surrogate_docking` 替换为真实 docking adapter。
2. 增加蛋白结构准备和 binding site 配置表单/接口。
3. 接入 ADMETlab 或 Chemprop 批量预测，把 surrogate ADMET 作为 fallback。
4. 接入 AiZynthFinder，把 surrogate synthesis 替换为真实 retrosynthesis route。
5. 将候选评估结果纳入综合排序模块。
