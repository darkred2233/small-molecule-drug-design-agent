# Small Molecule Drug Design Agent

面向早期小分子药物发现的可追踪多智能体工作台。

本项目把靶点资料、候选分子生成、结构校验、规则过滤、ADMET 预测、分子对接、逆合成可行性、RAG 证据检索、自我反驳、综合排序、决策卡和项目报告串成一条端到端流程。目标不是替代实验验证，而是帮助科研和教学团队更快形成“为什么推进这个分子、为什么淘汰那个分子、证据来自哪里”的可复核记录。

> 重要说明：本项目用于教学、科研原型和计算流程探索。任何候选分子的活性、安全性、可合成性和成药性结论都需要实验、临床和合规流程验证。

## 项目特点

- 可追踪工作流：每个阶段都会产生结构化结果、标签、warnings、证据链接或 agent run 记录。
- 多策略候选生成：支持基于种子分子的 REINVENT4、CReM、AutoGrow4 风格生成策略，以及内置靶点配体库 fallback。
- 结构与规则校验：支持 RDKit/Datamol 结构标准化、描述符计算、Lipinski/Veber/PAINS/Brenk 等规则过滤。
- 分子对接适配：支持 GNINA、AutoDock Vina、DiffDock 的本地或 Docker 适配，并保留 adapter mode、pose 文件、raw output 和失败原因。
- ADMET 预测适配：支持 ADMET-AI/Chemprop、Chemprop CLI/Docker，以及 RDKit surrogate fallback。
- 逆合成评估：支持 AiZynthFinder 本地或 Docker 运行，无法运行真实工具时会明确标记 fallback。
- RAG 证据链：支持 PDF、DOCX、Markdown、文本、网页和内置靶点资料入库检索，可用于报告、反驳和决策卡。
- 自我反驳机制：围绕 docking、ADMET、合成可行性、证据缺口和排序风险生成反对意见。
- 前端工作台：React + Vite 界面支持项目创建、靶点选择、文件上传、流程运行、候选表、证据抽屉和报告查看。
- Docker 工具链：提供 API、PostgreSQL/pgvector、MinIO 以及外部计算工具镜像的构建和检查脚本。

## 推荐使用场景

- 药物化学或计算药物设计课程演示。
- 小分子优化流程的原型验证。
- 需要保留证据链和决策依据的候选分子筛选。
- 比较不同生成策略、过滤策略和外部工具组合。
- 为真实项目准备可复核的计算报告草稿。

不推荐直接用于：

- 临床决策。
- 无实验验证的候选分子推进。
- 不受信任网络环境中的公开计算服务。
- 没有隔离措施的 Docker socket 暴露部署。

## 系统架构

```text
React Web UI
    |
    | REST API
    v
FastAPI application
    |
    +-- Domain schemas and database models
    +-- Pipeline orchestrator
    +-- Agent layer
    |   +-- Target agent
    |   +-- SAR agent
    |   +-- Generator agent
    |   +-- Ranker agent
    |   +-- Self-refutation agent
    |   +-- Advisor/report agents
    |
    +-- Service layer
    |   +-- File ingestion and RAG indexing
    |   +-- Molecule import/generation/validation
    |   +-- Rule filtering
    |   +-- Receptor preparation
    |   +-- Docking adapters
    |   +-- ADMET adapters
    |   +-- Synthesis workflow
    |   +-- Candidate assessment/ranking
    |   +-- Decision cards/reporting
    |
    +-- Storage
        +-- SQLite for local development
        +-- PostgreSQL + pgvector for Docker/server mode
        +-- Local filesystem or MinIO for uploaded files and artifacts
```

## 目录结构

```text
.
├── apps/web/                 # React + Vite 前端
├── src/medagent/             # 后端主代码
│   ├── agents/               # 目标分析、SAR、排序、自我反驳、报告等 agent
│   ├── api/                  # FastAPI app 和 API router
│   ├── core/                 # 配置和运行环境
│   ├── data/                 # 内置靶点、药物库、数据采集器
│   ├── db/                   # SQLAlchemy models/session
│   ├── domain/               # Pydantic schema 和领域对象
│   ├── llm/                  # LLM 客户端
│   ├── pipeline/             # 流程编排、任务、恢复策略
│   ├── rag/                  # chunking、embedding、retrieval、rerank
│   ├── reporting/            # 决策卡、表格、PDF/项目报告
│   └── services/             # 药物设计核心服务和外部工具适配
├── tests/                    # pytest 测试
├── configs/                  # 工具、模型、过滤、打分配置
├── docker/                   # 外部计算工具 Dockerfile
├── infra/                    # 部署和基础设施脚本
├── migrations/               # SQLite schema 增量迁移
├── scripts/                  # 工具检查、数据扩展、RAG 构建等脚本
├── student_tool_runs/        # BRAF 示例复核材料
├── docs/                     # 模块构建记录和设计文档
├── docker-compose.yml        # API + Postgres + MinIO + 工具服务
├── Dockerfile                # 后端 API 镜像
├── pyproject.toml            # Python package 和依赖
└── config.yaml               # 本地运行配置
```

