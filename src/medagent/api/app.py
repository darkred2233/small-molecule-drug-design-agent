from collections.abc import Generator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, sessionmaker

from medagent.agents.conversation import ConversationAgent
from medagent.agents.orchestrator import PipelineOrchestrator
from medagent.core.config import Settings, get_settings
from medagent.db.models import (
    AgentRun,
    Base,
    ConversationMessage,
    Molecule,
    OptimizationConstraint,
    Project,
    Target,
)
from medagent.db.session import build_session_factory
from medagent.domain.schemas import (
    AdviceRead,
    BuiltinDrugRead,
    BuiltinTargetRead,
    ChatRequest,
    ChatResponse,
    ConstraintRead,
    MoleculeRead,
    ProjectCreate,
    ProjectRead,
    ProjectStatus,
    RunPipelineRequest,
    UploadedFileRead,
)
from medagent.services.bootstrap import seed_builtin_targets
from medagent.services.database import database_summary, ensure_relational_schema
from medagent.services.ids import new_id

SessionLocal: sessionmaker[Session]


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    session_factory = build_session_factory(app_settings)
    globals()["SessionLocal"] = session_factory

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        engine = session_factory.kw["bind"]
        Base.metadata.create_all(bind=engine)
        ensure_relational_schema(engine)
        with session_factory() as db:
            seed_builtin_targets(db)
        yield

    app = FastAPI(
        title="小分子药物设计 Agent",
        description=(
            "面向小分子药物设计流程的智能体后端。当前已完成关系数据库、内置靶点-药物库、"
            "项目创建、自然语言约束解析和流程 dry-run。RAG、Docking、ADMET 等能力后续接入。"
        ),
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "系统状态", "description": "服务健康检查和数据库摘要。"},
            {"name": "内置靶点库", "description": "查询 MVP 内置靶点和代表药物。"},
            {"name": "项目管理", "description": "创建项目、查询项目状态、启动流程 dry-run。"},
            {"name": "对话与约束", "description": "把自然语言优化方向转为结构化约束。"},
            {"name": "文件与导入", "description": "上传资料并创建知识导入任务。"},
            {"name": "结果查询", "description": "查询候选分子、Advisor 建议和报告骨架。"},
        ],
    )

    def get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    @app.get("/", include_in_schema=False)
    def chinese_home() -> HTMLResponse:
        return HTMLResponse(
            """
            <!doctype html>
            <html lang="zh-CN">
            <head>
              <meta charset="utf-8" />
              <meta name="viewport" content="width=device-width, initial-scale=1" />
              <title>小分子药物设计 Agent</title>
              <style>
                :root {
                  color-scheme: light;
                  --ink: #172033;
                  --muted: #5b667a;
                  --line: #d9e0ea;
                  --panel: #f7f9fc;
                  --accent: #176b87;
                  --accent-2: #4d7c0f;
                }
                * { box-sizing: border-box; }
                body {
                  margin: 0;
                  font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
                  color: var(--ink);
                  background: #ffffff;
                }
                header {
                  border-bottom: 1px solid var(--line);
                  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
                }
                .wrap {
                  width: min(1120px, calc(100% - 40px));
                  margin: 0 auto;
                }
                .hero {
                  padding: 42px 0 34px;
                  display: grid;
                  grid-template-columns: minmax(0, 1fr) auto;
                  gap: 28px;
                  align-items: end;
                }
                h1 {
                  margin: 0 0 12px;
                  font-size: clamp(30px, 4vw, 48px);
                  line-height: 1.08;
                  letter-spacing: 0;
                }
                p {
                  margin: 0;
                  color: var(--muted);
                  line-height: 1.72;
                  font-size: 16px;
                }
                .actions {
                  display: flex;
                  gap: 12px;
                  flex-wrap: wrap;
                  justify-content: flex-end;
                }
                a.button {
                  display: inline-flex;
                  align-items: center;
                  justify-content: center;
                  min-height: 42px;
                  padding: 0 16px;
                  border: 1px solid var(--line);
                  border-radius: 6px;
                  color: var(--ink);
                  text-decoration: none;
                  font-weight: 600;
                  background: #ffffff;
                }
                a.button.primary {
                  border-color: var(--accent);
                  background: var(--accent);
                  color: #ffffff;
                }
                main { padding: 30px 0 44px; }
                .grid {
                  display: grid;
                  grid-template-columns: repeat(3, minmax(0, 1fr));
                  gap: 16px;
                }
                .card {
                  border: 1px solid var(--line);
                  border-radius: 8px;
                  padding: 18px;
                  background: #ffffff;
                }
                .card h2 {
                  margin: 0 0 10px;
                  font-size: 18px;
                  letter-spacing: 0;
                }
                .metric {
                  display: flex;
                  gap: 18px;
                  padding: 18px;
                  margin: 0 0 18px;
                  border: 1px solid var(--line);
                  border-radius: 8px;
                  background: var(--panel);
                }
                .metric strong {
                  display: block;
                  font-size: 28px;
                  color: var(--accent-2);
                }
                code {
                  padding: 2px 6px;
                  border-radius: 4px;
                  background: #eef3f8;
                  color: #243044;
                }
                @media (max-width: 780px) {
                  .hero { grid-template-columns: 1fr; }
                  .actions { justify-content: flex-start; }
                  .grid { grid-template-columns: 1fr; }
                  .metric { flex-direction: column; gap: 8px; }
                }
              </style>
            </head>
            <body>
              <header>
                <div class="wrap hero">
                  <div>
                    <h1>小分子药物设计 Agent</h1>
                    <p>中文 API 控制台。当前阶段已完成关系数据库、内置靶点-药物库、项目创建、约束解析和流程 dry-run；RAG 暂未接入。</p>
                  </div>
                  <nav class="actions">
                    <a class="button primary" href="/docs">打开接口文档</a>
                    <a class="button" href="/database/summary">查看数据库摘要</a>
                    <a class="button" href="/builtin-targets">查看内置靶点</a>
                  </nav>
                </div>
              </header>
              <main class="wrap">
                <section class="metric" aria-label="当前数据库概览">
                  <div><strong>10</strong><span>内置 MVP 靶点</span></div>
                  <div><strong>32</strong><span>代表药物结构记录</span></div>
                  <div><strong>14</strong><span>dry-run Agent 步骤</span></div>
                </section>
                <section class="grid">
                  <article class="card">
                    <h2>项目入口</h2>
                    <p>使用 <code>POST /projects</code> 创建项目，再通过 <code>POST /projects/{id}/chat</code> 写入自然语言优化约束。</p>
                  </article>
                  <article class="card">
                    <h2>关系数据库</h2>
                    <p>使用 <code>GET /database/summary</code> 检查靶点和药物种子库是否已正确初始化。</p>
                  </article>
                  <article class="card">
                    <h2>流程 dry-run</h2>
                    <p>使用 <code>POST /projects/{id}/run</code> 生成完整 Agent 运行记录，方便后续逐步接入真实工具。</p>
                  </article>
                </section>
              </main>
            </body>
            </html>
            """
        )

    @app.get("/docs", include_in_schema=False)
    def chinese_docs() -> HTMLResponse:
        return HTMLResponse(
            """
            <!doctype html>
            <html lang="zh-CN">
            <head>
              <meta charset="utf-8" />
              <meta name="viewport" content="width=device-width, initial-scale=1" />
              <title>小分子药物设计 Agent - 接口文档</title>
              <style>
                :root {
                  color-scheme: light;
                  --ink: #172033;
                  --muted: #5b667a;
                  --line: #d9e0ea;
                  --panel: #f7f9fc;
                  --accent: #176b87;
                  --post: #176b87;
                  --get: #4d7c0f;
                }
                * { box-sizing: border-box; }
                body {
                  margin: 0;
                  font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
                  color: var(--ink);
                  background: #ffffff;
                }
                header {
                  padding: 30px 0 22px;
                  border-bottom: 1px solid var(--line);
                  background: #f8fbff;
                }
                .wrap {
                  width: min(1180px, calc(100% - 40px));
                  margin: 0 auto;
                }
                h1 {
                  margin: 0 0 10px;
                  font-size: clamp(28px, 4vw, 44px);
                  line-height: 1.12;
                  letter-spacing: 0;
                }
                p {
                  margin: 0;
                  color: var(--muted);
                  line-height: 1.7;
                }
                nav {
                  display: flex;
                  gap: 10px;
                  flex-wrap: wrap;
                  margin-top: 18px;
                }
                a.button {
                  display: inline-flex;
                  align-items: center;
                  min-height: 38px;
                  padding: 0 14px;
                  border: 1px solid var(--line);
                  border-radius: 6px;
                  text-decoration: none;
                  color: var(--ink);
                  background: #ffffff;
                  font-weight: 600;
                }
                a.button.primary {
                  background: var(--accent);
                  border-color: var(--accent);
                  color: #ffffff;
                }
                main { padding: 26px 0 44px; }
                .section-title {
                  margin: 26px 0 12px;
                  font-size: 20px;
                  letter-spacing: 0;
                }
                .grid {
                  display: grid;
                  grid-template-columns: repeat(2, minmax(0, 1fr));
                  gap: 14px;
                }
                .card {
                  border: 1px solid var(--line);
                  border-radius: 8px;
                  padding: 16px;
                  background: #ffffff;
                }
                .route {
                  display: flex;
                  align-items: center;
                  gap: 10px;
                  margin-bottom: 9px;
                  min-width: 0;
                }
                .method {
                  flex: 0 0 auto;
                  min-width: 58px;
                  text-align: center;
                  border-radius: 5px;
                  padding: 5px 8px;
                  color: #ffffff;
                  font-weight: 700;
                  font-size: 13px;
                }
                .method.get { background: var(--get); }
                .method.post { background: var(--post); }
                code {
                  font-size: 14px;
                  white-space: normal;
                  word-break: break-word;
                  padding: 2px 6px;
                  border-radius: 4px;
                  background: #eef3f8;
                  color: #243044;
                }
                .card h2 {
                  margin: 0 0 8px;
                  font-size: 17px;
                  letter-spacing: 0;
                }
                .note {
                  margin-top: 18px;
                  padding: 14px 16px;
                  border: 1px solid var(--line);
                  border-radius: 8px;
                  background: var(--panel);
                }
                @media (max-width: 760px) {
                  .grid { grid-template-columns: 1fr; }
                }
              </style>
            </head>
            <body>
              <header>
                <div class="wrap">
                  <h1>接口文档</h1>
                  <p>所有业务说明已中文化。当前后端支持内置靶点库、关系数据库摘要、项目创建、自然语言约束解析、流程模拟运行和结果查询。</p>
                  <nav>
                    <a class="button primary" href="/">返回首页</a>
                    <a class="button" href="/swagger">打开 Swagger 调试页</a>
                    <a class="button" href="/openapi.json">查看 OpenAPI JSON</a>
                  </nav>
                </div>
              </header>
              <main class="wrap">
                <h2 class="section-title">系统状态</h2>
                <section class="grid">
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/health</code></div>
                    <h2>健康检查</h2>
                    <p>确认服务是否正常启动。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/database/summary</code></div>
                    <h2>查看关系数据库摘要</h2>
                    <p>返回靶点数量、药物数量、项目数量和靶点编号列表。</p>
                  </article>
                </section>

                <h2 class="section-title">内置靶点库</h2>
                <section class="grid">
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/builtin-targets</code></div>
                    <h2>查看内置靶点列表</h2>
                    <p>返回 10 个 MVP 靶点和 32 个代表药物。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/builtin-targets/{target_id}</code></div>
                    <h2>查看单个靶点详情</h2>
                    <p>查询指定靶点的 UniProt、PDB、代表药物和结构字段。</p>
                  </article>
                </section>

                <h2 class="section-title">项目与对话</h2>
                <section class="grid">
                  <article class="card">
                    <div class="route"><span class="method post">POST</span><code>/projects</code></div>
                    <h2>创建项目</h2>
                    <p>创建一个药物设计项目，记录项目名称、靶点编号、目标和初始约束。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method post">POST</span><code>/projects/{project_id}/chat</code></div>
                    <h2>解析自然语言优化约束</h2>
                    <p>把“降低 hERG 风险、保留母核、只改 R6 位”等自然语言转成结构化约束。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method post">POST</span><code>/projects/{project_id}/run</code></div>
                    <h2>启动项目流程模拟运行</h2>
                    <p>创建完整 Agent 流程记录，目前只支持 dry_run。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/projects/{project_id}/status</code></div>
                    <h2>查看项目流程状态</h2>
                    <p>返回项目状态和 Agent 运行记录。</p>
                  </article>
                </section>

                <h2 class="section-title">文件与结果</h2>
                <section class="grid">
                  <article class="card">
                    <div class="route"><span class="method post">POST</span><code>/projects/{project_id}/files</code></div>
                    <h2>上传项目资料</h2>
                    <p>记录上传文件元信息；真实存储和解析会在后续阶段接入。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method post">POST</span><code>/projects/{project_id}/ingest</code></div>
                    <h2>创建知识导入任务</h2>
                    <p>创建知识导入 Agent 运行记录；RAG 暂未接入。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/projects/{project_id}/constraints</code></div>
                    <h2>查看当前优化约束</h2>
                    <p>按优先级返回当前项目的结构化约束。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/projects/{project_id}/report</code></div>
                    <h2>查看报告骨架</h2>
                    <p>返回可追踪报告的章节骨架和当前项目摘要。</p>
                  </article>
                </section>

                <div class="note">
                  <p>需要在线调试请求时，请打开 <a href="/swagger">Swagger 调试页</a>。调试页控件来自 Swagger UI，少量按钮文案由第三方库控制，但业务接口、分组和字段说明已经中文化。</p>
                </div>
              </main>
            </body>
            </html>
            """
        )

    @app.get("/swagger", include_in_schema=False)
    def swagger_debug_docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title="小分子药物设计 Agent - Swagger 调试页",
            swagger_ui_parameters={
                "docExpansion": "list",
                "displayRequestDuration": True,
                "defaultModelsExpandDepth": 1,
                "defaultModelExpandDepth": 2,
                "tryItOutEnabled": True,
            },
        )

    @app.get("/health", tags=["系统状态"], summary="健康检查")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": app_settings.app_name}

    @app.get("/database/summary", tags=["系统状态"], summary="查看关系数据库摘要")
    def get_database_summary(db: Session = Depends(get_db)):
        return database_summary(db)

    @app.get("/builtin-targets", response_model=list[BuiltinTargetRead], tags=["内置靶点库"], summary="查看内置靶点列表")
    def list_builtin_targets(db: Session = Depends(get_db)):
        targets = db.query(Target).order_by(Target.name).all()
        return [_target_to_read(target) for target in targets]

    @app.get(
        "/builtin-targets/{target_id}",
        response_model=BuiltinTargetRead,
        tags=["内置靶点库"],
        summary="查看单个靶点详情",
    )
    def get_builtin_target(target_id: str, db: Session = Depends(get_db)):
        target = db.query(Target).filter_by(target_id=target_id).one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="未找到该靶点")
        return _target_to_read(target)

    @app.post("/projects", response_model=ProjectRead, status_code=201, tags=["项目管理"], summary="创建项目")
    def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
        project = Project(
            project_id=new_id("PROJ"),
            name=payload.name,
            target_id=payload.target_id,
            objective=payload.objective,
            constraints_json=payload.constraints,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return _project_to_read(project)

    @app.post(
        "/projects/{project_id}/chat",
        response_model=ChatResponse,
        tags=["对话与约束"],
        summary="解析自然语言优化约束",
    )
    def chat(project_id: str, payload: ChatRequest, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        agent = ConversationAgent()
        parsed = agent.parse(payload.message)

        message = ConversationMessage(
            message_id=new_id("MSG"),
            project_id=project.project_id,
            role="user",
            content=payload.message,
            intent=parsed.intent,
            extracted_payload={"constraints": [constraint.__dict__ for constraint in parsed.constraints]},
        )
        db.add(message)
        db.flush()

        created_constraints: list[str] = []
        for parsed_constraint in parsed.constraints:
            constraint = OptimizationConstraint(
                constraint_id=new_id("CONS"),
                project_id=project.project_id,
                label=parsed_constraint.label,
                field=parsed_constraint.field,
                operator=parsed_constraint.operator,
                value=parsed_constraint.value,
                priority=parsed_constraint.priority,
                source_message_id=message.message_id,
            )
            db.add(constraint)
            created_constraints.append(constraint.constraint_id)

        db.add(
            ConversationMessage(
                message_id=new_id("MSG"),
                project_id=project.project_id,
                role="assistant",
                content=parsed.reply,
                intent=parsed.intent,
                extracted_payload={"created_constraints": created_constraints},
            )
        )
        db.commit()
        return ChatResponse(
            reply=parsed.reply,
            intent=parsed.intent,
            created_constraints=created_constraints,
        )

    @app.post(
        "/projects/{project_id}/files",
        response_model=UploadedFileRead,
        status_code=202,
        tags=["文件与导入"],
        summary="上传项目资料",
    )
    async def upload_file(
        project_id: str,
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
    ):
        _get_project(db, project_id)
        from medagent.db.models import UploadedFile as UploadedFileModel

        file_id = new_id("FILE")
        uploaded = UploadedFileModel(
            file_id=file_id,
            project_id=project_id,
            filename=file.filename or file_id,
            file_type=file.content_type or "application/octet-stream",
            storage_path=f"pending://{project_id}/{file_id}/{file.filename}",
            parse_status="uploaded",
            metadata_json={"note": "Storage adapter is not connected in M1 scaffold."},
        )
        db.add(uploaded)
        db.commit()
        return UploadedFileRead(
            file_id=file_id,
            filename=uploaded.filename,
            file_type=uploaded.file_type,
            parse_status=uploaded.parse_status,
        )

    @app.post("/projects/{project_id}/ingest", status_code=202, tags=["文件与导入"], summary="创建知识导入任务")
    def ingest(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        run = AgentRun(
            agent_run_id=new_id("RUN"),
            project_id=project_id,
            agent_name="knowledge_ingestion_agent",
            model_name=app_settings.qwen_task_model,
            status="queued",
            input_json={"project_id": project_id},
            output_json={"message": "Ingestion job queued; parsers will be attached in M2."},
        )
        db.add(run)
        db.commit()
        return {"agent_run_id": run.agent_run_id, "status": run.status}

    @app.post(
        "/projects/{project_id}/run",
        response_model=ProjectStatus,
        status_code=202,
        tags=["项目管理"],
        summary="启动项目流程 dry-run",
    )
    def run_pipeline(
        project_id: str,
        payload: RunPipelineRequest | None = None,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        requested = payload or RunPipelineRequest()
        if requested.mode != "dry_run":
            raise HTTPException(
                status_code=422,
                detail="当前仅支持 dry_run；真实工具适配器接入后再开放 full 模式。",
            )
        PipelineOrchestrator(app_settings).create_dry_run(db, project)
        db.refresh(project)
        return _project_status(db, project)

    @app.post(
        "/projects/{project_id}/rounds",
        response_model=ProjectStatus,
        status_code=202,
        tags=["项目管理"],
        summary="创建新一轮优化 dry-run",
    )
    def create_round(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        PipelineOrchestrator(app_settings).create_dry_run(db, project)
        db.refresh(project)
        return _project_status(db, project)

    @app.post(
        "/projects/{project_id}/advisor/apply",
        status_code=202,
        tags=["对话与约束"],
        summary="应用 Advisor 建议",
    )
    def apply_advice(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        return {"status": "queued", "message": "Advisor 建议应用将在 M6 阶段实现。"}

    @app.get(
        "/projects/{project_id}/status",
        response_model=ProjectStatus,
        tags=["项目管理"],
        summary="查看项目流程状态",
    )
    def get_status(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return _project_status(db, project)

    @app.get(
        "/projects/{project_id}/constraints",
        response_model=list[ConstraintRead],
        tags=["对话与约束"],
        summary="查看当前优化约束",
    )
    def list_constraints(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        constraints = (
            db.query(OptimizationConstraint)
            .filter_by(project_id=project_id)
            .order_by(OptimizationConstraint.priority.desc())
            .all()
        )
        return [
            ConstraintRead(
                constraint_id=item.constraint_id,
                label=item.label,
                field=item.field,
                operator=item.operator,
                value=item.value,
                priority=item.priority,
            )
            for item in constraints
        ]

    @app.get(
        "/projects/{project_id}/molecules",
        response_model=list[MoleculeRead],
        tags=["结果查询"],
        summary="查看候选分子",
    )
    def list_molecules(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        molecules = db.query(Molecule).filter_by(project_id=project_id).all()
        return [
            MoleculeRead(
                molecule_id=item.molecule_id,
                smiles=item.smiles,
                scaffold=item.scaffold,
                status=item.status,
                labels=item.labels,
            )
            for item in molecules
        ]

    @app.get(
        "/projects/{project_id}/advice",
        response_model=list[AdviceRead],
        tags=["结果查询"],
        summary="查看 Advisor 建议",
    )
    def get_advice(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        from medagent.db.models import AdvisorSuggestion

        suggestions = db.query(AdvisorSuggestion).filter_by(project_id=project_id).all()
        return [
            AdviceRead(
                suggestion_id=item.suggestion_id,
                summary=item.summary,
                suggestions=item.suggestions,
            )
            for item in suggestions
        ]

    @app.get("/projects/{project_id}/report", tags=["结果查询"], summary="查看报告骨架")
    def get_report(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        constraints = (
            db.query(OptimizationConstraint)
            .filter_by(project_id=project_id)
            .order_by(OptimizationConstraint.priority.desc())
            .all()
        )
        return {
            "project_summary": {
                "project_id": project.project_id,
                "name": project.name,
                "target_id": project.target_id,
                "objective": project.objective,
                "status": project.status,
            },
            "constraints": [
                {
                    "constraint_id": item.constraint_id,
                    "label": item.label,
                    "field": item.field,
                    "operator": item.operator,
                    "value": item.value,
                    "priority": item.priority,
                }
                for item in constraints
            ],
            "sections": [
                "project_summary",
                "input_information",
                "rag_evidence_overview",
                "target_and_pocket_analysis",
                "candidate_molecules",
                "filtering_statistics",
                "docking_overview",
                "admet_overview",
                "synthesis_overview",
                "self_refutation",
                "advisor_suggestions",
                "top_candidates",
                "evidence_links",
                "technical_appendix",
            ],
        }

    return app


def _get_project(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter_by(project_id=project_id).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="未找到该项目")
    return project


def _project_to_read(project: Project) -> ProjectRead:
    return ProjectRead(
        project_id=project.project_id,
        name=project.name,
        target_id=project.target_id,
        objective=project.objective,
        status=project.status,
        created_at=project.created_at,
    )


def _target_to_read(target: Target) -> BuiltinTargetRead:
    return BuiltinTargetRead(
        target_id=target.target_id,
        name=target.name,
        aliases=target.aliases,
        uniprot_id=target.uniprot_id,
        species=target.species,
        pdb_ids=target.pdb_ids,
        summary=target.summary,
        drugs=[
            BuiltinDrugRead(
                drug_name=drug.drug_name,
                drug_status=drug.drug_status,
                mechanism=drug.mechanism,
                indication=drug.indication,
                smiles=drug.smiles,
                canonical_smiles=drug.canonical_smiles,
                isomeric_smiles=drug.isomeric_smiles,
                inchi_key=drug.inchi_key,
                pubchem_cid=drug.pubchem_cid,
                evidence_source=drug.evidence_source,
            )
            for drug in target.drugs
        ],
    )


def _project_status(db: Session, project: Project) -> ProjectStatus:
    runs = (
        db.query(AgentRun)
        .filter_by(project_id=project.project_id)
        .order_by(AgentRun.created_at.asc())
        .all()
    )
    return ProjectStatus(
        project_id=project.project_id,
        status=project.status,
        agent_runs=[
            {
                "agent_run_id": run.agent_run_id,
                "agent_name": run.agent_name,
                "model_name": run.model_name,
                "status": run.status,
                "output_json": run.output_json,
            }
            for run in runs
        ],
    )
