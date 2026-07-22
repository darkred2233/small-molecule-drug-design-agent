"""Resolve a project-local PDB pocket for TargetDiff generation."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from medagent.db.models import BindingSite, Project, ProjectResource
from medagent.domain.schemas import TargetDiffCampaignConfig, TargetDiffResourceBundle


def resolve_targetdiff_resources(
    db: Session,
    project: Project,
    config: TargetDiffCampaignConfig,
) -> TargetDiffResourceBundle:
    """Choose a validated project PDB pocket without crossing project boundaries."""
    if config.pocket_resource_id:
        resource = (
            db.query(ProjectResource)
            .filter(
                ProjectResource.resource_id == config.pocket_resource_id,
                ProjectResource.project_id == project.project_id,
            )
            .first()
        )
        if resource is None:
            raise ValueError("TargetDiff selected pocket resource was not found in this project")
        if resource.resource_type != "binding_pocket":
            raise ValueError("TargetDiff selected resource must have type binding_pocket")
        return _bundle_from_resource(resource)

    if config.binding_site_id:
        site = (
            db.query(BindingSite)
            .filter(
                BindingSite.binding_site_id == config.binding_site_id,
                BindingSite.project_id == project.project_id,
            )
            .first()
        )
        if site is None:
            raise ValueError("TargetDiff selected binding site was not found in this project")
        return _bundle_from_binding_site(site)

    resources = (
        db.query(ProjectResource)
        .filter(
            ProjectResource.project_id == project.project_id,
            ProjectResource.resource_type == "binding_pocket",
        )
        .order_by(ProjectResource.created_at.desc(), ProjectResource.id.desc())
        .all()
    )
    for resource in resources:
        try:
            return _bundle_from_resource(resource)
        except ValueError:
            continue

    sites = (
        db.query(BindingSite)
        .filter(BindingSite.project_id == project.project_id)
        .order_by(BindingSite.created_at.desc(), BindingSite.id.desc())
        .all()
    )
    sites.sort(key=lambda site: site.preparation_status != "prepared")
    for site in sites:
        try:
            return _bundle_from_binding_site(site)
        except ValueError:
            continue

    raise ValueError(
        "TargetDiff requires a project binding_pocket PDB resource or a binding site with a local PDB receptor"
    )


def _bundle_from_resource(resource: ProjectResource) -> TargetDiffResourceBundle:
    return TargetDiffResourceBundle(
        pocket_file=_pdb_file(resource.file_path, "TargetDiff pocket resource"),
        pocket_resource_id=resource.resource_id,
        provenance={
            "source": "project_resource",
            "resource_type": resource.resource_type,
            "resource_scope": resource.scope,
            "resource_name": resource.name,
        },
    )


def _bundle_from_binding_site(site: BindingSite) -> TargetDiffResourceBundle:
    path = site.prepared_receptor_file or site.receptor_file
    return TargetDiffResourceBundle(
        pocket_file=_pdb_file(path, "TargetDiff binding site receptor"),
        binding_site_id=site.binding_site_id,
        provenance={
            "source": "binding_site",
            "preparation_status": site.preparation_status,
            "used_prepared_receptor": bool(site.prepared_receptor_file),
        },
    )


def _pdb_file(configured_path: str | None, description: str) -> str:
    if not configured_path:
        raise ValueError(f"{description} path is missing")
    path = Path(configured_path.removeprefix("local://")).expanduser()
    if path.suffix.lower() != ".pdb":
        raise ValueError(f"{description} must be a .pdb file")
    if not path.is_file():
        raise ValueError(f"{description} file does not exist")
    return str(path)
