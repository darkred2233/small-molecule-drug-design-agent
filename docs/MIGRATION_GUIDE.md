# 小分子药物设计 Agent 迁移与交接文档

版本：0.1.0
创建时间：2026-07-07
项目路径：`C:\Users\34471\Desktop\small-molecule-drug-design-agent`

## 1. 项目定位

本项目根据《小分子药物设计 Agent 开发文档 v2.1》构建，当前交付目标是 MVP M1 的可运行后端基础设施：

- FastAPI 服务骨架
- PostgreSQL/pgvector/MinIO 本地基础设施配置
- 核心关系数据库表模型
- 内置靶点-药物库种子数据
- 项目创建、对话约束解析、流程 dry-run、状态查询等核心 API
- Agent run 可追踪日志
- 标准化工具输出结构
- 基础自动化测试

当前版本不会伪造真实分子生成、Docking、ADMET 或合成路线结果。这些能力已留出接口和数据表，后续应通过独立工具适配器逐步接入。

## 2. 目录结构

```text
small-molecule-drug-design-agent/
  .env.example
  .gitignore
  docker-compose.yml
  pyproject.toml
  README.md
  docs/
    MIGRATION_GUIDE.md
    postgres-init.sql
  src/
    medagent/
      main.py
      agents/
        conversation.py
        orchestrator.py
      api/
        app.py
      core/
        config.py
      data/
        builtin_targets.py
      db/
        models.py
        session.py
      domain/
        schemas.py
      services/
        bootstrap.py
        ids.py
  tests/
    test_api.py
```

关键文件说明：

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | Python 包、依赖、pytest、ruff 配置 |
| `docker-compose.yml` | 本地 PostgreSQL + pgvector + MinIO |
| `.env.example` | 环境变量模板 |
| `src/medagent/api/app.py` | FastAPI 应用和所有 M1 API |
| `src/medagent/db/models.py` | 文档要求的核心数据库表模型 |
| `src/medagent/agents/conversation.py` | 自然语言约束解析的第一版规则实现 |
| `src/medagent/agents/orchestrator.py` | 端到端 Agent 流程 dry-run 编排 |
| `src/medagent/data/builtin_targets.py` | 内置靶点-药物种子数据 |
| `src/medagent/data/target_drug_library.json` | 已下载增强的内置靶点-药物关系库 |
| `database/medagent_seed.sqlite` | 可迁移 SQLite 种子库快照 |
| `tests/test_api.py` | API 行为测试 |

## 3. 最终目标结构

当前项目仍处于 MVP 早期，代码暂时集中在 `src/medagent` 下，方便快速验证。进入 RAG、Docking、ADMET、前端和后台任务之后，建议演进为下面的最终结构：

