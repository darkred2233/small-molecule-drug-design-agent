# Small Molecule Drug Design Agent

面向小分子药物设计的可追溯多智能体工作台。

当前主线已经从旧的固定轮数自动流程，整理为“项目 -> 无限轮次 -> 每轮多个生成 Campaign -> 评估/排序/自我反驳/报告”的实验式工作流。每一轮都应作为可复盘记录进入数据库，后续由用户或中枢 LLM 根据上一轮结果决定下一轮怎么生成、生成多少、用哪些约束。

本项目用于教学、科研原型和计算流程探索。任何候选分子的活性、安全性、可合成性和成药性结论都需要实验、临床和合规流程验证。

## 当前主线

1. 创建项目，选择内置靶点或自定义靶点。
2. 上传文献、结构文件、SMILES/SDF/CSV 等资料，构建 RAG 证据库。
3. 通过自然语言聊天提取结构化约束，例如降低 hERG 风险、保留某个骨架、限制理化性质范围。
4. 创建一轮 `ProjectRound` 草稿。
5. 为本轮配置 `CampaignConfig`，分别控制 CReM、REINVENT4、AutoGrow4。
6. 启动本轮后，系统执行生成、候选评估、综合排序、自我反驳，并创建下一轮草稿。
7. 用户或后续中枢 LLM 根据本轮结果，继续调整下一轮策略。
8. 报告模块基于数据库中已存在的证据输出项目报告。

核心入口：

```text
POST /projects
POST /projects/{project_id}/chat
POST /projects/{project_id}/rounds
POST /projects/{project_id}/rounds/{round_id}/start
GET  /projects/{project_id}/rounds
GET  /projects/{project_id}/rounds/{round_id}/campaigns
POST /projects/{project_id}/candidate-assessment/run
POST /projects/{project_id}/rankings/generate
GET  /projects/{project_id}/report
```

旧的 `RunPlan`、`/projects/{id}/run`、`/projects/{id}/run-iterative`、`/projects/{id}/molecules/generate` 已从主代码中移除。

## 三种生成方式

- CReM：适合围绕已有种子做局部片段替换，适合小步 SAR 优化和保守探索。
- REINVENT4：适合更强的生成式优化，可用轻量迁移学习加强化学习，也可按项目目标配置奖励函数。
- AutoGrow4：适合结合受体结构、结合口袋和对接搜索区域做对接引导的遗传式搜索。

底层适配器仍保留真实工具优先、不可用时明确 fallback 的机制。新流程通过 `CremAgent`、`Reinvent4Agent`、`AutoGrow4Agent` 在每个 Campaign 内调用这些适配器。

## 关键目录

```text
apps/web/                 React + Vite 前端
src/medagent/api/         FastAPI app 与路由
src/medagent/agents/      生成、排序、自我反驳、报告等 agent
src/medagent/db/          SQLAlchemy 模型和会话
src/medagent/domain/      Pydantic schema
src/medagent/pipeline/    RoundOrchestrator 与流程状态
src/medagent/services/    候选评估、工具适配、RAG、报告等服务
tests/                    pytest 测试
configs/                  模型、打分、过滤和工具配置
docs/                     当前设计文档
```

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,chem,rag]"

$env:PYTHONPATH="src"
python -m uvicorn medagent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd apps\web
corepack enable
pnpm install
pnpm dev
```

## 当前设计文档

- `docs/ROUND_STRATEGY_REDESIGN_GUIDE.md`：无限轮次、中央 LLM 策略、三种生成方式和后续评估排名的改造说明。
