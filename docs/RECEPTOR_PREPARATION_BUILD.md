# Receptor / Pocket 准备模块开发记录

日期：2026-07-09

本次完成 Docking 前置的 receptor / pocket 准备模块。目标是把 receptor 文件、binding site、grid box 和 Vina 输入准备纳入项目数据，而不是在候选评估时临时手填路径。

## 当前能力

新增服务：

```text
src/medagent/services/receptor_preparation.py
```

已支持：

- 从已上传文件 `source_file_id` 准备 receptor。
- 从本地 `receptor_file` 路径注册 receptor。
- 将 receptor 复制到项目存储目录：

```text
{storage_local_root}/{project_id}/receptors/{binding_site_id}/
```

- 创建或更新 `binding_sites` 记录。
- 保存 docking grid：
  - `grid_box.center`
  - `grid_box.size`
- 保存关键残基：
  - `key_residues`
- 解析 PDB/PDBQT 基础摘要：
  - title
  - atom_count
  - residue_count
  - chain_ids
- 检测 receptor 准备工具：
  - `obabel`
  - `mk_prepare_receptor.py`
  - `prepare_receptor4.py`
- 如果本机有 `obabel`，会尝试把 PDB receptor 转成 PDBQT，供 Vina 使用。
- 如果没有 PDBQT 准备工具，不伪造转换结果，只记录 warning，并继续保留 GNINA 可用的 receptor 文件。

## API

准备 receptor 和 pocket：

```http
POST /projects/{project_id}/receptors/prepare
```

请求示例：

```json
{
  "source_file_id": "FILE-xxxx",
  "grid_center": [1.0, 2.0, 3.0],
  "grid_size": [18.0, 18.0, 18.0],
  "key_residues": ["Met793", "Lys745"],
  "prepare_for_vina": true
}
```

也可以直接注册本地 receptor：

```json
{
  "receptor_file": "C:/path/to/receptor.pdb",
  "grid_center": [1.0, 2.0, 3.0],
  "grid_size": [18.0, 18.0, 18.0]
}
```

查询项目 binding sites：

```http
GET /projects/{project_id}/binding-sites
GET /projects/{project_id}/binding-sites/{binding_site_id}
```

## 与候选评估联动

`POST /projects/{project_id}/candidate-assessment/run` 现在可以只传：

```json
{
  "binding_site_id": "SITE-xxxx"
}
```

候选评估会自动从 `binding_sites` 读取：

- `prepared_receptor_file`，如果存在。
- 否则读取 `receptor_file`。
- `grid_box.center`
- `grid_box.size`
- `key_residues`

然后进入 GNINA/Vina 外部 Docking 适配层；如果工具或输入不满足，仍会降级到 `rdkit_surrogate_docking`。

## 数据库变化

扩展 `binding_sites`：

| 字段 | 作用 |
|---|---|
| `project_id` | 绑定项目 |
| `source_file_id` | 来源上传文件 |
| `receptor_file` | 项目内 receptor 文件 |
| `prepared_receptor_file` | PDBQT 等预处理 receptor 文件 |
| `preparation_status` | `uploaded` / `prepared` / `prepared_with_warnings` |
| `preparation_json` | 工具状态、warning、标签 |

`ensure_relational_schema` 已补轻量 schema 迁移，已有 SQLite 数据库启动时会自动补列。

## 文件变更

| 文件 | 作用 |
|---|---|
| `src/medagent/services/receptor_preparation.py` | receptor/pocket 准备服务 |
| `src/medagent/db/models.py` | 扩展 `BindingSite` 字段 |
| `src/medagent/services/database.py` | 为已有数据库补 `binding_sites` 新列 |
| `src/medagent/services/file_ingestion.py` | PDB ingest 与新 binding site 字段兼容 |
| `src/medagent/services/candidate_assessment.py` | 支持通过 `binding_site_id` 自动读取 receptor/grid |
| `src/medagent/domain/schemas.py` | 新增 receptor 准备请求和 binding site 读取 schema |
| `src/medagent/api/app.py` | 新增 receptor/pocket API |
| `tests/test_receptor_preparation.py` | 覆盖 receptor 准备和候选评估联动 |

## 已验证

```text
.\.venv\Scripts\python.exe -m pytest tests\test_receptor_preparation.py tests\test_candidate_assessment.py -q
```

结果：

```text
5 passed, 1 warning
```

```text
.\.venv\Scripts\python.exe -m ruff check .
```

结果：

```text
All checks passed!
```

## 下一步

建议下一步做综合排序模块：

- 汇总 docking、ADMET、合成可及性、规则过滤和约束匹配。
- 生成 `rankings` 记录。
- 输出 Top candidates。
- 为后续报告和 decision cards 提供统一候选分数。