```text
small-molecule-drug-design-agent/
├─ apps/                                  # 所有可运行应用
│  ├─ api/                                # 后端 API 服务
│  │  ├─ main.py                          # FastAPI 启动入口
│  │  ├─ routes/                          # HTTP 路由分组
│  │  │  ├─ projects.py                    # 项目创建、状态、轮次
│  │  │  ├─ chat.py                        # 自然语言对话与约束
│  │  │  ├─ files.py                       # 文件上传、解析、导入
│  │  │  ├─ targets.py                     # 内置靶点库
│  │  │  ├─ molecules.py                   # 候选分子查询
│  │  │  ├─ pipeline.py                    # 启动完整 Agent 流程
│  │  │  └─ reports.py                     # 报告查看与导出
│  │  └─ dependencies.py                   # 数据库、权限、配置依赖注入
│  │
│  ├─ web/                                # 前端页面
│  │  ├─ pages/                            # 页面：项目、上传、结果、报告
│  │  ├─ components/                       # 表格、分子卡片、文件上传器
│  │  ├─ api-client/                       # 调后端 API 的客户端
│  │  └─ styles/                           # 主题和样式
│  │
│  └─ worker/                             # 后台任务进程
│     ├─ main.py                           # Worker 启动入口
│     ├─ queues.py                         # 队列定义
│     └─ jobs/                             # 长任务：解析、生成、Docking、ADMET
│
├─ packages/                              # 核心业务包
│  ├─ domain/                              # 领域模型与统一数据结构
│  │  ├─ project.py                        # ProjectSpec
│  │  ├─ molecule.py                       # MoleculeRecord
│  │  ├─ evidence.py                       # EvidenceRecord
│  │  ├─ agent_run.py                      # AgentRun
│  │  └─ constraints.py                    # OptimizationConstraint
│  │
│  ├─ database/                            # 数据库层
│  │  ├─ models.py                         # SQLAlchemy ORM 表模型
│  │  ├─ session.py                        # DB session
│  │  ├─ migrations/                       # Alembic 迁移
│  │  └─ repositories/                     # 数据访问封装
│  │
│  ├─ storage/                             # 文件存储层
│  │  ├─ local.py                          # 本地文件存储
│  │  ├─ minio.py                          # MinIO/S3 存储
│  │  └─ paths.py                          # 文件路径规范
│  │
│  ├─ ingestion/                           # 文件解析与知识导入
│  │  ├─ parsers/                          # 各类文件解析器
│  │  │  ├─ pdf.py                         # PDF 文本抽取
│  │  │  ├─ csv.py                         # 活性表解析
│  │  │  ├─ sdf.py                         # SDF 分子解析
│  │  │  ├─ smiles.py                      # SMILES 文件解析
│  │  │  └─ pdb.py                         # PDB 结构解析
│  │  ├─ normalizers.py                    # 字段归一化
│  │  └─ service.py                        # 导入编排
│  │
│  ├─ rag/                                 # RAG 系统
│  │  ├─ chunking.py                       # 文档切分
│  │  ├─ embedding.py                      # text-embedding-v4
│  │  ├─ retrieval.py                      # BM25 + pgvector 检索
│  │  ├─ rerank.py                         # qwen3-rerank
│  │  └─ evidence.py                       # evidence_id 生成与引用
│  │
│  ├─ chemistry/                           # 分子处理
│  │  ├─ standardize.py                    # SMILES 标准化
│  │  ├─ descriptors.py                    # MW、LogP、TPSA、HBD、HBA
│  │  ├─ filters.py                        # PAINS、Brenk、Lipinski
│  │  ├─ similarity.py                     # Tanimoto、新颖性、多样性
│  │  ├─ conformers.py                     # 3D 构象生成
│  │  └─ labels.py                         # 分子标签规则
│  │
│  ├─ agents/                              # 智能体实现
│  │  ├─ conversation_agent.py             # 对话理解
│  │  ├─ central_host_agent.py             # 中枢编排
│  │  ├─ knowledge_ingestion_agent.py      # 知识导入
│  │  ├─ rag_agent.py                      # 文献检索与证据
│  │  ├─ target_agent.py                   # 靶点/口袋分析
│  │  ├─ sar_agent.py                      # SAR 分析
│  │  ├─ generator_agent.py                # 候选分子生成
│  │  ├─ filter_agent.py                   # 规则过滤
│  │  ├─ docking_agent.py                  # Docking 调度
│  │  ├─ admet_agent.py                    # ADMET 调度
│  │  ├─ synthesis_agent.py                # 合成可及性评估
│  │  ├─ self_refutation_agent.py          # DeepSeek 反驳
│  │  ├─ ranker_agent.py                   # 综合排序
│  │  ├─ advisor_agent.py                  # 下一轮建议
│  │  └─ report_agent.py                   # 报告生成
│  │
│  ├─ llm/                                 # 大模型调用封装
│  │  ├─ qwen.py                           # qwen3.7-max / plus
│  │  ├─ deepseek.py                       # deepseek-v4-pro
│  │  ├─ prompts/                          # prompt 模板
│  │  └─ json_repair.py                    # JSON 输出修复
│  │
│  ├─ tools/                               # 外部科学计算工具适配器
│  │  ├─ base.py                           # 标准 ToolRunResult
│  │  ├─ rdkit_tool.py                     # RDKit/Datamol
│  │  ├─ gnina.py                          # GNINA docking
│  │  ├─ vina.py                           # AutoDock Vina
│  │  ├─ admetlab.py                       # ADMETlab
│  │  ├─ chemprop.py                       # Chemprop
│  │  └─ aizynthfinder.py                  # 合成路线
│  │
│  ├─ pipeline/                            # 主流程编排
│  │  ├─ graph.py                          # Agent 流程图
│  │  ├─ tasks.py                          # Prefect/Celery 任务
│  │  ├─ state.py                          # 流程状态机
│  │  └─ recovery.py                       # 失败重试和断点续跑
│  │
│  ├─ scoring/                             # 综合评分
│  │  ├─ normalization.py                   # 0-100 归一化
│  │  ├─ weights.py                        # 多目标权重
│  │  ├─ penalties.py                      # 风险扣分
│  │  └─ ranking.py                        # Top 20-50 排序
│  │
│  └─ reporting/                           # 报告生成
│     ├─ markdown.py                       # Markdown 报告
│     ├─ pdf.py                            # PDF 报告
│     ├─ tables.py                         # Top 分子表格
│     └─ molecule_cards.py                 # 单分子证据卡
│
├─ data/                                   # 项目数据，不放大文件进 git
│  ├─ seed/                                # 内置靶点-药物种子库
│  ├─ uploads/                             # 用户上传原始文件
│  ├─ parsed/                              # 解析后的中间文件
│  ├─ poses/                               # docking pose 文件
│  └─ reports/                             # 最终报告
│
├─ database/                               # 数据库快照和初始化资产
│  ├─ seed.sqlite                          # 轻量种子库
│  ├─ init.sql                             # PostgreSQL 初始化
│  └─ backups/                             # 数据库备份
│
├─ infra/                                  # 部署与基础设施
│  ├─ docker-compose.yml                   # 本地开发环境
│  ├─ docker/                              # 各服务 Dockerfile
│  ├─ minio/                               # MinIO 初始化
│  ├─ postgres/                            # PostgreSQL 扩展配置
│  └─ prefect/                             # Prefect 工作流配置
│
├─ configs/                                # 配置文件
│  ├─ models.yaml                          # 模型栈配置
│  ├─ scoring.yaml                         # 打分权重
│  ├─ filters.yaml                         # 分子过滤阈值
│  └─ tools.yaml                           # 外部工具路径和超时
│
├─ tests/                                  # 自动化测试
│  ├─ unit/                                # 单元测试
│  ├─ integration/                         # API/数据库/文件解析集成测试
│  ├─ fixtures/                            # 测试文件样例
│  └─ e2e/                                 # 端到端流程测试
│
├─ scripts/                                # 运维和数据脚本
│  ├─ download_pubchem_seed.py             # 下载 PubChem 种子数据
│  ├─ init_database.py                     # 初始化数据库
│  ├─ run_demo_project.py                  # 跑演示项目
│  └─ export_report.py                     # 导出报告
│
├─ docs/                                   # 人类阅读文档
│  ├─ architecture.md                      # 架构说明
│  ├─ api.md                               # API 说明
│  ├─ database.md                          # 数据库表说明
│  ├─ deployment.md                        # 部署说明
│  ├─ workflow.md                          # Agent 流程说明
│  └─ migration.md                         # 迁移文档
│
├─ .env.example                            # 环境变量模板
├─ pyproject.toml                          # Python 项目配置
├─ package.json                            # 如果前端独立构建，则放这里
└─ README.md                               # 项目总入口
```

