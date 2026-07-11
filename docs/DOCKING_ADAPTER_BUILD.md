# Docking Adapter 开发记录

日期：2026-07-09

本次在 M5 候选评估模块中接入真实 Docking 工具适配层。实现重点是把 GNINA / AutoDock Vina 的命令封装、输出解析、工具检测和 RDKit surrogate 降级拆开，避免把估算结果伪装成真实 docking。

## 当前能力

新增模块：

```text
src/medagent/services/docking_adapters.py
```

已支持：

- `DockingToolRequest`：统一 receptor、ligand、grid、输出目录、超时等输入。
- `DockingToolResult`：统一真实工具结果、分数、pose 文件、stdout/stderr、warning 和 label。
- GNINA 命令构造与执行。
- AutoDock Vina 命令构造与执行。
- GNINA 输出解析：`Affinity`、`CNNscore`、`CNNaffinity`。
- Vina 输出解析：stdout 表格和 `REMARK VINA RESULT`。
- 工具选择：
  - GNINA 可用时优先使用 GNINA。
  - GNINA 不可用、Vina 可用且 receptor/ligand 都是 PDBQT 时使用 Vina。
  - 输入或工具不满足时返回 unavailable，候选评估服务自动降级到 RDKit surrogate。

## API 变化

`POST /projects/{project_id}/candidate-assessment/run` 新增可选字段：

```json
{
  "protein_file": "C:/path/to/prepared_receptor.pdb",
  "prepared_ligand_files": {
    "MOL-001": "C:/path/to/MOL-001.pdbqt"
  },
  "grid_center": [1.0, 2.0, 3.0],
  "grid_size": [18.0, 18.0, 18.0]
}
```

说明：

- `protein_file` 是预处理 receptor/protein 文件路径。
- GNINA 路径：如果只传 `protein_file`，服务会从分子 SMILES 自动生成临时 SDF ligand，并调用 GNINA。
- Vina 路径：Vina 需要 PDBQT 输入，建议通过 `prepared_ligand_files` 按 molecule_id 传入预处理 ligand PDBQT；`protein_file` 也应为 PDBQT。
- 如果没有安装 GNINA/Vina，或 receptor/grid/ligand 输入不满足要求，Docking 阶段仍会使用 `rdkit_surrogate_docking`，并在 summary warning 中说明原因。
- 当前推荐先调用 `POST /projects/{project_id}/receptors/prepare` 创建 `binding_site_id`，再在候选评估中只传 `binding_site_id`；服务会自动读取 receptor、grid 和 key residues。

## 结果标签

真实外部工具成功时，`docking_results.labels` 会包含：

```text
external_docking_adapter_used
gnina_adapter
gnina_external_docking
```

或：

```text
external_docking_adapter_used
vina_adapter
vina_external_docking
```

降级路径仍保留：

```text
external_docking_adapter_pending
rdkit_surrogate_docking
```

## 运行产物

服务会把临时 Docking 输入/输出放在：

```text
.local/candidate_assessment/{project_id}/ligands
.local/candidate_assessment/{project_id}/poses
```

这些属于本地运行产物，不需要进入迁移数据库。

## 文件变更

| 文件 | 作用 |
|---|---|
| `src/medagent/services/docking_adapters.py` | GNINA/Vina 适配层、命令构造、输出解析和执行封装 |
| `src/medagent/services/candidate_assessment.py` | 在 Docking 阶段优先尝试外部 adapter，失败后降级 surrogate |
| `src/medagent/domain/schemas.py` | 新增 `protein_file`、`prepared_ligand_files` 请求字段 |
| `src/medagent/api/app.py` | 转发新增 Docking 输入字段 |
| `tests/test_docking_adapters.py` | 覆盖 GNINA/Vina 解析、命令构造和工具选择 |
| `tests/test_candidate_assessment.py` | 覆盖 candidate assessment 使用 GNINA adapter 的 API 路径 |

## 已验证

```text
.\.venv\Scripts\python.exe -m pytest tests\test_docking_adapters.py tests\test_candidate_assessment.py -q
```

结果：

```text
8 passed, 1 warning
```

```text
.\.venv\Scripts\python.exe -m ruff check .
```

结果：

```text
All checks passed!
```

## 下一步

建议下一步做 receptor / pocket 准备模块：

- 管理 PDB/receptor 上传和准备状态。
- 保存 binding site、grid center、grid size。
- 为 Vina 增加正式的 PDBQT 准备链路。
- 把 receptor、ligand、pose 文件从 `.local` 运行目录迁入可迁移的项目存储结构。
