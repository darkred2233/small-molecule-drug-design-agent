# 本次开发文档：关系数据库与种子库

日期：2026-07-07
范围：只做关系数据库、种子数据、初始化工具和迁移说明；RAG、向量化、检索、rerank 暂不开发。

## 1. 本次完成内容

这次开发把项目从“有数据库模型”推进到“有可迁移的关系数据库资产”：

- 扩充内置靶点-药物库到 MVP 文档要求的 10 个靶点。
- 从 PubChem PUG REST 下载代表药物的 `CID`、`CanonicalSMILES`、`IsomericSMILES`、`InChIKey`。
- 生成结构化种子数据文件：`src/medagent/data/target_drug_library.json`。
- 新增数据库摘要接口：`GET /database/summary`。
- 新增 CLI 初始化入口：`python -m medagent.cli db init`。
- 新增 CLI 快照入口：`python -m medagent.cli db snapshot`。
- 新增轻量 schema 兼容步骤，旧 SQLite 库会自动补齐 `target_drug_library` 新字段。
- 生成可迁移 SQLite 关系数据库快照：`database/medagent_seed.sqlite`。
- 新增测试覆盖数据库摘要和 CLI 快照生成。

## 2. 本次明确未做

- 未接入 RAG。
- 未创建 pgvector embedding 数据。
- 未开发 BM25/vector 检索。
- 未接入 qwen rerank。
- 未导入论文、专利、PDF 或网页知识。
- 未做真实候选分子生成、Docking、ADMET、合成路线。

这些能力后续可以基于本次关系数据库继续扩展。

## 3. 新增或修改的文件

| 文件 | 说明 |
|---|---|
| `src/medagent/data/seed_catalog.py` | MVP 10 个靶点和代表药物的人工维护目录 |
| `src/medagent/data/target_drug_library.json` | 下载增强后的关系库种子数据 |
| `scripts/download_pubchem_seed.py` | 从 PubChem 下载药物结构字段并生成 JSON |
| `src/medagent/services/database.py` | 数据库初始化、SQLite 快照和摘要服务 |
| `src/medagent/cli.py` | 命令行入口 |
| `database/medagent_seed.sqlite` | 可迁移 SQLite 种子库 |
| `database/README.md` | 数据库产物说明 |
| `tests/test_database_seed.py` | 数据库摘要和 CLI 快照测试 |
| `docs/RELATIONAL_DATABASE_BUILD.md` | 本文档 |

## 4. 当前内置靶点覆盖

| target_id | 靶点 | 代表药物数量 |
|---|---:|---:|
| `TGT-EGFR` | EGFR | 4 |
| `TGT-ALK` | ALK | 4 |
| `TGT-BRAF` | BRAF | 3 |
| `TGT-KRAS-G12C` | KRAS G12C | 2 |
| `TGT-JAK2` | JAK2 | 3 |
| `TGT-BTK` | BTK | 3 |
| `TGT-CDK4-6` | CDK4/6 | 3 |
| `TGT-PARP1` | PARP1 | 4 |
| `TGT-PI3K` | PI3K | 3 |
| `TGT-HDAC` | HDAC | 3 |

合计：10 个靶点，32 个代表药物。

## 5. 药物结构字段来源

药物结构字段通过 `scripts/download_pubchem_seed.py` 从 PubChem PUG REST 下载：

```text
https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{drug_name}/property/CanonicalSMILES,IsomericSMILES,InChIKey/JSON
```

写入字段：

| 字段 | 说明 |
|---|---|
| `pubchem_cid` | PubChem Compound ID |
| `smiles` | 当前等同于 `canonical_smiles` |
| `canonical_smiles` | PubChem CanonicalSMILES |
| `isomeric_smiles` | PubChem IsomericSMILES |
| `inchi_key` | PubChem InChIKey |
| `external_refs.pubchem` | PubChem compound URL |
| `evidence_source` | `MVP seed catalog + PubChem PUG REST` |

后续如果需要更高可信度，可以再补 ChEMBL、DrugBank 或供应商数据库字段。当前种子库的目的不是替代药化审查，而是给系统启动和后续分子处理提供关系数据库基础。

## 6. 数据库初始化方式

### 6.1 初始化默认数据库

默认使用 `.env` 或 `Settings` 中的数据库地址：

```powershell
$env:PYTHONPATH='src'
python -m medagent.cli db init
```

如果项目已通过 `pip install -e .` 安装，也可以使用：

