from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

from medagent.core.config import Settings
from medagent.db.models import Base, Project
from medagent.db.session import build_engine, build_session_factory
from medagent.services.bootstrap import seed_builtin_targets
from medagent.services.rag import build_project_rag_index
from medagent.services.rag_collection import collect_and_index_project_packs


TARGET_IDS = [
    "TGT-EGFR",
    "TGT-ALK",
    "TGT-BRAF",
    "TGT-KRAS-G12C",
    "TGT-JAK2",
    "TGT-BTK",
    "TGT-CDK4-6",
    "TGT-PARP1",
    "TGT-PI3K",
    "TGT-HDAC",
]


def ensure_project(db, target_id: str) -> Project:
    project_id = f"PROJ-RAG-{target_id.replace('TGT-', '').replace('/', '-')}"
    project = db.query(Project).filter_by(project_id=project_id).one_or_none()
    if project is None:
        project = Project(project_id=project_id, name=f"{target_id} RAG validation", target_id=target_id, objective="RAG pack validation")
        db.add(project)
        db.flush()
    return project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-targets", action="store_true")
    parser.add_argument("--target-id", action="append", default=[])
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--output", default="database/rag_verification.json")
    parser.add_argument("--skip-network", action="store_true", help="Skip external collectors and test local build/query only")
    parser.add_argument("--collector-timeout", type=int, default=25, help="Per-collector timeout in seconds")
    args = parser.parse_args()

    settings = Settings(database_url=args.database_url) if args.database_url else Settings()
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)
    with session_factory() as db:
        seed_builtin_targets(db)
        target_ids = args.target_id or TARGET_IDS if args.all_targets else [args.target_id[0]] if args.target_id else ["TGT-EGFR"]
        summaries = []
        for target_id in target_ids:
            project = ensure_project(db, target_id)
            build_summary = build_project_rag_index(db, settings, project, include_builtin_target=True, include_uploads=False, rebuild=True)
            collection_summary = _collect_offline(db, settings, project) if args.skip_network else _collect_with_timeout(db, settings, project, args.collector_timeout)
            query_summary = _sample_queries(db, settings, project)
            summaries.append({
                "target_id": target_id,
                "project_id": project.project_id,
                "build": build_summary,
                "collection": collection_summary,
                "query": query_summary,
            })

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote verification to {output}")
    return 0


def _collect_offline(db, settings, project) -> dict[str, Any]:
    from medagent.data.collect_target_pack import build_pack_documents
    from medagent.services.rag_importers import import_pack_documents

    if not getattr(project, "target_id", None):
        return {"adapter_mode": "external_pack_import", "document_count": 0, "chunk_count": 0, "warnings": ["missing_target_id"]}

    target_payload = _resolve_target_payload(db, project.target_id)
    if not target_payload:
        return {"adapter_mode": "external_pack_import", "document_count": 0, "chunk_count": 0, "warnings": ["target_payload_not_found"]}

    pack_documents = build_pack_documents(target_payload)
    return import_pack_documents(db, settings, project, pack_documents)


def _collect_with_timeout(db, settings, project, timeout: int) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(collect_and_index_project_packs, db, settings, project)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            return {
                "adapter_mode": "external_pack_import",
                "document_count": 0,
                "chunk_count": 0,
                "warnings": [f"collector_timeout:{timeout}s"],
            }


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
        "chembl_target_id": None,
    }


def _sample_queries(db, settings, project):
    from medagent.services.rag import query_project_rag
    queries = [
        f"{project.target_id} inhibitor mechanism",
        f"{project.target_id} resistance and selectivity",
        f"{project.target_id} ADMET safety risk",
    ]
    results = []
    for query in queries:
        result = query_project_rag(db, settings, project, query=query, query_type="validation", top_k=5, create_evidence=False)
        results.append({
            "query": query,
            "retrieved_chunks": len(result.get("retrieved_chunks", [])),
            "confidence": result.get("confidence"),
            "evidence_ids": len(result.get("evidence_ids", [])),
        })
    return results


if __name__ == "__main__":
    sys.exit(main())
