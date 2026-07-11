from __future__ import annotations

from typing import Any

from sqlalchemy import text

from medagent.data.collect_target_pack import PackDocument
from medagent.rag.chunking import chunk_text
from medagent.rag.embedding import build_embedding_client, embedding_ref
from medagent.services.ids import new_id
from medagent.db.models import RagDocument, RagChunk


def import_pack_documents(db, settings, project, pack_documents: list[PackDocument]) -> dict[str, Any]:
    embedding_client = build_embedding_client(settings)
    documents_summaries: list[dict[str, Any]] = []
    warnings: list[str] = []

    for pack_doc in pack_documents:
        try:
            summary = _import_single_pack_document(
                db=db,
                settings=settings,
                project=project,
                pack_doc=pack_doc,
                embedding_client=embedding_client,
            )
            documents_summaries.append(summary)
        except Exception as exc:
            warnings.append(f"{pack_doc.document_type}:{pack_doc.title}:{exc}")

    return {
        "adapter_mode": "external_pack_import",
        "document_count": len(documents_summaries),
        "chunk_count": sum(item["chunk_count"] for item in documents_summaries),
        "documents": documents_summaries,
        "warnings": warnings,
    }


def _import_single_pack_document(db, settings, project, pack_doc: PackDocument, embedding_client) -> dict[str, Any]:
    document = RagDocument(
        document_id=new_id("DOC"),
        project_id=project.project_id,
        title=pack_doc.title[:300],
        source=pack_doc.source,
        document_type=pack_doc.document_type,
        metadata_json={
            **(pack_doc.metadata or {}),
            "adapter_mode": "external_pack_import",
            "target_id": pack_doc.target_id,
            "chunk_size": settings.rag_chunk_size,
            "chunk_overlap": settings.rag_chunk_overlap,
        },
    )
    db.add(document)
    db.flush()

    text = pack_doc.content or ""
    if not text.strip():
        return {
            "document_id": document.document_id,
            "title": document.title,
            "source": document.source,
            "document_type": document.document_type,
            "chunk_count": 0,
            "embedding_model": embedding_client.model_name,
        }

    chunks = chunk_text(text, chunk_size=settings.rag_chunk_size, overlap=settings.rag_chunk_overlap)
    embeddings = embedding_client.embed_texts([chunk.content for chunk in chunks], input_type="document")
    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True), start=1):
        rag_chunk = RagChunk(
            chunk_id=new_id("CHK"),
            document_id=document.document_id,
            page_number=chunk.page_number,
            section=chunk.section,
            content=chunk.content,
            embedding_model=embedding_client.model_name,
            embedding_ref=embedding_ref(embedding_client.model_name, chunk.content),
            embedding_json=embedding,
            token_count=len(chunk.content.split()),
            metadata_json={**(chunk.metadata or {}), "chunk_index": index, "pack_document_type": pack_doc.document_type},
        )
        db.add(rag_chunk)
        db.flush()
        _store_pgvector_embedding(db, rag_chunk.chunk_id, embedding)

    return {
        "document_id": document.document_id,
        "title": document.title,
        "source": document.source,
        "document_type": document.document_type,
        "chunk_count": len(chunks),
        "embedding_model": embedding_client.model_name,
    }


def _store_pgvector_embedding(db, chunk_id: str, embedding: list[float]) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql" or len(embedding) != 2048:
        return
    vector_literal = "[" + ",".join(str(value) for value in embedding) + "]"
    db.execute(
        text("UPDATE rag_chunks SET embedding_vector = CAST(:embedding AS vector) WHERE chunk_id = :chunk_id"),
        {"embedding": vector_literal, "chunk_id": chunk_id},
    )