```powershell
medagent db init
```

输出示例：

```json
{
  "target_count": 10,
  "drug_count": 32,
  "project_count": 0,
  "molecule_count": 0,
  "target_ids": ["TGT-ALK", "..."]
}
```

### 6.2 初始化指定 SQLite 数据库

```powershell
$env:PYTHONPATH='src'
python -m medagent.cli db init --database-url "sqlite:///C:/tmp/medagent.sqlite"
```

### 6.3 生成可迁移 SQLite 快照

```powershell
$env:PYTHONPATH='src'
python -m medagent.cli db snapshot --output database/medagent_seed.sqlite
```

当前已生成：

```text
database/medagent_seed.sqlite
```

这个文件包含 schema 和内置靶点-药物种子数据，可以直接复制到其他机器，用 SQLite 工具打开检查。

## 7. API 验证

启动服务：

```powershell
$env:PYTHONPATH='src'
python -m uvicorn medagent.main:app --host 127.0.0.1 --port 8000
```

查看数据库摘要：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/database/summary"
```

查看内置靶点：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/builtin-targets"
```

查看某个靶点详情：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/builtin-targets/TGT-EGFR"
```

## 8. 当前关系数据库表

当前仍沿用 M1 的核心 schema，并扩展了 `target_drug_library`：

| 表名 | 用途 |
|---|---|
| `projects` | 项目主表 |
| `targets` | 靶点主表 |
| `target_drug_library` | 靶点-药物关系库，本次重点扩充 |
| `binding_sites` | 结合口袋 |
| `seed_ligands` | 种子配体 |
| `uploaded_files` | 上传文件 |
| `conversation_messages` | 对话消息 |
| `optimization_constraints` | 优化约束 |
| `molecules` | 候选分子 |
| `molecule_properties` | 分子物化性质 |
| `docking_results` | Docking 结果 |
| `admet_results` | ADMET 结果 |
| `synthesis_routes` | 合成路线 |
| `rag_documents` | RAG 文档元信息，暂未使用 |
| `rag_chunks` | RAG 片段，暂未使用 |
| `evidence_links` | 证据链接，暂未使用 |
| `agent_runs` | Agent 运行日志 |
| `critiques` | 自我反驳记录 |
| `advisor_suggestions` | Advisor 建议 |
| `rankings` | 综合排名 |

`target_drug_library` 本次新增字段：

| 字段 | 说明 |
|---|---|
| `canonical_smiles` | 标准 SMILES |
| `isomeric_smiles` | 含立体信息的 SMILES |
| `inchi_key` | 结构指纹 |
| `pubchem_cid` | PubChem CID |
| `external_refs` | 外部链接 JSON |

## 9. PostgreSQL 迁移建议

本次快照使用 SQLite 是为了方便复制和检查。正式运行建议使用 PostgreSQL：

```powershell
docker compose up -d
Copy-Item .env.example .env
python -m pip install "psycopg[binary]"
$env:PYTHONPATH='src'
python -m medagent.cli db init --database-url "postgresql+psycopg://medagent:medagent@localhost:5432/medagent"
```

注意：

- PostgreSQL 初始化时会创建同样的关系表并导入同样的 10 个靶点、32 个药物。
- `docs/postgres-init.sql` 只启用 `pgvector`，但本次不写入向量数据。
- RDKit cartridge 暂不强依赖数据库扩展，后续更建议先用独立工具服务封装 RDKit。
- 当前轻量 schema 兼容只负责补齐本次新增的 `target_drug_library` 字段；正式生产迁移仍建议引入 Alembic。

## 10. 如何重新下载 PubChem 数据

如果想刷新 `target_drug_library.json`：

```powershell
$env:PYTHONPATH='src'
python scripts/download_pubchem_seed.py
```

刷新后重新生成 SQLite 快照：

```powershell
$env:PYTHONPATH='src'
python -m medagent.cli db snapshot --output database/medagent_seed.sqlite
```

再跑测试：

```powershell
python -m pytest tests/test_database_seed.py
python -m pytest
```

## 11. 验收结果

本次开发验收标准：

- `/database/summary` 返回 10 个靶点和 32 个药物。
- CLI 能创建指定 SQLite 数据库。
- `database/medagent_seed.sqlite` 已生成。
- 新增测试通过。
- RAG 没有被开发或接入。

当前验证命令：

```powershell
python -m pytest tests/test_database_seed.py
```

通过结果：

```text
2 passed
```
