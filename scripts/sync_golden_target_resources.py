#!/usr/bin/env python3
"""Fetch first-party target identities and experimental structures into the resource database."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from medagent.core.config import Settings
from medagent.db.models import (
    BindingSite,
    ScientificArtifact,
    SourceRelease,
    Target,
    TargetExternalId,
    TargetResourceLink,
    TargetResourcePackage,
    TargetStructure,
)
from medagent.db.session import build_session_factory
from medagent.services.ids import new_id
from medagent.services.scientific_execution import sha256_file
from medagent.services.target_resource_packages import (
    GOLDEN_TARGET_RESOURCE_SPECS,
    seed_golden_target_resource_packages,
)


def sync_target_resources(
    database_url: str,
    artifact_root: Path,
    target_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Download UniProt and RCSB source records without claiming docking readiness."""
    artifact_root.mkdir(parents=True, exist_ok=True)
    session_factory = build_session_factory(Settings(database_url=database_url))
    summary = {"updated": [], "failed": []}
    with session_factory() as db, httpx.Client(timeout=45.0, follow_redirects=True) as client:
        seed_golden_target_resource_packages(db)
        retrieved_on = datetime.now(UTC).date().isoformat()
        uniprot_release = _release(
            db,
            f"REL-UNIPROT-FETCH-{retrieved_on}",
            "uniprot",
            f"target_package_fetch_{retrieved_on}",
            "https://rest.uniprot.org/uniprotkb",
            "CC BY 4.0",
            "https://www.uniprot.org/help/license",
        )
        pdb_release = _release(
            db,
            f"REL-RCSB-PDB-FETCH-{retrieved_on}",
            "rcsb_pdb",
            f"target_package_fetch_{retrieved_on}",
            "https://data.rcsb.org/rest/v1",
            "CC0 1.0",
            "https://www.rcsb.org/pages/help/about_us",
        )
        for spec in GOLDEN_TARGET_RESOURCE_SPECS:
            if target_ids and spec["target_id"] not in target_ids:
                continue
            try:
                uniprot = _json(client, f"https://rest.uniprot.org/uniprotkb/{spec['uniprot']}.json")
                entry = _json(client, f"https://data.rcsb.org/rest/v1/core/entry/{spec['pdb_id']}")
                cif_path = artifact_root / spec["target_id"] / f"{spec['pdb_id']}.cif"
                cif_path.parent.mkdir(parents=True, exist_ok=True)
                response = client.get(f"https://files.rcsb.org/download/{spec['pdb_id']}.cif")
                response.raise_for_status()
                cif_path.write_bytes(response.content)
                _persist_target(db, spec, uniprot, entry, cif_path, uniprot_release, pdb_release)
                summary["updated"].append(spec["target_id"])
            except (httpx.HTTPError, OSError, ValueError) as exc:
                summary["failed"].append({"target_id": spec["target_id"], "error": str(exc)})
        uniprot_release.record_count = len(summary["updated"])
        pdb_release.record_count = len(summary["updated"])
        db.commit()
    return summary


def _json(client: httpx.Client, url: str) -> dict[str, Any]:
    response = client.get(url)
    response.raise_for_status()
    return response.json()


def _release(
    db,
    release_id: str,
    source_name: str,
    release_name: str,
    source_url: str,
    license_name: str,
    license_url: str,
) -> SourceRelease:
    release = db.query(SourceRelease).filter_by(source_release_id=release_id).one_or_none()
    if release is None:
        release = SourceRelease(
            source_release_id=release_id,
            source_name=source_name,
            release_name=release_name,
            source_url=source_url,
            license_name=license_name,
            license_url=license_url,
            downloaded_at=datetime.now(UTC),
            metadata_json={"collector": "sync_golden_target_resources"},
        )
        db.add(release)
        db.flush()
    return release


