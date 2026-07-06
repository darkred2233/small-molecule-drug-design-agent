from collections.abc import Generator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
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
        with session_factory() as db:
            seed_builtin_targets(db)
        yield

    app = FastAPI(title=app_settings.app_name, version="0.1.0", lifespan=lifespan)

    def get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": app_settings.app_name}

    @app.get("/builtin-targets", response_model=list[BuiltinTargetRead])
    def list_builtin_targets(db: Session = Depends(get_db)):
        targets = db.query(Target).order_by(Target.name).all()
        return [_target_to_read(target) for target in targets]

    @app.get("/builtin-targets/{target_id}", response_model=BuiltinTargetRead)
    def get_builtin_target(target_id: str, db: Session = Depends(get_db)):
        target = db.query(Target).filter_by(target_id=target_id).one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="Target not found")
        return _target_to_read(target)

    @app.post("/projects", response_model=ProjectRead, status_code=201)
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

    @app.post("/projects/{project_id}/chat", response_model=ChatResponse)
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

    @app.post("/projects/{project_id}/files", response_model=UploadedFileRead, status_code=202)
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

    @app.post("/projects/{project_id}/ingest", status_code=202)
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

    @app.post("/projects/{project_id}/run", response_model=ProjectStatus, status_code=202)
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
                detail="Only dry_run is available until external tool adapters are configured.",
            )
        PipelineOrchestrator(app_settings).create_dry_run(db, project)
        db.refresh(project)
        return _project_status(db, project)

    @app.post("/projects/{project_id}/rounds", response_model=ProjectStatus, status_code=202)
    def create_round(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        PipelineOrchestrator(app_settings).create_dry_run(db, project)
        db.refresh(project)
        return _project_status(db, project)

    @app.post("/projects/{project_id}/advisor/apply", status_code=202)
    def apply_advice(project_id: str, db: Session = Depends(get_db)):
        _get_project(db, project_id)
        return {"status": "queued", "message": "Advisor application will be implemented in M6."}

    @app.get("/projects/{project_id}/status", response_model=ProjectStatus)
    def get_status(project_id: str, db: Session = Depends(get_db)):
        project = _get_project(db, project_id)
        return _project_status(db, project)

    @app.get("/projects/{project_id}/constraints", response_model=list[ConstraintRead])
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

    @app.get("/projects/{project_id}/molecules", response_model=list[MoleculeRead])
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

    @app.get("/projects/{project_id}/advice", response_model=list[AdviceRead])
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

    @app.get("/projects/{project_id}/report")
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
        raise HTTPException(status_code=404, detail="Project not found")
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
