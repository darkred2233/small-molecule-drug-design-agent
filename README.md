# Small Molecule Drug Design Agent

小分子药物设计 Agent 是一个面向早期小分子药物发现的可追踪、多智能体辅助系统。它把靶点资料、RAG 证据库、候选分子生成、结构校验、规则过滤、候选评估、外部计算工具细筛、自我反驳、排序、决策卡和项目报告串成一个端到端工作流，目标是让每个候选分子“为什么被推进、观察或淘汰”都有证据链可查。

> 注意：本项目用于教学、科研原型和计算流程探索，不能替代实验验证、临床判断或药物开发中的合规审查。

## 核心能力

- 项目创建、靶点选择、自然语言优化约束解析。
- 内置靶点库与种子配体库，支持 BRAF、EGFR、ALK 等 MVP 靶点扩展。
- 文献、专利、网页、PDF、DOCX、Markdown 等资料导入 RAG。
- 候选分子导入、基于种子配体/片段的候选生成。
- RDKit/Datamol 结构标准化、性质计算、规则过滤和构象生成。
- 候选评估支持三种深度：
  - `fast`：只跑 RDKit surrogate 快筛。
  - `external`：默认模式，先粗筛排序，再只对 Top N 调用 GNINA/AiZynthFinder 等外部工具细筛。
  - `full`：所有候选都尝试外部工具，适合小批量验收。
- GNINA/Vina/DiffDock、AiZynthFinder、Chemprop、REINVENT4、AutoGrow4 等 Docker 工具适配。
- 候选分子综合排序、反驳机制、DecisionCard、ReasoningTrace 和项目报告导出。
- React 前端：项目创建、流程运行、实时进度、候选分子卡片、性质/对接/ADMET/合成证据展示。

## 仓库结构

```text
.
├── apps/web/                 # React + Vite 前端
├── src/medagent/             # FastAPI 后端、服务层、领域模型、RAG、工具适配
├── tests/                    # pytest 测试
├── docker/                   # 计算工具 Dockerfile：Vina/Chemprop/DiffDock/REINVENT4/AiZynthFinder 等
├── docs/                     # 构建记录、模块说明、数据库初始化 SQL
├── scripts/                  # 数据扩展、Docker 工具构建/检查、RAG 导入脚本
├── database/                 # 数据库说明；真实数据库快照默认不提交
├── student_tasks/            # BRAF 示例复核任务包，不依赖完整环境
├── docker-compose.yml        # 后端 API、PostgreSQL/pgvector、MinIO、可选工具镜像
├── Dockerfile                # 后端 API 容器
└── pyproject.toml
```

## 环境要求

基础开发环境：

- Python 3.11 或更高版本。
- Node.js 18 或更高版本，建议 Node.js 20。
- pnpm，用于前端依赖安装。
- Docker Desktop，用于 PostgreSQL/pgvector、MinIO 和计算工具容器。

可选化学工具：

- RDKit/Datamol：本地快速结构校验和 surrogate 计算。
- GNINA/Vina/DiffDock：分子对接与姿态评估。
- AiZynthFinder：逆合成路线可行性评估。
- Chemprop/ADMET-AI：ADMET 预测。
- REINVENT4/AutoGrow4/CReM：候选分子生成或局部优化。

## 快速启动：本地开发模式

适合开发、调试和课堂演示。默认使用 SQLite，启动最快。

