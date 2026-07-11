"""
Projects API路由 - 项目管理
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from medagent.db.models import Molecule, Project
from medagent.db.session import get_db
from medagent.services.ids import new_id

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    project_name: str
    target_protein: str
    disease_area: str
    description: str | None = None


class ProjectResponse(BaseModel):
    project_id: str
    project_name: str
    target_protein: str
    disease_area: str
    status: str
    created_at: str

    class Config:
        from_attributes = True


class ProjectStats(BaseModel):
    total_molecules: int
    evaluated_molecules: int
    excellent_molecules: int
    good_molecules: int


@router.post("/", response_model=ProjectResponse)
def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db),
):
    """创建项目"""
    new_project = Project(
        project_id=new_id("proj"),
        project_name=project.project_name,
        target_protein=project.target_protein,
        disease_area=project.disease_area,
        description=project.description,
        status="created",
    )

    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    return new_project


@router.get("/", response_model=list[ProjectResponse])
def list_projects(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """列出所有项目"""
    projects = db.query(Project).offset(skip).limit(limit).all()
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
):
    """获取项目详情"""
    project = db.query(Project).filter_by(project_id=project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    return project


@router.get("/{project_id}/stats", response_model=ProjectStats)
def get_project_stats(
    project_id: str,
    db: Session = Depends(get_db),
):
    """获取项目统计"""
    project = db.query(Project).filter_by(project_id=project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    total = db.query(Molecule).filter_by(project_id=project_id).count()

    # 简化统计
    return ProjectStats(
        total_molecules=total,
        evaluated_molecules=0,
        excellent_molecules=0,
        good_molecules=0,
    )


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
):
    """删除项目"""
    project = db.query(Project).filter_by(project_id=project_id).first()

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    db.delete(project)
    db.commit()

    return {"message": "项目已删除"}
