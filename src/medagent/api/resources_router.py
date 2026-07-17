"""项目资源 API router。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from medagent.db.models import Project, ProjectResource, TargetLigand
from medagent.db.session import get_db
from medagent.domain.schemas import ProjectResourceRead, TargetLigandRead

router = APIRouter(prefix="/projects/{project_id}/resources", tags=["resources"])


@router.get("", response_model=list[ProjectResourceRead])
def list_resources(project_id: str, db: Session = Depends(get_db)) -> list[ProjectResourceRead]:
    """列出项目资源。"""
    _ensure_project(db, project_id)
    resources = db.query(ProjectResource).filter(
        ProjectResource.project_id == project_id,
    ).order_by(ProjectResource.created_at).all()
    return [_resource_to_read(r) for r in resources]


@router.get("/ligands", response_model=list[TargetLigandRead])
def list_target_ligands(project_id: str, db: Session = Depends(get_db)) -> list[TargetLigandRead]:
    """列出靶点已知配体。"""
    project = _ensure_project(db, project_id)
    if not project.target_id:
        return []
    ligands = db.query(TargetLigand).filter(
        TargetLigand.target_id == project.target_id,
    ).all()
    return [_ligand_to_read(l) for l in ligands]


@router.post("/collect-target-pack")
def collect_target_pack(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """自动收集靶点数据包。"""
    project = _ensure_project(db, project_id)
    if not project.target_id:
        raise HTTPException(400, "Project has no target_id")

    from medagent.data.collect_target_pack import build_pack_documents
    from medagent.db.models import Target

    target = db.query(Target).filter(Target.target_id == project.target_id).first()
    if not target:
        raise HTTPException(404, f"Target {project.target_id} not found")

    target_payload = {
        "target_id": target.target_id,
        "name": target.name,
        "aliases": target.aliases or [],
        "uniprot_id": target.uniprot_id,
        "pdb_ids": target.pdb_ids or [],
        "drugs": [],
    }

    docs = build_pack_documents(target_payload)
    return {
        "target_id": target.target_id,
        "document_count": len(docs),
        "documents": [{"type": d.document_type, "title": d.title} for d in docs],
    }


@router.post("/resolve-autogrow4")
def resolve_autogrow4_resources(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """解析 AutoGrow4 资源。"""
    project = _ensure_project(db, project_id)

    from medagent.domain.schemas import AutoGrow4CampaignConfig
    from medagent.services.autogrow4_resources import resolve_autogrow4_resources

    config = AutoGrow4CampaignConfig()
    try:
        bundle = resolve_autogrow4_resources(db, project, config)
        return bundle.model_dump()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ensure_project(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


def _resource_to_read(r: ProjectResource) -> ProjectResourceRead:
    return ProjectResourceRead(
        resource_id=r.resource_id,
        project_id=r.project_id,
        target_id=r.target_id,
        resource_type=r.resource_type,
        scope=r.scope,
        name=r.name,
        file_path=r.file_path,
        metadata_json=r.metadata_json,
        confidence_level=r.confidence_level,
        source_url=r.source_url,
    )


def _ligand_to_read(l: TargetLigand) -> TargetLigandRead:
    return TargetLigandRead(
        target_ligand_id=l.target_ligand_id,
        target_id=l.target_id,
        name=l.name,
        smiles=l.smiles,
        canonical_smiles=l.canonical_smiles,
        inchi_key=l.inchi_key,
        source=l.source,
        source_id=l.source_id,
        activity_value=l.activity_value,
        activity_unit=l.activity_unit,
        activity_type=l.activity_type,
        pchembl_value=l.pchembl_value,
        assay_type=l.assay_type,
        confidence_level=l.confidence_level,
    )