最终结构的核心分层：

- `apps/`：真正启动的应用，包括 API、前端和后台 worker。
- `packages/`：可复用业务能力，包括数据库、RAG、分子处理、Agent、工具适配器和报告生成。
- `data/`：运行产生的数据，不建议把大文件提交进 git。
- `database/`：数据库快照、初始化脚本和备份。
- `infra/`：部署和基础设施配置。
- `configs/`：模型、评分、过滤阈值和工具超时等可调参数。
- `tests/`：单元测试、集成测试和端到端测试。
- `docs/`：给开发者、迁移者和使用者看的说明文档。

## 4. 环境要求

推荐环境：

- Python 3.11 或更高
- Docker Desktop
- PowerShell
- 可选：PostgreSQL 客户端工具

当前本机已用 Python 3.13.9 验证基础测试。生产环境建议固定 Python 3.11 或 3.12，避免科学计算依赖在 3.13 上遇到 wheel 缺失。

## 4. 本地快速启动

进入项目：

```powershell
cd C:\Users\34471\Desktop\small-molecule-drug-design-agent
```

创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

启动 API：

```powershell
python -m uvicorn medagent.main:app --reload --host 127.0.0.1 --port 8000
```

访问：

- Swagger API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

默认数据库是 SQLite：`./.local/medagent.db`。这适合快速验证 API，不适合生产或完整 MVP。

## 5. 使用 PostgreSQL 和 MinIO

启动基础设施：

```powershell
docker compose up -d
```