```powershell
git clone https://github.com/darkred2233/small-molecule-drug-design-agent.git
cd small-molecule-drug-design-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,rag]"

$env:PYTHONPATH="src"
python -m uvicorn medagent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

打开：

- 后端首页：http://127.0.0.1:8000/
- 中文接口说明：http://127.0.0.1:8000/docs
- Swagger 调试页：http://127.0.0.1:8000/swagger
- 健康检查：http://127.0.0.1:8000/health

## 前端启动

另开一个终端：

```powershell
cd apps\web
corepack enable
pnpm install
pnpm dev
```

默认前端地址：

- http://127.0.0.1:3000

Vite 已配置代理，前端 `/api/*` 会转发到 `http://127.0.0.1:8000`。

## Docker 部署：API + PostgreSQL + MinIO

适合更完整的复现环境。该模式会用 Docker 启动后端 API、PostgreSQL/pgvector 和 MinIO。

1. 准备环境变量：

```powershell
copy .env.example .env
```

如果没有 DashScope 或远程 rerank key，可以先把 `.env` 中的远程 RAG 开关设为 false，系统会使用本地 deterministic embedding/rerank fallback：

```env
MEDAGENT_RAG_USE_REMOTE_EMBEDDINGS=false
MEDAGENT_RAG_USE_REMOTE_RERANK=false
```

2. 启动基础服务和 API：

```powershell
docker compose up -d --build api postgres minio
```

3. 查看服务状态：

```powershell
docker compose ps
docker compose logs -f api
```

4. 访问：

- API：http://127.0.0.1:8000
- Swagger：http://127.0.0.1:8000/swagger
- MinIO 控制台：http://127.0.0.1:9001

默认 MinIO 账号在 `docker-compose.yml` 中是：

```text
medagent / medagent-secret
```

停止服务：

```powershell
docker compose down
```

连数据卷一起删除：

```powershell
docker compose down -v
```

## Docker 计算工具部署

外部计算工具以 Docker 镜像方式接入。候选评估时，后端会根据工具可用性决定使用真实外部工具，或回退到 RDKit surrogate。

构建核心工具：

```powershell
.\scripts\build_docker_tools.ps1 core
```

核心工具包括：

- GNINA：外部 docking。
- AutoDock Vina：外部 docking fallback。
- Chemprop：ADMET 预测。

构建全部工具：

```powershell
.\scripts\build_docker_tools.ps1 all
```

全部工具包括：

- `gnina`
- `vina`
- `chemprop`
- `diffdock`
- `reinvent4`
- `autogrow4`
- `aizynthfinder`

如果 Docker Hub 访问慢，可以先配置 Docker Desktop 镜像源，或运行：

```powershell
setup_and_build.bat
```

检查工具状态：

```powershell
check_docker_tools.bat
python scripts\check_tools.py --verbose --test
```

说明：

- 这些工具通常不是常驻 Web 服务，而是由后端适配器按需通过 Docker 镜像执行。
- 如果 Docker Desktop 没有启动，`external` 和 `full` 模式会回退到 surrogate 结果，并在 DecisionCard 中标记外部工具未使用或待接入。
- `external` 是推荐默认模式：先粗筛，再只对 Top N 细筛，速度和可信度比较平衡。

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

模式区别：

| 模式 | 速度 | 外部工具调用 | 适用场景 |
|---|---:|---|---|
| `fast` | 最快 | 不调用 GNINA/AiZynthFinder | 大批量粗筛、调试流程 |
| `external` | 中等 | 只对 Top N 调用 | 默认推荐，适合真实候选评估 |
| `full` | 最慢 | 所有候选都尝试调用 | 小批量最终验收 |

## RAG 数据扩展

导入本地资料后构建 RAG：

```powershell
$env:PYTHONPATH="src"
python scripts\collect_literature_patent_rag.py --help
python scripts\expand_builtin_knowledge.py --help
```

API 侧常用流程：

1. `POST /projects/{project_id}/files` 上传 PDF/DOCX/Markdown/文本。
2. `POST /projects/{project_id}/ingest` 解析并切块入库。
3. `POST /projects/{project_id}/rag/query` 检索项目证据。
4. 获取论文和专利后，重新运行 RAG 构建，让新资料进入当前项目的 evidence chain。

## 推荐端到端流程

1. 创建项目，选择靶点和生成策略。
2. 上传靶点资料、专利、论文或已有实验数据。
3. 构建项目 RAG。
4. 导入或生成候选分子。
5. 运行结构校验和规则过滤。
6. 运行候选评估，推荐使用 `external + Top N`。
7. 生成排序、DecisionCard 和 ReasoningTrace。
8. 查看反驳机制给出的风险和不确定性。
9. 导出项目报告。
10. 根据报告进行局部优化或人工复核。

## 常用 API

| 功能 | 接口 |
|---|---|
| 创建项目 | `POST /projects` |
| 自然语言约束解析 | `POST /projects/{project_id}/chat` |
| 上传文件 | `POST /projects/{project_id}/files` |
| RAG 入库 | `POST /projects/{project_id}/ingest` |
| RAG 查询 | `POST /projects/{project_id}/rag/query` |
| 查询种子配体 | `GET /projects/{project_id}/seed-ligands` |
| 导入候选分子 | `POST /projects/{project_id}/molecules/import-seeds` |
| 生成候选分子 | `POST /projects/{project_id}/molecules/generate` |
| 结构校验 | `POST /projects/{project_id}/molecules/validate` |
| 规则过滤 | `POST /projects/{project_id}/molecules/filter-rules` |
| 受体准备 | `POST /projects/{project_id}/receptors/prepare` |
| 候选评估 | `POST /projects/{project_id}/candidate-assessment/run` |
| 排名生成 | `POST /projects/{project_id}/rankings/generate` |
| 决策卡生成 | `POST /projects/{project_id}/decision-cards/generate` |
| 工具状态 | `GET /tools/status` |

## 测试与质量检查

后端测试：

```powershell
$env:PYTHONPATH="src"
python -m pytest
python -m ruff check .
```

前端检查：

```powershell
cd apps\web
pnpm lint
pnpm build
```

Docker 配置检查：

```powershell
docker compose config
```

## 本地数据与 Git 提交注意事项

默认不提交这些内容：

- `.env`
- `.venv/`
- `.local/`
- `data/`
- `logs/`
- `database/*.db`
- `*.sqlite`
- Docker/前端构建产物
- `node_modules/`

如果需要共享大模型、对接 pose、数据库快照或实验报告，请优先放到 release、云盘、对象存储或单独数据仓库中，不建议直接提交到 GitHub 主仓库。

## 相关文档

- `DATA_EXPANSION_GUIDE.md`：靶点、论文、专利、RAG 扩展指南。
- `TOOLS_QUICKSTART.md`：计算化学工具快速参考。
- `Docker工具检查指南.md`：Docker 工具镜像检查方法。
- `docs/RAG_BUILD.md`：RAG 模块构建说明。
- `docs/RULE_FILTERING_BUILD.md`：规则过滤构建说明。
- `docs/DECISION_CARD_BUILD.md`：决策卡构建说明。
- `GROUP_TASK_ASSIGNMENT_BRAF.md` 和 `student_tasks/`：BRAF 示例复核材料。

## 当前状态

当前版本已经完成 MVP 端到端链路：项目创建、资料入库、候选生成/导入、结构验证、规则过滤、候选评估、外部工具细筛、排序、反驳、决策卡、报告导出和前端流程展示。

后续推荐继续加强：

- 扩展更多靶点的高质量论文、专利和已知配体。
- 校准 docking、ADMET、合成可及性和综合排序阈值。
- 为更多真实项目沉淀可复现实验包。
- 把外部 ADMET、DiffDock、REINVENT4/AutoGrow4 的生产级配置继续补齐。
