# Small Molecule Drug Design Agent

一个面向教学、科研原型和可追溯计算流程的小分子药物设计工作台。项目将靶点资料、受体结构、设计约束、候选分子生成、性质评估、对接、逆合成和轮次决策组织为可审计的项目工作流。

> 本项目的输出仅用于计算设计与研究探索，不构成药物活性、安全性、可合成性、临床有效性或监管结论。所有候选分子都需要结合实验、临床和合规流程独立验证。

## 功能概览

- 项目化管理：按靶点、研究目标、上传资料和轮次保存设计上下文。
- 结构工作流：导入 RCSB PDB 结构或项目自有 PDB，运行口袋预测、选择口袋并制备对接受体。
- 轮次策略：将自然语言目标整理为可编辑的结构化策略，确认后冻结为不可变的执行快照。
- 候选生成：支持 CReM 局部结构优化、TargetDiff 口袋条件生成和 AutoGrow4 受体引导搜索。
- 候选评估：整合结构标准化、基础理化性质、ADMET-AI、Vina/GNINA、AiZynthFinder 和规则过滤。
- 证据与报告：保存输入、工具版本、原始产物、哈希、执行记录和证据层级，支持项目与轮次复盘。
- Web 工作台：React 前端用于项目、策略、结构、候选分子、运行轮次和结果查看。

## 工作流

```text
创建项目与靶点
  -> 导入文献、SMILES/SDF/CSV 和受体结构
  -> 建立 RAG 证据库，选择结构与口袋
  -> 编写或生成轮次策略草稿
  -> 人工确认策略和种子分子
  -> 冻结执行快照并启动轮次
  -> 生成、评估、排序和自我质疑
  -> 审阅候选、证据与报告
  -> 选择下一轮种子并继续优化
```

确认后的每轮执行都会保存策略版本、策略哈希、已解析的种子分子、方法级输入和执行时间。运行过程不会用“模拟成功”的结果替代不可用的外部工具。

## 证据层级

| 层级 | 含义 |
| --- | --- |
| `L0` | 未执行、被阻塞、工具不可用或执行失败。 |
| `L1` | 规则或 RDKit 等本地代理计算，用于早期探索。 |
| `L2` | 可复现的本地工具或模型计算，并已保存可核验产物。 |
| `L3` | 实验结果或经校准的外部验证。 |

对接、生成、ADMET 和逆合成预测不会自动被解释为实验结论。缺少工具、模型、受体或校准数据时，系统应明确报告失败或未就绪状态。

## 仓库结构

```text
apps/web/                 React + Vite 前端
configs/                  模型、过滤、评分和本地工具配置
data/                     可分发的配置与小型示例数据
docs/                     设计说明、研究记录与实施文档
migrations/               数据库迁移脚本
scripts/                  本地安装、检查、数据收集和维护脚本
src/medagent/api/         FastAPI 应用与 HTTP 路由
src/medagent/agents/      生成、策略、对话和报告 Agent
src/medagent/db/          SQLAlchemy 模型与数据库会话
src/medagent/domain/      Pydantic 数据模型
src/medagent/pipeline/    RoundOrchestrator 与流程状态控制
src/medagent/services/    工具适配、评估、RAG、结构和持久化服务
student_tool_runs/        已纳入版本控制的教学/演示结果
tests/                    pytest 测试
```

## 快速开始

### 1. 后端环境

要求：Python 3.11 或更高版本。以下命令以 PowerShell 为例：

```powershell
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,chem,rag]"
Copy-Item .env.example .env
```

按需在 `.env` 中配置数据库地址、对象存储和模型服务密钥。`.env` 已被 Git 忽略，不能提交 API 密钥或生产凭据。

默认开发配置使用：

```dotenv
MEDAGENT_DATABASE_URL="sqlite:///./.local/medagent.db"
MEDAGENT_STORAGE_LOCAL_ROOT="./.local/uploads"
MEDAGENT_TOOLS_CONFIG="./configs/tools.yaml"
```

启动 API：

```powershell
$env:PYTHONPATH = "src"
python -m uvicorn medagent.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

服务启动后可访问：

- `http://127.0.0.1:8000/`：中文入口页
- `http://127.0.0.1:8000/docs`：项目内 API 文档
- `http://127.0.0.1:8000/swagger`：Swagger UI
- `http://127.0.0.1:8000/openapi.json`：OpenAPI 描述

### 2. 前端环境

要求：Node.js 18+，并使用项目锁定的 `pnpm` 依赖。

