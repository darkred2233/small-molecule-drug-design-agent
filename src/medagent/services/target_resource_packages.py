"""Seed and inspect the ten phase-one target resource package declarations.

The declarations are intentionally metadata-only until a collector has stored
the downloaded receptor, reference ligand, grid and pocket artifacts.  A PDB
identifier alone is not treated as a dockable receptor.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from medagent.data.target_metadata import get_target_metadata
from medagent.db.models import (
    BindingSite,
    SourceRelease,
    Target,
    TargetExternalId,
    TargetResourcePackage,
    TargetStructure,
)
from medagent.services.ids import new_id


GOLDEN_TARGET_RESOURCE_SPECS: tuple[dict[str, str], ...] = (
    {"target_id": "TGT-EGFR", "name": "EGFR", "uniprot": "P00533", "pdb_id": "4ZAU"},
    {"target_id": "TGT-BRAF", "name": "BRAF V600E", "uniprot": "P15056", "pdb_id": "3OG7"},
    {"target_id": "TGT-ALK", "name": "ALK", "uniprot": "Q9UM73", "pdb_id": "2XP2"},
    {"target_id": "TGT-MET", "name": "MET", "uniprot": "P08581", "pdb_id": "3DKF"},
    {"target_id": "TGT-JAK2", "name": "JAK2", "uniprot": "O60674", "pdb_id": "3KRR"},
    {"target_id": "TGT-BTK", "name": "BTK", "uniprot": "Q06187", "pdb_id": "3GEN"},
    {"target_id": "TGT-PI3K", "name": "PIK3CA", "uniprot": "P42336", "pdb_id": "4JPS"},
    {"target_id": "TGT-PARP1", "name": "PARP1", "uniprot": "P09874", "pdb_id": "4UND"},
    {"target_id": "TGT-KRAS-G12C", "name": "KRAS G12C", "uniprot": "P01116", "pdb_id": "6OIM"},
    {"target_id": "TGT-HDAC6", "name": "HDAC6", "uniprot": "Q9UBN7", "pdb_id": "5EDU"},
)

_UNIPROT_RELEASE = {
    "source_release_id": "REL-UNIPROT-2026-07",
    "source_name": "uniprot",
    "release_name": "2026_03",
    "source_url": "https://rest.uniprot.org/",
    "license_name": "CC BY 4.0",
    "license_url": "https://www.uniprot.org/help/license",
}
_RCSB_RELEASE = {
    "source_release_id": "REL-RCSB-PDB-2026-07",
    "source_name": "rcsb_pdb",
    "release_name": "metadata_snapshot_2026-07-23",
    "source_url": "https://data.rcsb.org/",
    "license_name": "CC0 1.0",
    "license_url": "https://www.rcsb.org/pages/help/about_us",
}


def seed_golden_target_resource_packages(db: Session) -> dict[str, Any]:
    """Idempotently seed phase-one package metadata and release provenance."""
    uniprot_release = _upsert_source_release(db, _UNIPROT_RELEASE)
    pdb_release = _upsert_source_release(db, _RCSB_RELEASE)
    created_packages = 0
    updated_packages = 0

    for spec in GOLDEN_TARGET_RESOURCE_SPECS:
        target = _ensure_target(db, spec)
        _upsert_external_id(db, target.target_id, spec["uniprot"], uniprot_release.source_release_id)
        structure = _upsert_structure(db, target.target_id, spec["pdb_id"], pdb_release.source_release_id)
        site = _upsert_binding_site(db, target.target_id, spec, structure.structure_id)
        package = (
            db.query(TargetResourcePackage)
            .filter_by(target_id=target.target_id, package_version="v1")
            .one_or_none()
        )
        if package is None:
            package = TargetResourcePackage(
                package_id=new_id("PACK"),
                target_id=target.target_id,
                package_version="v1",
            )
            db.add(package)
            created_packages += 1
        else:
            updated_packages += 1
        package.uniprot_accession = spec["uniprot"]
        package.primary_structure_id = structure.structure_id
        package.binding_site_id = site.binding_site_id
        package.reference_ligand_id = site.reference_ligand_id
        package.status = "metadata_ready"
        package.source_release_ids = [uniprot_release.source_release_id, pdb_release.source_release_id]
        package.completeness_json = _metadata_completeness(site)
        package.warnings = [
            "receptor_artifact_not_collected",
            "reference_ligand_artifact_not_collected",
            "grid_not_validated_by_redock",
            "artifact_hashes_incomplete",
        ]

    return {
        "target_count": len(GOLDEN_TARGET_RESOURCE_SPECS),
        "created_packages": created_packages,
        "updated_packages": updated_packages,
        "status": "metadata_ready",
    }


def target_resource_readiness(
    db: Session, target_id: str | None
) -> tuple[dict[str, Any], list[str]]:
    """Return the snapshot-ready resource status without claiming absent files exist."""
    if not target_id:
        return {"target_id": None}, []
    package = (
        db.query(TargetResourcePackage)
        .filter_by(target_id=target_id, package_version="v1")
        .one_or_none()
    )
    if package is None:
        return {"target_id": target_id, "package_status": "missing"}, []
    completeness = dict(package.completeness_json or {})
    completeness.update(
        {
            "target_id": target_id,
            "package_id": package.package_id,
            "package_status": package.status,
            "binding_site_id": package.binding_site_id,
        }
    )
    return completeness, list(package.source_release_ids or [])


def _upsert_source_release(db: Session, payload: dict[str, str]) -> SourceRelease:
    release = db.query(SourceRelease).filter_by(source_release_id=payload["source_release_id"]).one_or_none()
    if release is None:
        release = SourceRelease(
            source_release_id=payload["source_release_id"],
            source_name=payload["source_name"],
            release_name=payload["release_name"],
            downloaded_at=datetime.now(UTC),
        )
        db.add(release)
    release.source_url = payload["source_url"]
    release.license_name = payload["license_name"]
    release.license_url = payload["license_url"]
    release.metadata_json = {"seeded_by": "golden_target_resource_packages"}
    db.flush()
    return release


def _ensure_target(db: Session, spec: dict[str, str]) -> Target:
    target = db.query(Target).filter_by(target_id=spec["target_id"]).one_or_none()
    if target is None:
        target = Target(
            target_id=spec["target_id"],
            name=spec["name"],
            aliases=[],
            uniprot_id=spec["uniprot"],
            species="Homo sapiens",
            pdb_ids=[spec["pdb_id"]],
            summary="Phase-one golden target resource package declaration.",
        )
        db.add(target)
        db.flush()
    return target


def _upsert_external_id(
    db: Session, target_id: str, uniprot_accession: str, source_release_id: str
) -> None:
    exists = (
        db.query(TargetExternalId)
        .filter_by(
            target_id=target_id,
            namespace="uniprot",
            external_id=uniprot_accession,
            source_release_id=source_release_id,
        )
        .one_or_none()
    )
    if exists is None:
        db.add(
            TargetExternalId(
                target_id=target_id,
                namespace="uniprot",
                external_id=uniprot_accession,
                taxon_id=9606,
                source_release_id=source_release_id,
            )
        )


def _upsert_structure(db: Session, target_id: str, pdb_id: str, source_release_id: str) -> TargetStructure:
    structure = (
        db.query(TargetStructure)
        .filter_by(source="rcsb_pdb", source_structure_id=pdb_id, source_release_id=source_release_id)
        .one_or_none()
    )
    if structure is None:
        structure = TargetStructure(
            structure_id=new_id("STR"),
            target_id=target_id,
            source="rcsb_pdb",
            source_structure_id=pdb_id,
            is_experimental=True,
            is_preferred=True,
            quality_status="metadata_only",
            source_release_id=source_release_id,
        )
        db.add(structure)
        db.flush()
    return structure


def _upsert_binding_site(
    db: Session, target_id: str, spec: dict[str, str], structure_id: str
) -> BindingSite:
    metadata = get_target_metadata(target_id)
    sites = list(metadata.get("binding_sites") or [])
    site_metadata = next((site for site in sites if site.get("pdb_id") == spec["pdb_id"]), None)
    site_metadata = site_metadata or (sites[0] if sites else {})
    binding_site_id = site_metadata.get("binding_site_id") or f"SITE-{target_id}-{spec['pdb_id']}"
    site = db.query(BindingSite).filter_by(binding_site_id=binding_site_id).one_or_none()
    if site is None:
        site = BindingSite(
            binding_site_id=binding_site_id,
            target_id=target_id,
            key_residues=[],
            grid_box={},
        )
        db.add(site)
    grid_box = dict(site_metadata.get("grid_box") or {})
    reference_ligand = site_metadata.get("reference_ligand")
    site.target_id = target_id
    site.pdb_id = spec["pdb_id"]
    site.structure_id = structure_id
    site.reference_ligand_id = reference_ligand
    site.receptor_file = site_metadata.get("source_url") or f"https://www.rcsb.org/structure/{spec['pdb_id']}"
    site.prepared_receptor_file = None
    site.preparation_status = "metadata_only"
    site.key_residues = list(site_metadata.get("key_residues") or [])
    site.pocket_residues_json = list(site_metadata.get("key_residues") or [])
    site.grid_box = grid_box
    site.pocket_method = grid_box.get("method")
    site.validation_status = "metadata_only"
    site.redock_rmsd = None
    site.preparation_json = {
        "source": "golden_target_resource_registry",
        "pdb_id": spec["pdb_id"],
        "reference_ligand_metadata": reference_ligand,
        "warnings": ["metadata_only_not_a_prepared_receptor"],
    }
    db.flush()
    return site


def _metadata_completeness(site: BindingSite) -> dict[str, bool]:
    return {
        "target_identity": True,
        "experimental_structure_metadata": True,
        "prepared_receptor": False,
        "verified_pocket": False,
        "reference_ligand": bool(site.reference_ligand_id),
        "reference_ligand_artifact": False,
        "grid_metadata": bool((site.grid_box or {}).get("center")),
        "targetdiff_pocket": False,
        "artifact_hashes_complete": False,
    }
