# 本次开发文档：文件上传与关系库解析

日期：2026-07-07

范围：实现 M2 的文件上传、保存、解析和关系数据库入库。RAG、向量化、embedding、rerank 暂不接入。

## 1. 本次完成内容

本次开发把文件导入从“占位接口”推进到“可保存、可解析、可查询”的关系数据库流程：

- 上传文件真实保存到本地目录。
- 支持项目文件列表查询。
- 支持解析全部待处理文件。
- 支持重新解析单个文件。
- 支持查询单个文件解析结果。
- 支持查询解析得到的种子配体。
- SMILES/TXT、CSV、SDF 中的分子写入 `seed_ligands`。
- PDB 文件解析结构摘要，并在项目已有靶点时创建 `binding_sites` 记录。
- 每个文件解析状态写入 `uploaded_files.parse_status`。
- 每个文件解析摘要写入 `uploaded_files.metadata_json`。
- Knowledge Ingestion Agent run 现在会记录真实解析摘要。

## 2. 本次明确未做

- 未做 RAG。
- 未切分文档 chunk。
- 未调用 embedding 模型。
- 未写入 pgvector。
- 未做 rerank。
- 未抽取 PDF 正文。
- 未做 RDKit 结构合法性校验。
- 未把 seed ligand 自动提升为候选分子。

当前阶段的目标是先把用户资料稳定落盘、解析、入关系库，为后续 RAG 和分子工具链留出干净入口。

## 3. 新增或修改文件

| 文件 | 说明 |
|---|---|
| `src/medagent/services/file_ingestion.py` | 文件保存、解析和入库服务 |
| `src/medagent/api/app.py` | 新增文件列表、解析结果、重新解析、seed ligand 查询接口 |
| `src/medagent/domain/schemas.py` | 新增文件解析结果和 seed ligand 响应模型 |
| `src/medagent/core/config.py` | 新增本地上传根目录配置 |
| `tests/test_file_ingestion.py` | 文件上传与解析行为测试 |
| `docs/FILE_INGESTION_BUILD.md` | 本文档 |

## 4. 文件保存位置

默认本地保存根目录：

```text
./.local/uploads
```

实际路径格式：

```text
.local/uploads/{project_id}/{file_id}/{filename}
```

数据库中的 `uploaded_files.storage_path` 使用：

```text
local://{absolute_or_relative_path}
```

后续切换 MinIO 时，建议保留 `storage_path` 抽象，例如：

```text
minio://medagent-files/{project_id}/{file_id}/{filename}
```

这样解析服务只需要替换存取层，不必改变 API。

## 5. 支持的文件类型

### 5.1 SMILES / SMI / TXT

支持扩展名：

```text
.smi
.smiles
.txt
```

格式：

```text
CCO ethanol
c1ccccc1 benzene
```

解析规则：

- 每行第一个字段作为 `smiles`。
- 后续字段合并作为 `name`。
- 空行和 `#` 开头注释行会跳过。
- 每条记录写入 `seed_ligands`。

### 5.2 CSV

支持扩展名：

```text
.csv
```

识别字段：

| 字段候选 | 写入 |
|---|---|
| `smiles`, `SMILES`, `canonical_smiles`, `CanonicalSMILES` | `seed_ligands.smiles` |
| `name`, `Name`, `compound`, `compound_id` | `seed_ligands.name` |
| `activity_value`, `activity`, `IC50`, `Ki`, `Kd` | `seed_ligands.activity_value` |
| `activity_unit`, `unit`, `Unit` | `seed_ligands.activity_unit` |

示例：

```csv
name,smiles,activity_value,activity_unit
ligand_a,CCN,12.5,nM
ligand_b,CCCl,0.8,uM
```

### 5.3 SDF

支持扩展名：

```text
.sdf
```

解析规则：

- 以 `$$$$` 切分记录。
- 第一条非空行作为 `name`。
- 从 SDF property 中读取 `SMILES`、`smiles`、`CanonicalSMILES` 或 `canonical_smiles`。
- 有 SMILES 的记录写入 `seed_ligands`。

当前 SDF 解析是轻量解析，不做 mol block 到 SMILES 的化学转换。后续接入 RDKit 后，可以从结构块自动标准化生成 SMILES。