def _persist_target(
    db,
    spec: dict[str, str],
    uniprot: dict[str, Any],
    entry: dict[str, Any],
    cif_path: Path,
    uniprot_release: SourceRelease,
    pdb_release: SourceRelease,
) -> None:
    target = db.query(Target).filter_by(target_id=spec["target_id"]).one()
    _external_id(db, target.target_id, spec["uniprot"], uniprot_release.source_release_id)
    structure = _structure(db, target, spec["pdb_id"], entry, pdb_release.source_release_id)
    artifact = _artifact(db, cif_path)
    link = (
        db.query(TargetResourceLink)
        .filter_by(target_id=target.target_id, artifact_id=artifact.artifact_id, role="experimental_structure")
        .one_or_none()
    )
    if link is None:
        db.add(
            TargetResourceLink(
                target_id=target.target_id,
                artifact_id=artifact.artifact_id,
                role="experimental_structure",
                structure_id=structure.structure_id,
                is_preferred=True,
            )
        )
    site = db.query(BindingSite).filter_by(target_id=target.target_id).first()
    if site is not None:
        site.structure_id = structure.structure_id
        site.receptor_file = str(cif_path.resolve())
        site.preparation_status = "experimental_structure_collected"
        site.artifact_id = artifact.artifact_id
        site.preparation_json = {
            **dict(site.preparation_json or {}),
            "experimental_structure_uri": str(cif_path.resolve()),
            "experimental_structure_sha256": artifact.sha256,
            "source_pdb_id": spec["pdb_id"],
            "warnings": ["raw_mmcif_not_a_prepared_receptor"],
        }
    package = db.query(TargetResourcePackage).filter_by(target_id=target.target_id, package_version="v1").one()
    package.primary_structure_id = structure.structure_id
    package.status = "structure_collected"
    package.source_release_ids = [uniprot_release.source_release_id, pdb_release.source_release_id]
    package.completeness_json = {
        **dict(package.completeness_json or {}),
        "target_identity": bool(uniprot.get("primaryAccession")),
        "experimental_structure_metadata": True,
        "experimental_structure_artifact": True,
        "raw_structure_sha256": artifact.sha256,
        "prepared_receptor": False,
        "verified_pocket": False,
        "reference_ligand_artifact": False,
        "targetdiff_pocket": False,
        "artifact_hashes_complete": False,
    }
    package.warnings = [
        "raw_experimental_structure_collected_not_prepared",
        "reference_ligand_artifact_not_collected",
        "grid_not_validated_by_redock",
        "artifact_hashes_incomplete",
    ]


def _external_id(db, target_id: str, accession: str, release_id: str) -> None:
    if not db.query(TargetExternalId).filter_by(
        target_id=target_id, namespace="uniprot", external_id=accession, source_release_id=release_id
    ).one_or_none():
        db.add(TargetExternalId(target_id=target_id, namespace="uniprot", external_id=accession, taxon_id=9606, source_release_id=release_id))


def _structure(db, target: Target, pdb_id: str, entry: dict[str, Any], release_id: str) -> TargetStructure:
    structure = db.query(TargetStructure).filter_by(
        source="rcsb_pdb", source_structure_id=pdb_id, source_release_id=release_id
    ).one_or_none()
    info = entry.get("rcsb_entry_info") or {}
    exptl = entry.get("exptl") or []
    if structure is None:
        structure = TargetStructure(
            structure_id=new_id("STR"), target_id=target.target_id, source="rcsb_pdb",
            source_structure_id=pdb_id, source_release_id=release_id,
        )
        db.add(structure)
    resolution = info.get("resolution_combined") or []
    structure.experimental_method = (exptl[0].get("method") if exptl else None)
    structure.resolution = float(resolution[0]) if resolution else None
    structure.is_experimental = True
    structure.is_preferred = True
    structure.quality_status = "structure_collected"
    db.flush()
    return structure


def _artifact(db, path: Path) -> ScientificArtifact:
    uri = str(path.resolve())
    digest = sha256_file(path)
    artifact = db.query(ScientificArtifact).filter_by(uri=uri, sha256=digest).one_or_none()
    if artifact is None:
        artifact = ScientificArtifact(
            artifact_id=new_id("ART"), artifact_type="cif", uri=uri, sha256=digest,
            size_bytes=path.stat().st_size, producer_tool="rcsb_pdb_download",
        )
        db.add(artifact)
        db.flush()
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=Settings().database_url)
    parser.add_argument("--artifact-root", default=".local/target_resources")
    parser.add_argument("--target-id", action="append")
    args = parser.parse_args()
    print(sync_target_resources(args.database_url, Path(args.artifact_root), set(args.target_id or [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