## 核心工作流

1. 创建项目并选择靶点，例如 BRAF、EGFR、ALK 或自定义靶点。
2. 上传文献、专利、实验数据、PDB、SMILES、SDF、CSV 等资料。
3. 构建项目 RAG 索引，形成可检索证据库。
4. 导入已知配体或从内置靶点库生成 seed molecules。
5. 使用 REINVENT4/CReM/AutoGrow4 风格策略生成候选分子。
6. 使用 RDKit/Datamol 做结构校验、标准化、描述符计算和构象生成。
7. 使用规则过滤移除明显不合格候选。
8. 运行候选评估：
   - docking：GNINA/Vina/DiffDock 或 surrogate fallback。
   - ADMET：ADMET-AI/Chemprop 或 RDKit surrogate fallback。
   - synthesis：AiZynthFinder 或启发式 fallback。
9. 运行自我反驳，识别证据缺口、过拟合风险、ADMET 风险和合成风险。
10. 生成综合排序、DecisionCard、ReasoningTrace 和项目报告。
11. 人工复核候选，决定推进、观察、修改或淘汰。

## 环境要求

基础开发环境：

- Python 3.11 或更高版本。
- Node.js 18 或更高版本，推荐 Node.js 20。
- pnpm，用于前端依赖管理。
- Docker Desktop，用于 PostgreSQL/pgvector、MinIO 和外部计算工具。

推荐化学工具：

- RDKit/Datamol：结构校验、描述符、指纹和 surrogate 计算。
- Meeko/Gemmi：Vina 输入准备和受体处理。
- GNINA 或 AutoDock Vina：分子对接。
- DiffDock：深度学习 docking。
- ADMET-AI/Chemprop：ADMET 预测。
- AiZynthFinder：逆合成路线搜索。
- REINVENT4、AutoGrow4、CReM：候选分子生成和优化。

## 快速启动：本地开发模式

本地开发默认可以使用 SQLite，适合调试和课堂演示。

