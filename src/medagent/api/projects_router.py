from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from medagent.db.models import Molecule, Project
from medagent.db.session import get_db
from medagent.domain.schemas import ProjectCreate, ProjectRead
from medagent.services.ids import new_id

router = APIRouter(prefix="/projects", tags=["项目管理"])


class ProjectStats(BaseModel):
    total_molecules: int = Field(title="候选分子总数")
    evaluated_molecules: int = Field(title="已评估分子数")
    excellent_molecules: int = Field(title="推荐分子数")
    good_molecules: int = Field(title="备选分子数")


@router.post("/", response_model=ProjectRead, status_code=201, include_in_schema=False)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
):
    new_project = Project(
        project_id=new_id("PROJ"),
        name=payload.name,
        target_id=payload.target_id,
        objective=payload.objective,
        constraints_json=payload.constraints,
        status="created",
    )

    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    return _project_to_read(new_project)


@router.get("", response_model=list[ProjectRead], summary="列出项目")
def list_projects(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    projects = db.query(Project).order_by(Project.created_at.desc()).offset(skip).limit(limit).all()
    return [_project_to_read(project) for project in projects]


@router.get("/", response_model=list[ProjectRead], include_in_schema=False)
def list_projects_with_trailing_slash(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return list_projects(skip=skip, limit=limit, db=db)


@router.get("/{project_id}", response_model=ProjectRead, summary="获取项目详情")
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(project_id=project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    return _project_to_read(project)


@router.get("/{project_id}/stats", response_model=ProjectStats, summary="获取项目统计")
def get_project_stats(
    project_id: str,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(project_id=project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    total = db.query(Molecule).filter_by(project_id=project_id).count()
    evaluated = (
        db.query(Molecule)
        .filter(
            Molecule.project_id == project_id,
            Molecule.status.in_(
                [
                    "candidate_assessed",
                    "recommended",
                    "reserve",
                    "passed_filter",
                    "docking_passed",
                    "admet_risky",
                    "synthesis_risky",
                ]
            ),
        )
        .count()
    )

    return ProjectStats(
        total_molecules=total,
        evaluated_molecules=evaluated,
        excellent_molecules=db.query(Molecule).filter_by(project_id=project_id, status="recommended").count(),
        good_molecules=db.query(Molecule).filter_by(project_id=project_id, status="reserve").count(),
    )


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter_by(project_id=project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    db.delete(project)
    db.commit()

    return {"message": "项目已删除"}


def _project_to_read(project: Project) -> ProjectRead:
    return ProjectRead(
        project_id=project.project_id,
        name=project.name,
        target_id=project.target_id,
        objective=project.objective,
        status=project.status,
        created_at=project.created_at,
    )
