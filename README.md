# 小分子药物设计 Agent

这是按《小分子药物设计 Agent 开发文档 v2.1》启动的项目骨架。当前版本聚焦 M1：FastAPI 服务、核心数据模型、内置靶点-药物库、自然语言约束解析入口、Agent 运行日志和可追踪报告接口。

## 当前已包含

- FastAPI 后端骨架
- PostgreSQL/pgvector/MinIO 的 Docker Compose 配置
- 文档要求的核心关系表 SQLAlchemy 模型
- 内置靶点接口：`GET /builtin-targets`
- 项目创建接口：`POST /projects`
- 对话约束接口：`POST /projects/{id}/chat`
- 流程启动占位接口：`POST /projects/{id}/run`
- 状态、分子、约束、建议、报告查询接口
- 标准化工具运行输出结构
- 基础 pytest 测试

## 本地运行

```powershell
cd C:\Users\34471\Desktop\small-molecule-drug-design-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn medagent.main:app --reload --host 127.0.0.1 --port 8000
```

打开：

- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

默认使用本地 SQLite，方便快速试跑。生产或完整 M1 环境请复制 `.env.example`，把 `MEDAGENT_DATABASE_URL` 指向 PostgreSQL。

## 启动基础设施

```powershell
docker compose up -d
```

Compose 会启动 PostgreSQL + pgvector 和 MinIO。RDKit cartridge 在不同发行镜像中支持差异较大，当前迁移脚本将 RDKit 作为可选扩展记录，真正分子计算建议放在独立工具容器中，通过标准化 tool-run 接口接入。

## 测试

```powershell
python -m pytest
```

## 下一步建议

1. M2：补齐文件上传解析流水线，接入 PDF/CSV/SDF/PDB parser。
2. M3：接入 embedding 与 rerank，落地 RAG chunk、检索和 evidence_id。
3. M4：接入 RDKit/Datamol 规则过滤，形成真实 MoleculeRecord 生命周期。
