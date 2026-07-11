from __future__ import annotations

from typing import Any

from medagent.data.collect_target_pack import build_pack_documents
from medagent.services.rag_importers import import_pack_documents


def collect_and_index_project_packs(db, settings, project) -> dict[str, Any]:
    if not getattr(project, "target_id", None):
        return {"adapter_mode": "external_pack_import", "document_count": 0, "chunk_count": 0, "warnings": ["missing_target_id"]}

    target_payload = _resolve_target_payload(db, project.target_id)
    if not target_payload:
        return {"adapter_mode": "external_pack_import", "document_count": 0, "chunk_count": 0, "warnings": ["target_payload_not_found"]}

    pack_documents = build_pack_documents(target_payload)
    return import_pack_documents(db, settings, project, pack_documents)


def _resolve_target_payload(db, target_id: str) -> dict[str, Any] | None:
    from medagent.db.models import Target

    target = db.query(Target).filter_by(target_id=target_id).one_or_none()
    if target is None:
        return None
    drugs = []
    for row in target.drugs:
        drugs.append((
            row.drug_name,
            row.drug_status,
            row.mechanism,
            row.indication,
        ))
    return {
        "target_id": target.target_id,
        "name": target.name,
        "aliases": target.aliases or [],
        "uniprot_id": target.uniprot_id,
        "species": target.species,
        "pdb_ids": target.pdb_ids or [],
        "summary": target.summary,
        "drugs": drugs,
        "chembl_target_id": _guess_chembl_target_id(target),
    }


def _guess_chembl_target_id(target) -> str | None:
    return None