### 5.4 PDB

支持扩展名：

```text
.pdb
```

解析内容：

- `TITLE`
- ATOM/HETATM 数量
- residue 数量
- chain id 列表

写入：

- 解析摘要写入 `uploaded_files.metadata_json.pdb`。
- 如果项目有 `target_id` 且该靶点存在于 `targets` 表，会创建一条 `binding_sites` 记录。

当前不会自动识别真实结合口袋坐标和 grid box。后续可以接入 PDB 结构分析工具或由用户提供 pocket 参数。

## 6. 解析状态

`uploaded_files.parse_status` 当前使用：

| 状态 | 含义 |
|---|---|
| `uploaded` | 已上传，尚未解析 |
| `parsed` | 已解析成功 |
| `failed` | 解析失败或文件类型不支持 |

解析详情写入：

```text
uploaded_files.metadata_json
```

常见字段：

| 字段 | 含义 |
|---|---|
| `parser` | 使用的解析器 |
| `record_count` | 文件内解析记录数 |
| `seed_ligand_count` | 写入 seed_ligands 的数量 |
| `error_message` | 失败原因 |
| `pdb` | PDB 结构摘要 |
| `binding_site_created` | 是否创建 binding_sites 记录 |

## 7. 新增 API

### 7.1 上传文件

```http
POST /projects/{project_id}/files
```

表单字段：

```text
file
```

返回：

```json
{
  "file_id": "FILE-...",
  "filename": "seeds.smi",
  "file_type": "text/plain",
  "parse_status": "uploaded"
}
```

### 7.2 查看项目文件

```http
GET /projects/{project_id}/files
```

返回该项目所有上传文件和解析状态。

### 7.3 解析待处理文件

```http
POST /projects/{project_id}/ingest
```

会解析状态为 `uploaded` 或 `failed` 的文件。

返回示例：

```json
{
  "agent_run_id": "RUN-...",
  "status": "completed",
  "parsed_files": 1,
  "failed_files": 0,
  "seed_ligands_created": 2,
  "details": []
}
```

### 7.4 重新解析单个文件

```http
POST /projects/{project_id}/files/{file_id}/parse
```

会删除该文件上一次写入的 `seed_ligands`，再重新解析。

### 7.5 查看解析结果

```http
GET /projects/{project_id}/files/{file_id}/parse-result
```

返回：

```json
{
  "file_id": "FILE-...",
  "filename": "seeds.smi",
  "parse_status": "parsed",
  "metadata": {
    "parser": "smiles_text",
    "record_count": 2,
    "seed_ligand_count": 2
  }
}
```

### 7.6 查看种子配体

```http
GET /projects/{project_id}/seed-ligands
```

返回解析得到的 seed ligands。

## 8. 手动验证流程

启动服务：

```powershell
$env:PYTHONPATH='src'
python -m uvicorn medagent.main:app --host 127.0.0.1 --port 8000
```

创建项目：

```powershell
$project = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/projects" `
  -ContentType "application/json" `
  -Body '{"name":"EGFR 文件解析测试","target_id":"TGT-EGFR","objective":"导入 seed ligands"}'
```

上传文件：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/projects/$($project.project_id)/files" `
  -Form @{ file = Get-Item ".\example.smi" }
```

触发解析：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/projects/$($project.project_id)/ingest"
```

查看 seed ligands：

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/projects/$($project.project_id)/seed-ligands"
```

## 9. 测试覆盖

新增测试文件：

```text
tests/test_file_ingestion.py
```

覆盖：

- SMILES 文件上传和入库。
- CSV 活性值保留。
- PDB 结构摘要和 binding site 创建。
- 项目文件列表查询。

运行：

```powershell
python -m pytest tests/test_file_ingestion.py
python -m pytest
```

当前通过：

```text
4 passed in test_file_ingestion.py
```

## 10. 下一步建议

下一步可以继续做“轻量分子处理”：

- 对 `seed_ligands` 做 SMILES 基础校验。
- 标准化 SMILES。
- 去重。
- 写入 `molecules`。
- 计算简单性质占位字段。
- 为后续 RDKit/Datamol 接入留工具适配器。

这样 RAG 即使继续延后，分子数据链路也能先跑起来。