服务端口：

| 服务 | 地址 | 默认账号 |
|---|---|---|
| PostgreSQL | `localhost:5432` | `medagent / medagent` |
| MinIO API | `localhost:9000` | `medagent / medagent-secret` |
| MinIO Console | `http://localhost:9001` | `medagent / medagent-secret` |

复制环境变量：

```powershell
Copy-Item .env.example .env
```

确认 `.env` 中数据库地址：

```text
MEDAGENT_DATABASE_URL="postgresql+psycopg://medagent:medagent@localhost:5432/medagent"
```

注意：如果使用 PostgreSQL，需要安装 psycopg：

```powershell
python -m pip install "psycopg[binary]"
```

当前 `pyproject.toml` 没有默认安装 `psycopg`，是为了让 SQLite 快速启动更轻。迁移到 PostgreSQL 时建议把它加入依赖。

## 6. 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `MEDAGENT_APP_NAME` | FastAPI 应用名称 | `Small Molecule Drug Design Agent` |
| `MEDAGENT_DATABASE_URL` | SQLAlchemy 数据库地址 | `sqlite:///./.local/medagent.db` |
| `MEDAGENT_STORAGE_ENDPOINT` | MinIO/S3 endpoint | `localhost:9000` |
| `MEDAGENT_STORAGE_ACCESS_KEY` | MinIO access key | `medagent` |
| `MEDAGENT_STORAGE_SECRET_KEY` | MinIO secret key | `medagent-secret` |
| `MEDAGENT_STORAGE_BUCKET` | 文件桶名 | `medagent-files` |
| `MEDAGENT_QWEN_REASONING_MODEL` | 中枢推理模型 | `qwen3.7-max` |
| `MEDAGENT_QWEN_TASK_MODEL` | 普通任务模型 | `qwen3.7-plus` |
| `MEDAGENT_DEEPSEEK_REFUTATION_MODEL` | 反驳模型 | `deepseek-v4-pro` |
| `MEDAGENT_EMBEDDING_MODEL` | 向量模型 | `text-embedding-v4` |
| `MEDAGENT_RERANK_MODEL` | 重排序模型 | `qwen3-rerank` |

## 7. API 清单

当前已实现或占位的接口：

| 方法 | 路径 | 状态 | 说明 |
|---|---|---|---|
| `GET` | `/health` | 已实现 | 健康检查 |
| `GET` | `/database/summary` | 已实现 | 查询关系数据库摘要 |
| `GET` | `/builtin-targets` | 已实现 | 获取内置靶点列表 |
| `GET` | `/builtin-targets/{target_id}` | 已实现 | 获取靶点详情和代表药物 |
| `POST` | `/projects` | 已实现 | 创建项目 |
| `POST` | `/projects/{project_id}/chat` | 已实现 | 解析自然语言约束并记录对话 |
| `POST` | `/projects/{project_id}/files` | 占位 | 记录上传文件，真实 MinIO 存储待 M2 接入 |
| `POST` | `/projects/{project_id}/ingest` | 占位 | 创建知识导入 Agent run |
| `POST` | `/projects/{project_id}/run` | dry-run | 注册完整 Agent 流程步骤 |
| `POST` | `/projects/{project_id}/rounds` | dry-run | 启动新一轮 dry-run |
| `POST` | `/projects/{project_id}/advisor/apply` | 占位 | 应用 Advisor 建议，待 M6 |
| `GET` | `/projects/{project_id}/status` | 已实现 | 查询流程状态和 Agent runs |
| `GET` | `/projects/{project_id}/molecules` | 已实现 | 查询候选分子，目前通常为空 |
| `GET` | `/projects/{project_id}/constraints` | 已实现 | 查询结构化优化约束 |
| `GET` | `/projects/{project_id}/advice` | 已实现 | 查询 Advisor 建议，目前通常为空 |
| `GET` | `/projects/{project_id}/report` | 已实现 | 输出报告骨架 |

## 8. API 验证示例

创建项目：

```powershell
$project = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/projects `
  -ContentType "application/json" `
  -Body '{"name":"EGFR lead optimization","target_id":"TGT-EGFR","objective":"lower hERG while preserving quinazoline scaffold"}'

$project
```

提交自然语言约束：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/projects/$($project.project_id)/chat" `
  -ContentType "application/json" `
  -Body '{"message":"下一轮优先降低 hERG 风险，但保留 quinazoline 母核，只改 R6 位"}'
```