```powershell
git clone https://github.com/darkred2233/small-molecule-drug-design-agent.git
cd small-molecule-drug-design-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,chem,rag]"

$env:PYTHONPATH="src"
python -m uvicorn medagent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

常用后端地址：

- API 首页：http://127.0.0.1:8000/
- Swagger：http://127.0.0.1:8000/swagger
- OpenAPI 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

启动前端：

```powershell
cd apps\web
corepack enable
pnpm install
pnpm dev
```

默认前端地址：

- http://127.0.0.1:3000

前端 Vite 已配置代理，`/api/*` 会转发到 `http://127.0.0.1:8000`。

## Docker 部署

Docker 模式适合更完整的复现环境，会启动 API、PostgreSQL/pgvector 和 MinIO。

```powershell
copy .env.example .env
docker compose up -d --build api postgres minio
docker compose ps
docker compose logs -f api
```

访问地址：

- API：http://127.0.0.1:8000
- Swagger：http://127.0.0.1:8000/swagger
- MinIO 控制台：http://127.0.0.1:9001

停止服务：

```powershell
docker compose down
```

谨慎清理数据卷。只有在确认 PostgreSQL、MinIO 和工具缓存数据都不再需要时，才执行：

```powershell
docker compose down -v
```

## 外部计算工具

外部计算工具通过本地可执行文件或 Docker 镜像接入。系统会根据工具可用性选择真实工具或明确标记 fallback。

检查工具状态：

```powershell
python scripts\check_tools.py --verbose --test
```

构建核心工具：

```powershell
.\scripts\build_docker_tools.ps1 core
```

构建全部工具：

```powershell
.\scripts\build_docker_tools.ps1 all
```

工具范围：

- `gnina`
- `vina`
- `chemprop`
- `diffdock`
- `reinvent4`
- `autogrow4`
- `aizynthfinder`

如果 Docker Desktop 未启动或工具镜像不可用，`external` 和 `full` 评估模式可能降级到 surrogate 结果。降级会写入 warnings、adapter mode 和结果标签，方便后续复核。

## 候选评估模式

候选评估接口：

```http
POST /projects/{project_id}/candidate-assessment/run
```

示例请求：

```json
{
  "assessment_mode": "external",
  "external_top_n": 5,
  "top_n": 20
}
```

模式说明：

| 模式 | 速度 | 外部工具调用 | 推荐场景 |
| --- | ---: | --- | --- |
| `fast` | 最快 | 不调用外部 docking/retrosynthesis | 大批量粗筛、流程调试 |
| `external` | 中等 | 先粗筛，再只对 Top N 调用外部工具 | 默认推荐，兼顾速度和可信度 |
| `full` | 最慢 | 对所有候选尝试外部工具 | 小批量最终复核 |

## RAG 与证据链

项目支持将文献、专利、网页、PDF、DOCX、Markdown 和文本资料导入 RAG 索引。

常见流程：

1. `POST /projects/{project_id}/files` 上传文件。
2. `POST /projects/{project_id}/ingest` 解析并切块入库。
3. `POST /projects/{project_id}/rag/query` 检索项目证据。
4. 在候选评估、反驳、决策卡和报告中引用证据。

辅助脚本：

```powershell
$env:PYTHONPATH="src"
python scripts\collect_literature_patent_rag.py --help
python scripts\expand_builtin_knowledge.py --help
python scripts\run_rag_collection.py --help
```

如果没有远程 embedding/rerank key，可以先关闭远程服务，系统会使用本地 deterministic fallback：

```env
MEDAGENT_RAG_USE_REMOTE_EMBEDDINGS=false
MEDAGENT_RAG_USE_REMOTE_RERANK=false
```

## 常用 API

| 功能 | 接口 |
| --- | --- |
| 创建项目 | `POST /projects` |
| 列出项目 | `GET /projects` |
| 删除项目 | `DELETE /projects/{project_id}` |
| 自然语言约束解析 | `POST /projects/{project_id}/chat` |
| 上传资料 | `POST /projects/{project_id}/files` |
| 构建 RAG | `POST /projects/{project_id}/ingest` |
| 查询 RAG | `POST /projects/{project_id}/rag/query` |
| 查询内置靶点 | `GET /targets` |
| 查询 seed ligands | `GET /projects/{project_id}/seed-ligands` |
| 导入 seed ligands | `POST /projects/{project_id}/molecules/import-seeds` |
| 生成候选分子 | `POST /projects/{project_id}/molecules/generate` |
| 结构校验 | `POST /projects/{project_id}/molecules/validate` |
| 规则过滤 | `POST /projects/{project_id}/molecules/filter-rules` |
| 受体准备 | `POST /projects/{project_id}/receptors/prepare` |
| 候选评估 | `POST /projects/{project_id}/candidate-assessment/run` |
| 综合排序 | `POST /projects/{project_id}/rankings/generate` |
| 决策卡生成 | `POST /projects/{project_id}/decision-cards/generate` |
| 项目报告 | `GET /projects/{project_id}/report` |
| 工具状态 | `GET /tools/status` |

## 配置

主要配置来源：

- `.env`：本地密钥、数据库、对象存储和远程模型开关。不要提交。
- `.env.example`：可提交的配置模板。
- `config.yaml`：项目运行配置。
- `configs/tools.yaml`：工具镜像、路径和运行参数。
- `configs/models.yaml`：模型配置。
- `configs/filters.yaml`：过滤规则。
- `configs/scoring.yaml`：排序和打分权重。

常见环境变量：

```env
MEDAGENT_DATABASE_URL=sqlite:///./database/medagent.db
MEDAGENT_STORAGE_DIR=.local/storage
MEDAGENT_RAG_USE_REMOTE_EMBEDDINGS=false
MEDAGENT_RAG_USE_REMOTE_RERANK=false
MEDAGENT_DASHSCOPE_API_KEY=
MEDAGENT_DEEPSEEK_API_KEY=
```

## 测试与质量检查

后端：

```powershell
$env:PYTHONPATH="src"
python -m pytest
python -m ruff check .
```

前端：

```powershell
cd apps\web
pnpm lint
pnpm build
pnpm test
pnpm test:e2e
```

Docker 配置检查：

```powershell
docker compose config
```

## 示例材料

`student_tool_runs/` 提供 BRAF 示例复核材料，包括：

- 输入 payload。
- baseline CSV。
- receptor/ligand/pose 示例文件。
- AiZynthFinder route 示例。
- 学生复核结果模板。

这些材料用于教学、演示和回归检查，不代表真实项目的最终候选推荐。

## 数据与安全边界

默认不提交以下内容：

- `.env`
- `.venv/`
- `.local/`
- `data/`
- `logs/`
- `database/*.db`
- `*.sqlite`
- Docker/前端构建产物
- `node_modules/`
- 测试报告和 coverage 产物

如果需要共享大模型、docking pose、大型数据库快照或完整实验报告，优先使用 release、对象存储、网盘或单独数据仓库，不建议直接提交到主代码仓库。

Docker 模式下如果 API 容器挂载 Docker socket，就具备较高宿主机权限。只应在可信本机或隔离服务器使用，不要把该 API 直接暴露到不受信任网络。

## 开发路线

短期优先级：

- 扩展更多靶点的高质量文献、专利和已知配体资料。
- 继续校准 docking、ADMET、合成可及性和综合排序阈值。
- 增强外部工具失败时的可解释 warnings 和 UI 展示。
- 完善 Docker GPU 工具链和 DiffDock/REINVENT4/AutoGrow4 的生产配置。
- 补充更多真实项目复现实验包。

中长期方向：

- 更系统的 SAR group 和 matched molecular pair 分析。
- 与实验反馈闭环结合，支持 assay 结果回流。
- 更严格的 provenance 和 audit trail。
- 多轮 lead optimization 策略推荐。
- 面向团队协作的权限、任务和报告版本管理。

## 许可证与引用

本仓库目前是科研和教学原型。如果你计划在课程、论文、演示或内部项目中使用，请在报告中注明项目来源，并明确标注所有计算结果的工具来源和 fallback 状态。