```powershell
cd apps\web
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

Vite 会输出本地访问地址。开发时前端通过 Vite 配置将 API 请求转发至后端。

### 3. 初始化数据库

应用启动时会创建关系表并写入内置靶点和资源包元数据。也可以使用 CLI 显式初始化：

```powershell
$env:PYTHONPATH = "src"
medagent db init
```

如需生成可移动的 SQLite 快照：

```powershell
$env:PYTHONPATH = "src"
medagent db snapshot --output database\medagent_seed.sqlite
```

`database/` 是本地运行目录；除 `database/README.md` 外，不应提交运行生成的数据库文件。

## 本地工具链

工具配置位于 `configs/tools.yaml`。其中的路径可被 `MEDAGENT_<TOOL>_COMMAND`、`MEDAGENT_<TOOL>_PYTHON` 或 `MEDAGENT_<TOOL>_WORKDIR` 环境变量覆盖，便于不同工作站使用不同安装位置。

```powershell
.\scripts\install_local_tools.ps1 -InstallWsl
.\.venv\Scripts\python.exe scripts\check_local_tools.py --json
```

当前工作流涉及的主要工具：

| 工具 | 用途 | 运行位置 |
| --- | --- | --- |
| RDKit / Datamol | 结构标准化、描述符、过滤与基础化学计算 | Windows Python |
| CReM | 基于种子分子的局部片段替换 | Windows Python |
| TargetDiff | 基于口袋的三维条件生成 | WSL + NVIDIA GPU |
| AutoGrow4 | 受体引导的遗传式候选搜索 | WSL |
| AutoDock Vina | 全量候选的基线对接 | Windows |
| GNINA | 精筛、重打分和姿势优化 | WSL + NVIDIA GPU |
| ADMET-AI | ADMET 预测 | Windows 或独立 GPU 环境 |
| AiZynthFinder | 逆合成路线搜索 | Windows 独立环境 |
| P2Rank | 结合口袋预测 | Windows |
| Open Babel / Meeko | 受体、配体与 PDBQT 格式准备 | Windows |

工具“就绪”不仅表示可执行文件存在。正式执行前还需要检查运行时、模型或数据包、靶点资源和 smoke test；任意一项缺失都会阻止对应阶段执行。

## 结构与靶点资源

对结构条件工具而言，仅有 PDB 编号并不代表受体已经可用于计算。一个可用的结构资源包通常需要：

- 原始 PDB/mmCIF、来源和检索时间。
- 项目拥有的受体文件及其 SHA-256。
- 同一坐标系派生的受体 PDBQT。
- 明确选择的口袋、网格中心和网格大小。
- 参考配体和相关产物的哈希与来源。
- 与 TargetDiff、AutoGrow4、Vina、GNINA 的就绪状态。

前端中的结构工作流要求显式选择口袋；系统不会在多个口袋之间静默选择，也不会在缺失结构时自动构造受体。

## 轮次与候选生成

每个 `ProjectRound` 先保存为可编辑策略草稿。策略可包含研究目标、种子策略、生成方式、候选预算、性质约束、评估配置和风险提示。确认后，系统把策略与已解析种子编译为执行快照，再由编排器启动各个 Campaign。

生成方法的定位：

- **CReM**：围绕已有种子进行小步结构优化和 SAR 探索。
- **TargetDiff**：以经过验证的口袋为条件进行 de novo 三维生成；生成坐标只是候选假设，仍需独立对接验证。
- **AutoGrow4**：结合受体、网格和来源分子池进行遗传式搜索。

Vina 用于候选的标准基线筛选；GNINA 用于精筛、重打分或独立重对接。两者的结果、姿势和来源应分开保存，不能互相覆盖。

## API 导览

完整请求与响应模式以运行中的 `/docs` 为准。常用资源包括：

```text
POST /projects
POST /projects/{project_id}/chat
POST /projects/{project_id}/files
POST /projects/{project_id}/structures/import-rcsb
POST /projects/{project_id}/structures/register-upload
POST /projects/{project_id}/structures/{structure_id}/p2rank
POST /projects/{project_id}/rounds
POST /projects/{project_id}/rounds/{round_id}/start
GET  /projects/{project_id}/rounds
GET  /projects/{project_id}/rounds/{round_id}/campaigns
POST /projects/{project_id}/candidate-assessment/run
POST /projects/{project_id}/rankings/generate
GET  /projects/{project_id}/report
POST /scientific/projects/{project_id}/preflight
GET  /scientific/projects/{project_id}/execution-manifests
```

RAG CLI 示例：

```powershell
$env:PYTHONPATH = "src"
medagent rag build --project-id PROJ-EXAMPLE
medagent rag query --project-id PROJ-EXAMPLE --query "BRAF V600E inhibitor selectivity"
```

## 测试与质量检查

后端：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests scripts
```

前端：

```powershell
cd apps\web
pnpm test
pnpm build
pnpm lint
pnpm test:e2e
```

涉及 GPU、外部模型、WSL 或下载数据的检查依赖本地环境，不应将其失败伪装为已通过的计算。提交前至少运行与改动相关的测试，并在可用时运行完整测试集。

## 数据与仓库卫生

版本控制中只保留源码、配置、测试、文档和有明确教学价值的小型示例产物。下列内容必须保持在 Git 之外：

- `.env`、令牌、密码和任何私有凭据。
- `.local/`、虚拟环境、依赖缓存和临时下载。
- SQLite/PostgreSQL 运行数据、日志、PID 文件与测试报告。
- 可由输入重新生成的 PDBQT、对接姿势、中间文件和大型模型权重。

运行生成的本地文件应放在 `.local/` 或明确的工作目录中。`student_tool_runs/` 中的已提交文件是教学样例；新增运行输出需要先判断是否值得作为可复现样本纳入仓库。

## 进一步阅读

- `docs/STRUCTURE_WORKFLOW_IMPLEMENTATION_PLAN.md`：项目结构、口袋选择和受体准备的设计说明。
- `docs/TARGETDIFF_TOOLCHAIN_REDESIGN_AND_HANDOFF.md`：工具链、证据边界和后续演进计划。
- `docs/research/`：靶点、口袋和候选种子研究记录。
- `configs/tools.yaml`：本机工具的默认路径、依赖与超时设置。

## 许可证与贡献

在发布或引入第三方模型、化学数据库、stock 文件、结构文件或容器镜像前，请核对其许可证、来源和再分发条件。提交代码时请避免提交本地数据、模型权重和敏感配置，并同时更新相关测试与文档。