启动 dry-run 流程：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/projects/$($project.project_id)/run" `
  -ContentType "application/json" `
  -Body '{"mode":"dry_run"}'
```

查看报告骨架：

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/projects/$($project.project_id)/report"
```

## 9. 数据库表设计

`src/medagent/db/models.py` 已包含文档中的核心表：

| 表名 | 当前用途 |
|---|---|
| `projects` | 项目名称、靶点、目标、约束和状态 |
| `targets` | 内置或导入靶点 |
| `target_drug_library` | 靶点与代表药物关系 |
| `binding_sites` | 结合口袋、关键残基、grid box |
| `seed_ligands` | 项目种子配体 |
| `uploaded_files` | 上传文件元信息和解析状态 |
| `conversation_messages` | 用户/Agent 对话消息 |
| `optimization_constraints` | 自然语言转出的结构化约束 |
| `molecules` | 候选分子主表 |
| `molecule_properties` | 物化性质和 SA Score |
| `docking_results` | Docking 分数、pose 和标签 |
| `admet_results` | hERG/Ames/CYP/溶解度等结果 |
| `synthesis_routes` | 合成路线和可及性 |
| `rag_documents` | RAG 文档元数据 |
| `rag_chunks` | RAG 文本片段 |
| `evidence_links` | 分子结论与证据片段链接 |
| `agent_runs` | 每次 Agent 调用输入、输出和状态 |
| `critiques` | Self-Refutation 反驳结果 |
| `advisor_suggestions` | 下一轮优化建议 |
| `rankings` | 综合排序结果 |

迁移到生产数据库时建议引入 Alembic，不建议长期使用 `Base.metadata.create_all()` 管理 schema。当前为了 M1 快速启动，应用启动时会自动建表并导入内置靶点。

## 10. 内置靶点-药物库

当前种子数据在：

```text
src/medagent/data/builtin_targets.py
```

已包含：

- `TGT-EGFR`
- `TGT-ALK`
- `TGT-KRAS-G12C`

每个靶点包含：

- target id
- aliases
- UniProt ID
- species
- PDB IDs
- summary
- representative drugs
- mechanism
- indication
- SMILES
- evidence source

后续扩展 BTK、BRAF、JAK2、CDK4/6、PARP1、PI3K、HDAC 时，只需要按同样结构添加数据。服务启动时 `seed_builtin_targets()` 会幂等导入，不会重复插入同一靶点-药物组合。

## 11. Agent 流程当前状态

`PipelineOrchestrator` 当前会创建以下 dry-run Agent run：

1. `conversation_agent`
2. `knowledge_ingestion_agent`
3. `rag_builder_agent`
4. `target_agent`
5. `sar_agent`
6. `generator_agent`
7. `filter_agent`
8. `docking_agent`
9. `admet_agent`
10. `synthesis_agent`
11. `self_refutation_agent`
12. `ranker_agent`
13. `advisor_agent`
14. `report_agent`

这些 run 的价值是先把“可追踪流程骨架”落库。真正执行逻辑应该后续逐个 Agent 替换：

- LLM 类 Agent：接入百炼或 DeepSeek API。
- 工具类 Agent：通过统一 tool adapter 执行 RDKit、GNINA、ADMETlab、AiZynthFinder 等。
- RAG 类 Agent：接入 embedding、pgvector 检索和 rerank。

## 12. 标准化工具接口

文档要求工具输出统一封装。当前结构定义在：

```text
src/medagent/domain/schemas.py
```

`ToolRunResult` 字段：

| 字段 | 说明 |
|---|---|
| `tool_name` | 工具名，如 `gnina_docking` |
| `input` | 标准化输入 |
| `output` | 标准化输出 |
| `stdout` | 原始标准输出 |
| `stderr` | 原始错误输出 |
| `exit_code` | 退出码 |
| `runtime_seconds` | 运行耗时 |

后续所有外部工具都应先转换为这个结构，再写入 `agent_runs`、对应结果表和报告。

## 13. 测试与质量检查

运行测试：

```powershell
python -m pytest
```

当前测试覆盖：

- 内置靶点启动时导入
- 创建项目
- 对话解析 hERG、母核、R6 位约束
- dry-run 注册完整 Agent 流程

建议后续每个里程碑都补行为测试：

- M2：上传 PDF/CSV/SDF/PDB 后生成 `uploaded_files` 和解析状态。
- M3：RAG chunk 可检索，并返回 evidence id。
- M4：无效 SMILES 被标记为 `invalid_structure`。
- M5：工具超时不会中断全流程，只记录失败并跳过分子。
- M6：Self-Refutation 能改变至少部分分子排名。
- M7：报告中每个 Top 分子至少有 2 条证据。

## 14. 迁移到新机器的步骤

1. 复制整个项目目录到新机器。
2. 安装 Python 3.11 或 3.12。
3. 安装 Docker Desktop。
4. 在项目根目录创建虚拟环境。
5. 执行 `python -m pip install -e ".[dev]"`。
6. 如使用 PostgreSQL，执行 `docker compose up -d`。
7. 复制 `.env.example` 为 `.env`，修改数据库和 MinIO 地址。
8. 如果使用 PostgreSQL，安装 `psycopg[binary]`。
9. 执行 `python -m pytest`。
10. 启动 `python -m uvicorn medagent.main:app --reload --host 127.0.0.1 --port 8000`。
11. 打开 `/docs`，按 API 验证示例创建项目并启动 dry-run。

## 15. 后续开发路线

### M2：对话、上传和知识导入

建议实现：

- MinIO bucket 自动创建
- 上传文件真实写入 MinIO
- PDF 文本抽取
- CSV/Excel 结构化读取
- SDF/SMILES/PDB 文件识别
- `uploaded_files.parse_status` 状态机
- `knowledge_ingestion_agent` 真实执行

### M3：RAG 建库和检索

建议实现：

- 文档 chunk 切分
- `text-embedding-v4` 调用
- pgvector 存储
- BM25 + vector hybrid retrieval
- `qwen3-rerank`
- `EvidenceRecord` 和 `evidence_links`

### M4：分子生成和规则过滤

建议实现：

- RDKit/Datamol 标准化
- PAINS/Brenk 过滤
- MW、LogP、TPSA、HBD、HBA、SA Score
- 相似性、新颖性、多样性
- 分子状态流转

### M5：Docking、ADMET、合成

建议实现：

- GNINA 或 AutoDock Vina tool adapter
- ADMETlab/Chemprop adapter
- AiZynthFinder adapter
- 工具超时、失败、重试和跳过策略

### M6：反驳、Advisor 和排序

建议实现：

- DeepSeek Self-Refutation Agent
- Con Score
- 多目标 0-100 归一化
- Ranker Agent
- Advisor Agent 生成下一轮约束

### M7：报告和前端展示

建议实现：

- Top 20-50 报告
- 每个分子的证据链和反驳链
- 简单 Web 前端
- 报告导出 Markdown/PDF

## 16. 重要注意事项

- 不要让 LLM 直接凭空生成 SMILES 当最终结果；必须经过工具校验和数据库记录。
- 不要只用 docking score 决定最终排名。
- RAG 证据不足时，结论必须标记为 `hypothesis` 或低置信度。
- 所有工具调用必须记录 tool name、version、input hash、状态和时间。
- MinIO 只存大文件路径，数据库只存元信息和引用。
- RDKit cartridge 是否放进 PostgreSQL 要谨慎评估；更稳妥的方式是先用独立分子工具服务。
- 生产环境必须引入 Alembic 管理迁移，不要依赖自动建表。

## 17. 当前已知限制

- 文件上传接口只记录元信息，尚未写入 MinIO。
- `/ingest` 只创建 Agent run，尚未解析文件。
- `/run` 只支持 `dry_run`。
- 候选分子生成、Docking、ADMET、合成路线均未接入真实工具。
- RAG 表已建模，但 embedding、检索和 rerank 尚未实现。
- 当前自然语言约束解析是规则版，后续应替换为 `qwen3.7-plus` JSON 输出。

## 18. 交接检查清单

迁移完成后请确认：

- `python -m pytest` 通过。
- `/health` 返回 `{"status":"ok"}`。
- `/builtin-targets` 至少返回 EGFR、ALK、KRAS G12C。
- `POST /projects` 能创建项目。
- `POST /projects/{id}/chat` 能生成 `optimization_constraints`。
- `POST /projects/{id}/run` 能生成 14 个 Agent run。
- `.env` 中没有提交真实 API key。
- 如果使用 PostgreSQL，`vector` extension 已启用。
