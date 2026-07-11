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
    DecisionCard,
    EvidenceLink,
    Molecule,
    MoleculeProperty,
    OptimizationConstraint,
    Project,
    RagChunk,
    RagDocument,
    ReasoningTrace,
    RuleFilterResult,
    SeedLigand,
    Target,
    UploadedFile as UploadedFileModel,
)
from medagent.db.session import build_session_factory
from medagent.domain.schemas import (
    ADMETResultRead,
    AdviceRead,
    BindingSiteRead,
    BuiltinDrugRead,
    BuiltinTargetRead,
    CandidateAssessmentRunRequest,
    CandidateAssessmentRunResponse,
    ChatRequest,
    ChatResponse,
    ConformerResultRead,
    ConstraintRead,
    DecisionCardGenerateResponse,
    DecisionCardRead,
    DockingResultRead,
    FileParseResult,
    MoleculeGenerationRequest,
    MoleculeGenerationResponse,
    MoleculeImportResponse,
    MoleculePropertyRead,
    MoleculeRead,
    MoleculeValidationResponse,
    ProjectCreate,
    ProjectRead,
    ProjectStatus,
    EvidenceLinkRead,
    RagBuildRequest,
    RagBuildResponse,
    RagChunkRead,
    RagCrawlRequest,
    RagCollectResponse,
    RagDocumentRead,
    RagQueryRequest,
    RagQueryResponse,
    RankingGenerateRequest,
    RankingRead,
    RankingRunResponse,
    ReceptorPrepareRequest,
    ReasoningTraceRead,
    RuleFilterResponse,
    RuleFilterResultRead,
    RunPipelineRequest,
    SeedLigandRead,
    SynthesisRouteRead,
    UploadedFileRead,
)
from medagent.services.bootstrap import seed_builtin_targets
from medagent.services.candidate_assessment import (
    list_project_admet_results,
    list_project_conformer_results,
    list_project_docking_results,
    list_project_synthesis_routes,
    run_project_candidate_assessment,
)
from medagent.services.candidate_ranking import generate_project_rankings, list_project_rankings
from medagent.services.database import database_summary, ensure_relational_schema
from medagent.services.decision_cards import generate_project_decision_cards
from medagent.services.file_ingestion import (
    parse_pending_project_files,
    parse_single_file,
    save_upload_file,
)
from medagent.services.ids import new_id
from medagent.services.molecule_generation import generate_project_molecules
from medagent.services.molecule_import import import_seed_ligands_as_molecules
from medagent.services.molecule_validation import validate_project_molecules
from medagent.services.rag import build_project_rag_index, crawl_project_urls, query_project_rag
from medagent.services.receptor_preparation import (
    binding_site_to_payload,
    get_project_binding_site,
    list_project_binding_sites,
    prepare_project_receptor,
)
from medagent.services.rule_filtering import filter_project_molecules

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
            "项目创建、自然语言约束解析、RAG 建库检索、MVP full pipeline 和候选分子评估。"
        ),
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "系统状态", "description": "服务健康检查和数据库摘要。"},
            {"name": "内置靶点库", "description": "查询 MVP 内置靶点和代表药物。"},
            {"name": "项目管理", "description": "创建项目、查询项目状态、启动 dry-run 或 full MVP 流程。"},
            {"name": "对话与约束", "description": "把自然语言优化方向转为结构化约束。"},
            {"name": "文件与导入", "description": "上传资料并创建知识导入任务。"},
            {"name": "RAG", "description": "构建、爬取、查询 RAG 证据库和 evidence links。"},
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
                    <p>中文 API 控制台。当前阶段已完成关系数据库、内置靶点-药物库、项目创建、约束解析、RAG 建库检索和 full MVP 流程。</p>
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
                    <h2>流程运行</h2>
                    <p>使用 <code>POST /projects/{id}/run</code> 创建 dry-run 记录，或用 <code>mode=full</code> 执行 MVP 候选评估流程。</p>
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
                  <p>所有业务说明已中文化。当前后端支持内置靶点库、关系数据库摘要、项目创建、自然语言约束解析、流程运行和结果查询。</p>
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
                    <h2>启动项目流程运行</h2>
                    <p>创建完整 Agent 流程记录；使用 <code>dry_run</code> 只登记步骤，使用 <code>full</code> 执行 MVP 工作流。</p>
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
                    <p>解析上传资料，并自动建立内置靶点与上传文档的 RAG 索引。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method post">POST</span><code>/projects/{project_id}/files/{file_id}/parse</code></div>
                    <h2>重新解析单个文件</h2>
                    <p>重新读取已上传文件，并把 SMILES、CSV、SDF 或 PDB 内容写入关系数据库。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/projects/{project_id}/files/{file_id}/parse-result</code></div>
                    <h2>查看文件解析结果</h2>
                    <p>查看解析状态、记录数、seed ligand 数量、PDB 摘要或失败原因。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/projects/{project_id}/constraints</code></div>
                    <h2>查看当前优化约束</h2>
                    <p>按优先级返回当前项目的结构化约束。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/projects/{project_id}/seed-ligands</code></div>
                    <h2>查看种子配体</h2>
                    <p>返回由 SMILES、CSV 或 SDF 文件解析得到的种子配体。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method post">POST</span><code>/projects/{project_id}/molecules/import-seeds</code></div>
                    <h2>导入种子配体为候选分子</h2>
                    <p>轻量校验 SMILES、按项目去重，并写入 molecules 表。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method post">POST</span><code>/projects/{project_id}/molecules/validate</code></div>
                    <h2>轻量校验候选分子</h2>
                    <p>检查括号、环编号等基础结构问题，并为通过校验的分子写入估算性质。</p>
                  </article>
                  <article class="card">
                    <div class="route"><span class="method get">GET</span><code>/projects/{project_id}/molecules/{molecule_id}/properties</code></div>
                    <h2>查看候选分子性质</h2>
                    <p>返回分子量、氢键供体/受体和校验元数据；当前结果仍需后续 RDKit 复核。</p>
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
        file_id = new_id("FILE")
        await file.seek(0)
        storage_path = save_upload_file(
            app_settings,
            project_id,
            file_id,
            file.filename or file_id,
            file.file,
        )
        uploaded = UploadedFileModel(
            file_id=file_id,
            project_id=project_id,
            filename=file.filename or file_id,
            file_type=file.content_type or "application/octet-stream",
            storage_path=f"local://{storage_path}",
            parse_status="uploaded",
            metadata_json={"storage_backend": "local", "original_filename": file.filename or file_id},
        )
        db.add(uploaded)
        db.commit()
        return UploadedFileRead(
            file_id=file_id,
            filename=uploaded.filename,
            file_type=uploaded.file_type,
            parse_status=uploaded.parse_status,
        )

    @app.get(
        "/projects/{project_id}/files",
        response_model=list[UploadedFileRead],
        tags=["文件与导入"],
        summary="查看项目上传文件",
    )
    def list_project_files(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        files = (
            db.query(UploadedFileModel)
            .filter_by(project_id=project_id)
            .order_by(UploadedFileModel.created_at.asc())
            .all()
        )
        return [
            UploadedFileRead(
                file_id=item.file_id,
                filename=item.filename,
                file_type=item.file_type,
                parse_status=item.parse_status,
            )
            for item in files
        ]

    @app.post("/projects/{project_id}/ingest", status_code=202, tags=["文件与导入"], summary="创建知识导入任务")
    def ingest(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        parse_summary = parse_pending_project_files(db, app_settings, project)
        rag_summary = build_project_rag_index(
            db,
            app_settings,
            project,
            include_builtin_target=True,
            include_uploads=True,
            rebuild=True,
        )
        run = AgentRun(
            agent_run_id=new_id("RUN"),
            project_id=project_id,
            agent_name="knowledge_ingestion_agent",
            model_name=app_settings.qwen_task_model,
            status="completed",
            input_json={"project_id": project_id},
            output_json={**parse_summary, "rag": rag_summary},
        )
        db.add(run)
        db.commit()
        return {"agent_run_id": run.agent_run_id, "status": run.status, **parse_summary, "rag": rag_summary}

    @app.post(
        "/projects/{project_id}/rag/build",
        response_model=RagBuildResponse,
        status_code=202,
        tags=["RAG"],
        summary="Build or rebuild the project RAG index",
    )
    def build_rag_index(
        project_id: str,
        payload: RagBuildRequest | None = None,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        request = payload or RagBuildRequest()
        return build_project_rag_index(
            db,
            app_settings,
            project,
            include_builtin_target=request.include_builtin_target,
            include_uploads=request.include_uploads,
            file_ids=request.file_ids,
            rebuild=request.rebuild,
        )

    @app.post(
        "/projects/{project_id}/rag/crawl",
        response_model=RagBuildResponse,
        status_code=202,
        tags=["RAG"],
        summary="Crawl URLs and add them to the project RAG index",
    )
    def crawl_rag_sources(
        project_id: str,
        payload: RagCrawlRequest,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        return crawl_project_urls(
            db,
            app_settings,
            project,
            urls=payload.urls,
            document_type=payload.document_type,
            rebuild=payload.rebuild,
        )

    @app.post(
        "/projects/{project_id}/rag/query",
        response_model=RagQueryResponse,
        tags=["RAG"],
        summary="Search the project RAG evidence index",
    )
    def query_rag(
        project_id: str,
        payload: RagQueryRequest,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        if payload.molecule_id:
            molecule = db.query(Molecule).filter_by(project_id=project_id, molecule_id=payload.molecule_id).one_or_none()
            if molecule is None:
                raise HTTPException(status_code=404, detail="未找到该分子")
        return query_project_rag(
            db,
            app_settings,
            project,
            query=payload.query,
            query_type=payload.query_type,
            top_k=payload.top_k,
            molecule_id=payload.molecule_id,
            create_evidence=payload.create_evidence,
        )

    @app.get(
        "/projects/{project_id}/rag/documents",
        response_model=list[RagDocumentRead],
        tags=["RAG"],
        summary="List project RAG documents",
    )
    def list_rag_documents(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        documents = (
            db.query(RagDocument)
            .filter_by(project_id=project_id)
            .order_by(RagDocument.created_at.asc(), RagDocument.id.asc())
            .all()
        )
        return [_rag_document_to_read(document) for document in documents]

    @app.get(
        "/projects/{project_id}/rag/chunks",
        response_model=list[RagChunkRead],
        tags=["RAG"],
        summary="List project RAG chunks",
    )
    def list_rag_chunks(
        project_id: str,
        document_id: str | None = None,
        db: Session = Depends(get_db),
    ):
        _get_project(db, project_id)
        documents_query = db.query(RagDocument).filter_by(project_id=project_id)
        if document_id:
            documents_query = documents_query.filter_by(document_id=document_id)
        document_ids = [document.document_id for document in documents_query.all()]
        if not document_ids:
            return []
        chunks = (
            db.query(RagChunk)
            .filter(RagChunk.document_id.in_(document_ids))
            .order_by(RagChunk.created_at.asc(), RagChunk.id.asc())
            .all()
        )
        return [_rag_chunk_to_read(chunk) for chunk in chunks]

    @app.get(
        "/projects/{project_id}/evidence-links",
        response_model=list[EvidenceLinkRead],
        tags=["RAG"],
        summary="List project RAG evidence links",
    )
    def list_evidence_links(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        document_ids = [
            document_id
            for (document_id,) in db.query(RagDocument.document_id).filter_by(project_id=project_id).all()
        ]
        if not document_ids:
            return []
        chunk_ids = [
            chunk_id
            for (chunk_id,) in db.query(RagChunk.chunk_id).filter(RagChunk.document_id.in_(document_ids)).all()
        ]
        if not chunk_ids:
            return []
        links = (
            db.query(EvidenceLink)
            .filter(EvidenceLink.chunk_id.in_(chunk_ids))
            .order_by(EvidenceLink.created_at.asc(), EvidenceLink.id.asc())
            .all()
        )
        return [_evidence_link_to_read(link) for link in links]

    @app.post(
        "/projects/{project_id}/files/{file_id}/parse",
        response_model=FileParseResult,
        tags=["文件与导入"],
        summary="重新解析单个文件",
    )
    def parse_project_file(project_id: str, file_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        uploaded_file = _get_uploaded_file(db, project_id, file_id)
        parse_single_file(db, app_settings, project, uploaded_file)
        db.refresh(uploaded_file)
        return _file_parse_result(uploaded_file)

    @app.get(
        "/projects/{project_id}/files/{file_id}/parse-result",
        response_model=FileParseResult,
        tags=["文件与导入"],
        summary="查看文件解析结果",
    )
    def get_file_parse_result(project_id: str, file_id: str, db: Session = Depends(get_db)):
        uploaded_file = _get_uploaded_file(db, project_id, file_id)
        return _file_parse_result(uploaded_file)

    @app.post(
        "/projects/{project_id}/run",
        response_model=ProjectStatus,
        status_code=202,
        tags=["项目管理"],
        summary="启动项目流程",
    )
    def run_pipeline(
        project_id: str,
        payload: RunPipelineRequest | None = None,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        requested = payload or RunPipelineRequest()
        if requested.mode == "full":
            PipelineOrchestrator(app_settings).run_full(db, project)
            db.refresh(project)
            return _project_status(db, project)
        if requested.mode != "dry_run":
            raise HTTPException(
                status_code=422,
                detail="运行模式必须是 dry_run 或 full。",
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
                source_agent=item.source_agent,
            )
            for item in molecules
        ]

    @app.post(
        "/projects/{project_id}/molecules/import-seeds",
        response_model=MoleculeImportResponse,
        status_code=201,
        tags=["结果查询"],
        summary="导入种子配体为候选分子",
    )
    def import_seed_molecules(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return import_seed_ligands_as_molecules(db, project)

    @app.post(
        "/projects/{project_id}/molecules/generate",
        response_model=MoleculeGenerationResponse,
        status_code=201,
        tags=["结果查询"],
        summary="生成三类候选分子",
    )
    def generate_molecules(
        project_id: str,
        payload: MoleculeGenerationRequest | None = None,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        request = payload or MoleculeGenerationRequest()
        try:
            return generate_project_molecules(
                db=db,
                project=project,
                generation_size=request.generation_size,
                strategies=request.strategies,
                constraints=request.constraints,
                include_target_library_seeds=request.include_target_library_seeds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/projects/{project_id}/molecules/validate",
        response_model=MoleculeValidationResponse,
        tags=["结果查询"],
        summary="轻量校验候选分子",
    )
    def validate_molecules(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return validate_project_molecules(db, project)

    @app.post(
        "/projects/{project_id}/molecules/filter-rules",
        response_model=RuleFilterResponse,
        tags=["rule-filtering"],
        summary="Apply basic drug-likeness rule filters",
    )
    def filter_molecules_by_rules(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return filter_project_molecules(db, project)

    @app.get(
        "/projects/{project_id}/rule-filter-results",
        response_model=list[RuleFilterResultRead],
        tags=["rule-filtering"],
        summary="List project rule filter results",
    )
    def list_project_rule_filter_results(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        results = (
            db.query(RuleFilterResult)
            .filter_by(project_id=project_id)
            .order_by(RuleFilterResult.created_at.asc(), RuleFilterResult.id.asc())
            .all()
        )
        return [_rule_filter_result_to_read(result) for result in results]

    @app.get(
        "/projects/{project_id}/molecules/{molecule_id}/rule-filter-results",
        response_model=list[RuleFilterResultRead],
        tags=["rule-filtering"],
        summary="List molecule rule filter results",
    )
    def list_molecule_rule_filter_results(
        project_id: str,
        molecule_id: str,
        db: Session = Depends(get_db),
    ):
        _get_project(db, project_id)
        molecule = db.query(Molecule).filter_by(project_id=project_id, molecule_id=molecule_id).one_or_none()
        if molecule is None:
            raise HTTPException(status_code=404, detail="Molecule not found")
        results = (
            db.query(RuleFilterResult)
            .filter_by(project_id=project_id, molecule_id=molecule_id)
            .order_by(RuleFilterResult.created_at.asc(), RuleFilterResult.id.asc())
            .all()
        )
        return [_rule_filter_result_to_read(result) for result in results]

    @app.post(
        "/projects/{project_id}/receptors/prepare",
        response_model=BindingSiteRead,
        status_code=201,
        tags=["receptor-preparation"],
        summary="Prepare project receptor and docking grid",
    )
    def prepare_receptor(
        project_id: str,
        payload: ReceptorPrepareRequest,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        try:
            result = prepare_project_receptor(
                db=db,
                settings=app_settings,
                project=project,
                source_file_id=payload.source_file_id,
                receptor_file=payload.receptor_file,
                binding_site_id=payload.binding_site_id,
                pdb_id=payload.pdb_id,
                grid_center=payload.grid_center,
                grid_size=payload.grid_size,
                key_residues=payload.key_residues,
                prepare_for_vina=payload.prepare_for_vina,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return binding_site_to_payload(result.binding_site)

    @app.get(
        "/projects/{project_id}/binding-sites",
        response_model=list[BindingSiteRead],
        tags=["receptor-preparation"],
        summary="List project binding sites",
    )
    def list_binding_sites(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return [binding_site_to_payload(site) for site in list_project_binding_sites(db, project)]

    @app.get(
        "/projects/{project_id}/binding-sites/{binding_site_id}",
        response_model=BindingSiteRead,
        tags=["receptor-preparation"],
        summary="Get project binding site",
    )
    def get_binding_site(
        project_id: str,
        binding_site_id: str,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        site = get_project_binding_site(db, project, binding_site_id)
        if site is None:
            raise HTTPException(status_code=404, detail="Binding site not found")
        return binding_site_to_payload(site)

    @app.post(
        "/projects/{project_id}/candidate-assessment/run",
        response_model=CandidateAssessmentRunResponse,
        tags=["candidate-assessment"],
        summary="Run conformer, docking, ADMET, and synthesis assessment",
    )
    def run_candidate_assessment(
        project_id: str,
        payload: CandidateAssessmentRunRequest | None = None,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        request = payload or CandidateAssessmentRunRequest()
        return run_project_candidate_assessment(
            db=db,
            project=project,
            molecule_ids=request.molecule_ids,
            max_molecules=request.max_molecules,
            binding_site_id=request.binding_site_id,
            protein_file=request.protein_file,
            prepared_ligand_files=request.prepared_ligand_files,
            grid_center=request.grid_center,
            grid_size=request.grid_size,
            key_residues=request.key_residues,
            admet_properties=request.admet_properties,
            max_synthesis_steps=request.max_synthesis_steps,
            prefer_buyable_building_blocks=request.prefer_buyable_building_blocks,
        )

    @app.get(
        "/projects/{project_id}/conformer-results",
        response_model=list[ConformerResultRead],
        tags=["candidate-assessment"],
        summary="List project conformer generation results",
    )
    def list_conformer_results(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return [_conformer_result_to_read(result) for result in list_project_conformer_results(db, project)]

    @app.get(
        "/projects/{project_id}/docking-results",
        response_model=list[DockingResultRead],
        tags=["candidate-assessment"],
        summary="List project docking results",
    )
    def list_docking_results(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return [_docking_result_to_read(result) for result in list_project_docking_results(db, project)]

    @app.get(
        "/projects/{project_id}/admet-results",
        response_model=list[ADMETResultRead],
        tags=["candidate-assessment"],
        summary="List project ADMET results",
    )
    def list_admet_results(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return [_admet_result_to_read(result) for result in list_project_admet_results(db, project)]

    @app.get(
        "/projects/{project_id}/synthesis-routes",
        response_model=list[SynthesisRouteRead],
        tags=["candidate-assessment"],
        summary="List project synthesis route assessments",
    )
    def list_synthesis_routes(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return [_synthesis_route_to_read(result) for result in list_project_synthesis_routes(db, project)]

    @app.post(
        "/projects/{project_id}/rankings/generate",
        response_model=RankingRunResponse,
        tags=["candidate-assessment"],
        summary="Generate project candidate rankings",
    )
    def generate_rankings(
        project_id: str,
        payload: RankingGenerateRequest | None = None,
        db: Session = Depends(get_db),
    ):
        project = _get_project(db, project_id)
        request = payload or RankingGenerateRequest()
        summary = generate_project_rankings(
            db=db,
            project=project,
            molecule_ids=request.molecule_ids,
            max_molecules=request.max_molecules,
            top_n=request.top_n,
        )
        return {"project_id": project.project_id, "ranking": summary.as_dict()}

    @app.get(
        "/projects/{project_id}/rankings",
        response_model=list[RankingRead],
        tags=["candidate-assessment"],
        summary="List project candidate rankings",
    )
    def list_rankings(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return [_ranking_to_read(result) for result in list_project_rankings(db, project)]

    @app.post(
        "/projects/{project_id}/decision-cards/generate",
        response_model=DecisionCardGenerateResponse,
        status_code=201,
        tags=["缁撴灉鏌ヨ"],
        summary="Generate reasoning traces and decision cards",
    )
    def generate_decision_cards(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return generate_project_decision_cards(db, project)

    @app.get(
        "/projects/{project_id}/reasoning-traces",
        response_model=list[ReasoningTraceRead],
        tags=["缁撴灉鏌ヨ"],
        summary="List project reasoning traces",
    )
    def list_reasoning_traces(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        traces = (
            db.query(ReasoningTrace)
            .filter_by(project_id=project_id)
            .order_by(ReasoningTrace.created_at.asc(), ReasoningTrace.id.asc())
            .all()
        )
        return [_reasoning_trace_to_read(trace) for trace in traces]

    @app.get(
        "/projects/{project_id}/decision-cards",
        response_model=list[DecisionCardRead],
        tags=["缁撴灉鏌ヨ"],
        summary="List project decision cards",
    )
    def list_project_decision_cards(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        cards = (
            db.query(DecisionCard)
            .filter_by(project_id=project_id)
            .order_by(DecisionCard.created_at.asc(), DecisionCard.id.asc())
            .all()
        )
        return [_decision_card_to_read(card) for card in cards]

    @app.get(
        "/projects/{project_id}/molecules/{molecule_id}/properties",
        response_model=MoleculePropertyRead,
        tags=["结果查询"],
        summary="查看候选分子性质",
    )
    def get_molecule_properties(project_id: str, molecule_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        molecule = db.query(Molecule).filter_by(project_id=project_id, molecule_id=molecule_id).one_or_none()
        if molecule is None:
            raise HTTPException(status_code=404, detail="未找到该分子")

        properties = db.query(MoleculeProperty).filter_by(molecule_id=molecule_id).one_or_none()
        if properties is None:
            raise HTTPException(status_code=404, detail="该分子尚未生成性质记录，请先运行轻量校验")

        return MoleculePropertyRead(
            molecule_id=properties.molecule_id,
            mw=properties.mw,
            logp=properties.logp,
            tpsa=properties.tpsa,
            hbd=properties.hbd,
            hba=properties.hba,
            sa_score=properties.sa_score,
            tool_metadata=properties.tool_metadata or {},
        )

    @app.get(
        "/projects/{project_id}/molecules/{molecule_id}/decision-cards",
        response_model=list[DecisionCardRead],
        tags=["缁撴灉鏌ヨ"],
        summary="List molecule decision cards",
    )
    def list_molecule_decision_cards(project_id: str, molecule_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        molecule = db.query(Molecule).filter_by(project_id=project_id, molecule_id=molecule_id).one_or_none()
        if molecule is None:
            raise HTTPException(status_code=404, detail="鏈壘鍒拌鍒嗗瓙")
        cards = (
            db.query(DecisionCard)
            .filter_by(project_id=project_id, molecule_id=molecule_id)
            .order_by(DecisionCard.created_at.asc(), DecisionCard.id.asc())
            .all()
        )
        return [_decision_card_to_read(card) for card in cards]

    @app.get(
        "/projects/{project_id}/molecules/{molecule_id}",
        response_model=MoleculeRead,
        tags=["结果查询"],
        summary="查看单个候选分子",
    )
    def get_molecule(project_id: str, molecule_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        molecule = db.query(Molecule).filter_by(project_id=project_id, molecule_id=molecule_id).one_or_none()
        if molecule is None:
            raise HTTPException(status_code=404, detail="未找到该分子")
        return MoleculeRead(
            molecule_id=molecule.molecule_id,
            smiles=molecule.smiles,
            scaffold=molecule.scaffold,
            status=molecule.status,
            labels=molecule.labels,
            source_agent=molecule.source_agent,
        )

    @app.get(
        "/projects/{project_id}/seed-ligands",
        response_model=list[SeedLigandRead],
        tags=["结果查询"],
        summary="查看种子配体",
    )
    def list_seed_ligands(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        ligands = db.query(SeedLigand).filter_by(project_id=project_id).order_by(SeedLigand.id.asc()).all()
        return [
            SeedLigandRead(
                ligand_id=item.ligand_id,
                name=item.name,
                smiles=item.smiles,
                activity_value=item.activity_value,
                activity_unit=item.activity_unit,
                source=item.source,
            )
            for item in ligands
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

    @app.post(
        "/projects/{project_id}/rag/collect",
        response_model=RagCollectResponse,
        status_code=202,
        tags=["RAG"],
        summary="Collect external pack data and index into project RAG",
    )
    def collect_rag_packs(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        from medagent.services.rag_collection import collect_and_index_project_packs

        output = collect_and_index_project_packs(db, app_settings, project)
        run = AgentRun(
            agent_run_id=new_id("RUN"),
            project_id=project.project_id,
            agent_name="rag_collection_agent",
            model_name=app_settings.embedding_model,
            status="completed",
            input_json={"project_id": project.project_id},
            output_json=output,
        )
        db.add(run)
        db.commit()
        return {"agent_run_id": run.agent_run_id, "status": run.status, **output}

    # 注册新的路由
    from medagent.api.chat_router import router as chat_router
    from medagent.api.projects_router import router as projects_router
    from medagent.api.files_router import router as files_router
    from medagent.api.tools_router import router as tools_router

    app.include_router(chat_router)
    app.include_router(projects_router)
    app.include_router(files_router)
    app.include_router(tools_router)

    return app


def _rag_document_to_read(document: RagDocument) -> RagDocumentRead:
    return RagDocumentRead(
        document_id=document.document_id,
        project_id=document.project_id,
        title=document.title,
        source=document.source,
        document_type=document.document_type,
        metadata=document.metadata_json or {},
    )


def _rag_chunk_to_read(chunk: RagChunk) -> RagChunkRead:
    return RagChunkRead(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        page_number=chunk.page_number,
        section=chunk.section,
        content=chunk.content,
        embedding_model=chunk.embedding_model,
        embedding_ref=chunk.embedding_ref,
        token_count=chunk.token_count,
        metadata=chunk.metadata_json or {},
    )


def _evidence_link_to_read(link: EvidenceLink) -> EvidenceLinkRead:
    return EvidenceLinkRead(
        evidence_id=link.evidence_id,
        molecule_id=link.molecule_id,
        chunk_id=link.chunk_id,
        claim_type=link.claim_type,
        confidence=link.confidence,
        rationale=link.rationale,
    )


def _reasoning_trace_to_read(trace: ReasoningTrace) -> ReasoningTraceRead:
    return ReasoningTraceRead(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        molecule_id=trace.molecule_id,
        trace_type=trace.trace_type,
        claim=trace.claim,
        supporting_factors=trace.supporting_factors or [],
        opposing_factors=trace.opposing_factors or [],
        evidence_ids=trace.evidence_ids or [],
        uncertainty=trace.uncertainty,
        next_actions=trace.next_actions or [],
        confidence=trace.confidence,
        source_agent=trace.source_agent,
        provenance=trace.provenance or {},
    )


def _decision_card_to_read(card: DecisionCard) -> DecisionCardRead:
    return DecisionCardRead(
        decision_id=card.decision_id,
        project_id=card.project_id,
        molecule_id=card.molecule_id,
        trace_id=card.trace_id,
        card_type=card.card_type,
        title=card.title,
        decision=card.decision,
        summary=card.summary,
        support=card.support or [],
        risk=card.risk or [],
        next_steps=card.next_steps or [],
        evidence_ids=card.evidence_ids or [],
        confidence=card.confidence,
        provenance=card.provenance or {},
    )


def _rule_filter_result_to_read(result: RuleFilterResult) -> RuleFilterResultRead:
    return RuleFilterResultRead(
        filter_result_id=result.filter_result_id,
        project_id=result.project_id,
        molecule_id=result.molecule_id,
        rule_set=result.rule_set,
        decision=result.decision,
        failed_rules=result.failed_rules or [],
        warnings=result.warnings or [],
        labels=result.labels or [],
        properties_snapshot=result.properties_snapshot or {},
        raw_output=result.raw_output or {},
    )


def _conformer_result_to_read(result) -> ConformerResultRead:
    return ConformerResultRead(
        molecule_id=result.molecule_id,
        conformer_generated=result.conformer_generated,
        conformer_count=result.conformer_count,
        lowest_energy=result.lowest_energy,
        strain_energy=result.strain_energy,
        rmsd_between_conformers=result.rmsd_between_conformers,
        chiral_centers=result.chiral_centers,
        undefined_stereo_centers=result.undefined_stereo_centers,
        labels=result.labels or [],
        conformer_file=result.conformer_file,
        raw_output=result.raw_output or {},
    )


def _docking_result_to_read(result) -> DockingResultRead:
    return DockingResultRead(
        molecule_id=result.molecule_id,
        vina_score=result.vina_score,
        cnn_score=result.cnn_score,
        key_hbond_count=result.key_hbond_count,
        clash_count=result.clash_count,
        pose_file=result.pose_file,
        labels=result.labels or [],
    )


def _admet_result_to_read(result) -> ADMETResultRead:
    return ADMETResultRead(
        molecule_id=result.molecule_id,
        hERG_probability=result.hERG_probability,
        hERG_risk=result.hERG_risk,
        Ames_probability=result.Ames_probability,
        Ames_risk=result.Ames_risk,
        solubility=result.solubility,
        permeability=result.permeability,
        admet_risk_score=result.admet_risk_score,
        labels=result.labels or [],
        raw_output=result.raw_output or {},
    )


def _synthesis_route_to_read(result) -> SynthesisRouteRead:
    return SynthesisRouteRead(
        molecule_id=result.molecule_id,
        route_found=result.route_found,
        route_steps=result.route_steps,
        route_confidence=result.route_confidence,
        buyable_building_blocks=result.buyable_building_blocks,
        labels=result.labels or [],
        route_json=result.route_json or {},
    )


def _ranking_to_read(result) -> RankingRead:
    return RankingRead(
        molecule_id=result.molecule_id,
        rank=result.rank,
        pro_score=result.pro_score,
        con_score=result.con_score,
        evidence_confidence=result.evidence_confidence,
        overall_score=result.overall_score,
        final_decision=result.final_decision,
        score_breakdown=result.score_breakdown or {},
    )


def _get_project(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter_by(project_id=project_id).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="未找到该项目")
    return project


def _get_uploaded_file(db: Session, project_id: str, file_id: str) -> UploadedFileModel:
    uploaded_file = db.query(UploadedFileModel).filter_by(project_id=project_id, file_id=file_id).one_or_none()
    if uploaded_file is None:
        raise HTTPException(status_code=404, detail="未找到该文件")
    return uploaded_file


def _file_parse_result(uploaded_file: UploadedFileModel) -> FileParseResult:
    return FileParseResult(
        file_id=uploaded_file.file_id,
        filename=uploaded_file.filename,
        parse_status=uploaded_file.parse_status,
        metadata=uploaded_file.metadata_json or {},
    )


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
