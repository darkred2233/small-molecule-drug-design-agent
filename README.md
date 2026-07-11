# Small Molecule Drug Design Agent

小分子药物设计 Agent 是一个面向小分子药物设计的可追踪、证据驱动多智能体系统。项目目标是把靶点资料、用户上传数据、候选分子导入、结构校验、规则过滤、RAG 证据、自我反驳、综合排序和报告生成串成一个可审计的智能体工作流，帮助用户理解每个候选分子为什么被推荐或淘汰。

当前代码已进入 MVP 集成验证阶段：后端 API、关系数据库、内置靶点库、文件上传解析、RAG 建库检索、候选分子导入/生成、结构校验、规则过滤、候选评估、综合排序和 DecisionCard 已经连成可执行的 full pipeline。Docker 计算工具适配已就绪，下一步重点是用真实项目资料验证 Docking、ADMET、合成可及性和报告链路的科学可用性。

## 当前已包含

- FastAPI 后端骨架
- 中文首页和中文接口说明页
- Swagger 调试页：`/swagger`
- PostgreSQL/pgvector/MinIO 的 Docker Compose 配置
- SQLAlchemy 关系数据库模型
- RAG 文档表、chunk 表和 evidence link 表
- 内置靶点-药物库 RAG 入库
- 上传文本/PDF/DOCX/Markdown/HTML 的 RAG 建库
- URL 静态页面爬取入库：`POST /projects/{project_id}/rag/crawl`
- RAG 混合检索：本地向量 + BM25 + 可选 `qwen3-rerank`
- RAG 查询和证据编号：`POST /projects/{project_id}/rag/query`
- 内置靶点-药物关系库：10 个 MVP 靶点、32 个代表药物
- 可迁移 SQLite 种子库快照：`database/medagent_seed.sqlite`
- 项目创建接口：`POST /projects`
- 自然语言约束解析接口：`POST /projects/{project_id}/chat`
- 文件上传接口：`POST /projects/{project_id}/files`
- 文件解析接口：`POST /projects/{project_id}/ingest`
- 单文件重新解析接口：`POST /projects/{project_id}/files/{file_id}/parse`
- 种子配体查询接口：`GET /projects/{project_id}/seed-ligands`
- 候选分子导入接口：`POST /projects/{project_id}/molecules/import-seeds`
- 候选分子生成接口：`POST /projects/{project_id}/molecules/generate`
- 候选分子轻量校验接口：`POST /projects/{project_id}/molecules/validate`
- 规则过滤接口：`POST /projects/{project_id}/molecules/filter-rules`
- 受体准备接口：`POST /projects/{project_id}/receptors/prepare`
- 候选评估接口：`POST /projects/{project_id}/candidate-assessment/run`
- 排名生成接口：`POST /projects/{project_id}/rankings/generate`
- Advisor 建议应用接口：`POST /projects/{project_id}/advisor/apply`
- ReasoningTrace 和 DecisionCard 生成接口：`POST /projects/{project_id}/decision-cards/generate`
- 候选分子性质查询接口：`GET /projects/{project_id}/molecules/{molecule_id}/properties`
- 流程 dry-run 和 full MVP 模式、状态查询、约束查询、报告骨架接口
- 计算工具状态和直接调用接口：`GET /tools/status`
- pytest 自动化测试

## 本地运行

```powershell
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:PYTHONPATH='src'
python -m uvicorn medagent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

打开：

- 中文首页：http://127.0.0.1:8000/
- 中文接口说明：http://127.0.0.1:8000/docs
- Swagger 调试页：http://127.0.0.1:8000/swagger
- 健康检查：http://127.0.0.1:8000/health

默认使用本地 SQLite，方便快速试跑。生产或完整环境请复制 `.env.example`，把 `MEDAGENT_DATABASE_URL` 指向 PostgreSQL。

## 启动基础设施

```powershell
docker compose up -d
```

Compose 会启动 PostgreSQL + pgvector 和 MinIO。RDKit cartridge 在不同发行镜像中支持差异较大，真实分子计算建议放在独立工具容器或 Python 化学工具适配器中，通过标准化 tool-run 接口接入。

检查本地计算工具状态：

```powershell
python scripts\check_tools.py
```

## 测试

```powershell
python -m pytest
python -m ruff check .
```

## 关系数据库快照

重新生成 SQLite 种子库快照：

```powershell
$env:PYTHONPATH='src'
python -m medagent.cli db snapshot --output database/medagent_seed.sqlite
```

相关文档：

- `docs/RELATIONAL_DATABASE_BUILD.md`
- `docs/FILE_INGESTION_BUILD.md`
- `docs/MOLECULE_IMPORT_BUILD.md`
- `docs/MOLECULE_VALIDATION_BUILD.md`
- `docs/RAG_BUILD.md`
- `docs/MIGRATION_GUIDE.md`

## 下一步路线

1. 清理旧 Agent 草稿与当前 `services/*` 主线之间的字段分叉，统一使用当前 ORM 和领域 schema。
2. 用真实靶点资料、受体文件和种子配体跑一轮 `mode=full`，沉淀可复现 demo 数据。
3. 校准 Docking、ADMET 和合成可及性结果的阈值、标签和失败原因，避免把代理结果当成实验结论。
4. 把 Self-Refutation、Advisor 和 Report Agent 接入 full pipeline 的 AgentRun 记录。
5. 扩充真实文献和项目资料 RAG 证据库，评估 Top 10 相关证据比例。
