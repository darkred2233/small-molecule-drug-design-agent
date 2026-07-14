import html
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.data.target_metadata import get_target_metadata
from medagent.db.models import AgentRun, EvidenceLink, Project, RagChunk, RagDocument, Target, UploadedFile
from medagent.rag.chunking import chunk_text
from medagent.rag.embedding import build_embedding_client, embedding_ref
from medagent.rag.rerank import build_reranker
from medagent.rag.retrieval import RetrievalCandidate, retrieve_candidates
from medagent.services.ids import new_id


RAG_BUILDER_AGENT_NAME = "rag_builder_agent"
RAG_RETRIEVAL_AGENT_NAME = "rag_agent"
RAG_ADAPTER_MODE = "hybrid_bm25_vector_rag"
RAG_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".pdf", ".html", ".htm", ".docx"}


@dataclass
class IndexedDocumentSummary:
    document_id: str
    title: str
    source: str
    document_type: str
    chunk_count: int
    embedding_model: str
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source": self.source,
            "document_type": self.document_type,
            "chunk_count": self.chunk_count,
            "embedding_model": self.embedding_model,
            "warnings": self.warnings,
        }


def build_project_rag_index(
    db: Session,
    settings: Settings,
    project: Project,
    *,
    include_builtin_target: bool = True,
    include_uploads: bool = True,
    file_ids: list[str] | None = None,
    rebuild: bool = True,
) -> dict[str, Any]:
    run = create_agent_run(
        db,
        project,
        RAG_BUILDER_AGENT_NAME,
        model_name=settings.embedding_model,
        input_json={
            "include_builtin_target": include_builtin_target,
            "include_uploads": include_uploads,
            "file_ids": file_ids or [],
            "rebuild": rebuild,
        },
    )
    summaries: list[IndexedDocumentSummary] = []
    warnings: list[str] = []

    if include_builtin_target and project.target_id:
        target_summary = index_builtin_target(db, settings, project, rebuild=rebuild)
        if target_summary:
            summaries.append(target_summary)

    if include_uploads:
        uploaded_files = select_uploaded_files(db, project, file_ids)
        for uploaded_file in uploaded_files:
            try:
                summary = index_uploaded_file(db, settings, project, uploaded_file, rebuild=rebuild)
            except Exception as exc:
                warnings.append(f"{uploaded_file.file_id}: {exc}")
                continue
            if summary is not None:
                summaries.append(summary)

    output = rag_build_summary(project.project_id, summaries, warnings)
    finish_agent_run(run, output)
    db.commit()
    return {"agent_run_id": run.agent_run_id, "status": run.status, **output}


def crawl_project_urls(
    db: Session,
    settings: Settings,
    project: Project,
    *,
    urls: list[str],
    document_type: str = "web",
    rebuild: bool = True,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    run = create_agent_run(
        db,
        project,
        RAG_BUILDER_AGENT_NAME,
        model_name=settings.embedding_model,
        input_json={"urls": urls, "document_type": document_type, "rebuild": rebuild},
    )
    summaries: list[IndexedDocumentSummary] = []
    warnings: list[str] = []

    for url in urls:
        try:
            text_content, title = fetch_url_text(url, timeout_seconds=timeout_seconds)
            summary = index_text_document(
                db,
                settings,
                project_id=project.project_id,
                title=title or url,
                source=url,
                document_type=document_type,
                text_content=text_content,
                metadata={"source_kind": "crawl"},
                rebuild=rebuild,
            )
            summaries.append(summary)
        except Exception as exc:
            warnings.append(f"{url}: {exc}")

    output = rag_build_summary(project.project_id, summaries, warnings)
    finish_agent_run(run, output)
    db.commit()
    return {"agent_run_id": run.agent_run_id, "status": run.status, **output}


def query_project_rag(
    db: Session,
    settings: Settings,
    project: Project,
    *,
    query: str,
    query_type: str = "general",
    top_k: int | None = None,
    molecule_id: str | None = None,
    create_evidence: bool = True,
) -> dict[str, Any]:
    top_k = top_k or settings.rag_default_top_k
    run = create_agent_run(
        db,
        project,
        RAG_RETRIEVAL_AGENT_NAME,
        model_name=settings.rerank_model,
        input_json={"query": query, "query_type": query_type, "top_k": top_k, "molecule_id": molecule_id},
    )
    embedding_client = build_embedding_client(settings)
    query_embedding = embedding_client.embed_texts([query], input_type="query")[0]
    chunks, documents_by_id = load_project_chunks(db, project)
    candidates = retrieve_candidates(
        query=query,
        query_embedding=query_embedding,
        chunks=chunks,
        documents_by_id=documents_by_id,
        vector_top_k=settings.rag_vector_top_k,
        keyword_top_k=settings.rag_keyword_top_k,
    )
    ranked = rerank_candidates(settings, query, candidates, top_k)
    retrieved_chunks = [
        candidate_to_payload(
            db,
            candidate,
            query=query,
            query_type=query_type,
            molecule_id=molecule_id,
            create_evidence=create_evidence,
        )
        for candidate in ranked
    ]
    evidence_ids = [item["evidence_id"] for item in retrieved_chunks if item.get("evidence_id")]
    output = {
        "query": query,
        "query_type": query_type,
        "retrieved_chunks": retrieved_chunks,
        "evidence_ids": evidence_ids,
        "confidence": retrieval_confidence(retrieved_chunks),
        "missing_information": [] if retrieved_chunks else ["rag_retrieval_no_results"],
        "adapter_mode": RAG_ADAPTER_MODE,
    }
    finish_agent_run(run, output)
    db.commit()
    return {"agent_run_id": run.agent_run_id, **output}


def index_builtin_target(
    db: Session,
    settings: Settings,
    project: Project,
    *,
    rebuild: bool,
) -> IndexedDocumentSummary | None:
    target = db.query(Target).filter_by(target_id=project.target_id).one_or_none()
    if target is None:
        return None
    lines = [
        f"Target: {target.name} ({target.target_id})",
        f"Aliases: {', '.join(target.aliases or [])}",
        f"UniProt: {target.uniprot_id or 'unknown'}",
        f"Species: {target.species or 'unknown'}",
        f"Representative PDB structures: {', '.join(target.pdb_ids or [])}",
        "",
        target.summary or "",
    ]
    metadata = get_target_metadata(target.target_id)
    if target.pocket_summary or metadata.get("pocket_summary"):
        lines.extend(["", f"Pocket summary: {target.pocket_summary or metadata.get('pocket_summary')}"])
    for site in metadata.get("binding_sites", []):
        grid_box = site.get("grid_box") or {}
        lines.extend(
            [
                "",
                f"Binding site: {site.get('site_name') or site.get('binding_site_id')}",
                f"PDB: {site.get('pdb_id')} reference ligand: {site.get('reference_ligand')}",
                f"Grid center: {grid_box.get('center')} size: {grid_box.get('size')} {grid_box.get('unit') or ''}".strip(),
                f"Key residues: {', '.join(site.get('key_residues') or [])}",
            ]
        )
    if metadata.get("sar_rules"):
        lines.extend(["", "Target SAR rules:"])
        for rule in metadata["sar_rules"]:
            lines.append(
                f"- {rule.get('title')}: {rule.get('rationale')} "
                f"Preferred: {rule.get('preferred_change')} Avoid: {rule.get('avoid')}"
            )
    if metadata.get("admet_risks"):
        lines.extend(["", "Target ADMET risks:"])
        for risk in metadata["admet_risks"]:
            lines.append(
                f"- {risk.get('category')}: {risk.get('signal')} "
                f"Mitigation: {risk.get('mitigation')} Severity: {risk.get('severity')}"
            )
    lines.extend(["", "Representative drugs and mechanisms:"])
    for drug in target.drugs:
        refs = drug.external_refs or {}
        lines.extend(
            [
                f"- {drug.drug_name}: {drug.mechanism or 'mechanism unknown'}; "
                f"status={drug.drug_status or 'unknown'}; indication={drug.indication or 'unknown'}; "
                f"PubChem CID={drug.pubchem_cid or 'unknown'}; InChIKey={drug.inchi_key or 'unknown'}; "
                f"source={drug.evidence_source or 'MVP seed catalog'}; refs={refs}",
            ]
        )
    return index_text_document(
        db,
        settings,
        project_id=project.project_id,
        title=f"{target.name} built-in target-drug knowledge",
        source=f"builtin://targets/{target.target_id}",
        document_type="builtin_target",
        text_content="\n".join(lines),
        metadata={"target_id": target.target_id, "source_kind": "builtin"},
        rebuild=rebuild,
    )


def index_uploaded_file(
    db: Session,
    settings: Settings,
    project: Project,
    uploaded_file: UploadedFile,
    *,
    rebuild: bool,
) -> IndexedDocumentSummary | None:
    path = path_from_storage_uri(settings, uploaded_file.storage_path)
    suffix = path.suffix.lower()
    if suffix not in RAG_TEXT_SUFFIXES:
        return None

    text_content, metadata, warnings = extract_text_from_path(path, uploaded_file)
    if not text_content.strip():
        return None
    summary = index_text_document(
        db,
        settings,
        project_id=project.project_id,
        title=Path(uploaded_file.filename).stem or uploaded_file.filename,
        source=uploaded_file.file_id,
        document_type=document_type_from_suffix(suffix),
        text_content=text_content,
        metadata={
            **metadata,
            "source_kind": "upload",
            "file_id": uploaded_file.file_id,
            "filename": uploaded_file.filename,
            "storage_path": uploaded_file.storage_path,
        },
        rebuild=rebuild,
    )
    summary.warnings.extend(warnings)
    uploaded_file.metadata_json = {
        **(uploaded_file.metadata_json or {}),
        "rag_document_id": summary.document_id,
        "rag_chunk_count": summary.chunk_count,
        "rag_warnings": summary.warnings,
    }
    return summary


def index_text_document(
    db: Session,
    settings: Settings,
    *,
    project_id: str | None,
    title: str,
    source: str,
    document_type: str,
    text_content: str,
    metadata: dict[str, Any] | None = None,
    rebuild: bool = True,
) -> IndexedDocumentSummary:
    if rebuild:
        delete_existing_document_by_source(db, project_id, source)

    chunks = chunk_text(
        text_content,
        chunk_size=settings.rag_chunk_size,
        overlap=settings.rag_chunk_overlap,
    )
    embedding_client = build_embedding_client(settings)
    embeddings = embedding_client.embed_texts([chunk.content for chunk in chunks], input_type="document")
    document = RagDocument(
        document_id=new_id("DOC"),
        project_id=project_id,
        title=title[:300],
        source=source,
        document_type=document_type,
        metadata_json={
            **(metadata or {}),
            "adapter_mode": RAG_ADAPTER_MODE,
            "chunk_size": settings.rag_chunk_size,
            "chunk_overlap": settings.rag_chunk_overlap,
        },
    )
    db.add(document)
    db.flush()

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
            metadata_json={**(chunk.metadata or {}), "chunk_index": index},
        )
        db.add(rag_chunk)
        db.flush()
        store_pgvector_embedding(db, rag_chunk.chunk_id, embedding)

    return IndexedDocumentSummary(
        document_id=document.document_id,
        title=document.title,
        source=source,
        document_type=document_type,
        chunk_count=len(chunks),
        embedding_model=embedding_client.model_name,
    )


def select_uploaded_files(db: Session, project: Project, file_ids: list[str] | None) -> list[UploadedFile]:
    query = db.query(UploadedFile).filter_by(project_id=project.project_id)
    if file_ids:
        query = query.filter(UploadedFile.file_id.in_(file_ids))
    return query.order_by(UploadedFile.created_at.asc(), UploadedFile.id.asc()).all()


def load_project_chunks(db: Session, project: Project) -> tuple[list[RagChunk], dict[str, RagDocument]]:
    documents = (
        db.query(RagDocument)
        .filter(or_(RagDocument.project_id == project.project_id, RagDocument.project_id.is_(None)))
        .order_by(RagDocument.id.asc())
        .all()
    )
    document_ids = [document.document_id for document in documents]
    if not document_ids:
        return [], {}
    chunks = (
        db.query(RagChunk)
        .filter(RagChunk.document_id.in_(document_ids))
        .order_by(RagChunk.id.asc())
        .all()
    )
    return chunks, {document.document_id: document for document in documents}


def rerank_candidates(
    settings: Settings,
    query: str,
    candidates: list[RetrievalCandidate],
    top_k: int,
) -> list[RetrievalCandidate]:
    if not candidates:
        return []
    shortlist = candidates[: max(top_k, 1) * 4]
    reranker = build_reranker(settings)
    reranked = reranker.rerank(query, [candidate.chunk.content for candidate in shortlist], top_n=top_k)
    if not reranked:
        return shortlist[:top_k]
    output: list[RetrievalCandidate] = []
    for index, score in reranked:
        if index >= len(shortlist):
            continue
        candidate = shortlist[index]
        candidate.rerank_score = round(score, 6)
        output.append(candidate)
    return output[:top_k]


def candidate_to_payload(
    db: Session,
    candidate: RetrievalCandidate,
    *,
    query: str,
    query_type: str,
    molecule_id: str | None,
    create_evidence: bool,
) -> dict[str, Any]:
    evidence_id = None
    evidence_summary = summarize_evidence(candidate.chunk.content, query)
    if create_evidence:
        link = EvidenceLink(
            evidence_id=new_id("EVD"),
            molecule_id=molecule_id,
            chunk_id=candidate.chunk.chunk_id,
            claim_type=query_type,
            confidence=round(candidate.rerank_score or candidate.combined_score, 3),
            rationale=evidence_summary,
        )
        db.add(link)
        db.flush()
        evidence_id = link.evidence_id

    return {
        "chunk_id": candidate.chunk.chunk_id,
        "document_id": candidate.document.document_id,
        "source_type": candidate.document.document_type,
        "title": candidate.document.title,
        "source": candidate.document.source,
        "page": candidate.chunk.page_number,
        "section": candidate.chunk.section,
        "vector_score": candidate.vector_score,
        "keyword_score": candidate.keyword_score,
        "combined_score": candidate.combined_score,
        "rerank_score": candidate.rerank_score,
        "evidence_id": evidence_id,
        "evidence_summary": evidence_summary,
        "content": candidate.chunk.content,
    }


def delete_existing_document_by_source(db: Session, project_id: str | None, source: str) -> None:
    documents = db.query(RagDocument).filter_by(project_id=project_id, source=source).all()
    if not documents:
        return
    document_ids = [document.document_id for document in documents]
    chunk_ids = [
        row[0]
        for row in db.query(RagChunk.chunk_id).filter(RagChunk.document_id.in_(document_ids)).all()
    ]
    if chunk_ids:
        db.query(EvidenceLink).filter(EvidenceLink.chunk_id.in_(chunk_ids)).delete(synchronize_session=False)
    db.query(RagChunk).filter(RagChunk.document_id.in_(document_ids)).delete(synchronize_session=False)
    for document in documents:
        db.delete(document)


def store_pgvector_embedding(db: Session, chunk_id: str, embedding: list[float]) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql" or len(embedding) != 2048:
        return
    vector_literal = "[" + ",".join(str(value) for value in embedding) + "]"
    db.execute(
        text("UPDATE rag_chunks SET embedding_vector = CAST(:embedding AS vector) WHERE chunk_id = :chunk_id"),
        {"embedding": vector_literal, "chunk_id": chunk_id},
    )


def extract_text_from_path(path: Path, uploaded_file: UploadedFile) -> tuple[str, dict[str, Any], list[str]]:
    suffix = path.suffix.lower()
    warnings: list[str] = []
    if suffix in {".txt", ".md", ".markdown"}:
        return path.read_text(encoding="utf-8", errors="ignore"), {"parser": "plain_text"}, warnings
    if suffix in {".html", ".htm"}:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        text_content, title = html_to_text(raw)
        return text_content, {"parser": "html", "title": title}, warnings
    if suffix == ".docx":
        return docx_to_text(path), {"parser": "docx"}, warnings
    if suffix == ".pdf":
        text_content, parser_warning = pdf_to_text(path)
        if parser_warning:
            warnings.append(parser_warning)
        return text_content, {"parser": "pdf"}, warnings
    return "", {"parser": "unsupported", "file_id": uploaded_file.file_id}, ["unsupported_rag_file_type"]


def pdf_to_text(path: Path) -> tuple[str, str | None]:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(str(path))
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            pages.append(f"Page {index}\n{page.extract_text() or ''}")
        return "\n\n".join(pages), None
    except Exception:
        raw = path.read_bytes().decode("utf-8", errors="ignore")
        text_content = re.sub(r"\s+", " ", raw)
        return text_content, "pdf_text_extraction_fallback_used"


def docx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml_payload = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_payload)
    texts = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            texts.append(node.text)
    return "\n".join(texts)


def fetch_url_text(url: str, *, timeout_seconds: float) -> tuple[str, str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs can be crawled")
    headers = {"User-Agent": "medagent-rag-crawler/0.1"}
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        return html_to_text(response.text)
    return response.text, url


def html_to_text(payload: str) -> tuple[str, str | None]:
    parser = HTMLTextExtractor()
    parser.feed(payload)
    return parser.text(), parser.title


class HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._ignored_depth = 0
        self._in_title = False
        self.title: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False
            title = " ".join(self._title_parts).strip()
            self.title = html.unescape(title) if title else None
        if tag in {"p", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        cleaned = data.strip()
        if not cleaned:
            return
        if self._in_title:
            self._title_parts.append(cleaned)
        self._parts.append(html.unescape(cleaned))
        self._parts.append(" ")

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._parts)).strip()


def document_type_from_suffix(suffix: str) -> str:
    return {
        ".pdf": "paper_or_patent_pdf",
        ".md": "markdown",
        ".markdown": "markdown",
        ".txt": "text",
        ".html": "web",
        ".htm": "web",
        ".docx": "docx",
    }.get(suffix, "document")


def path_from_storage_uri(settings: Settings, storage_path: str) -> Path:
    if storage_path.startswith("local://"):
        return Path(storage_path.removeprefix("local://"))
    return Path(settings.storage_local_root) / storage_path


def summarize_evidence(content: str, query: str) -> str:
    query_terms = set(re.findall(r"[A-Za-z0-9_+\-\.]+|[\u4e00-\u9fff]", query.lower()))
    sentences = re.split(r"(?<=[。！？.!?])\s+", content)
    best_sentence = ""
    best_overlap = -1
    for sentence in sentences:
        terms = set(re.findall(r"[A-Za-z0-9_+\-\.]+|[\u4e00-\u9fff]", sentence.lower()))
        overlap = len(query_terms.intersection(terms))
        if overlap > best_overlap:
            best_sentence = sentence
            best_overlap = overlap
    summary = best_sentence.strip() or content.strip()
    return summary[:260]


def retrieval_confidence(retrieved_chunks: list[dict[str, Any]]) -> float:
    if not retrieved_chunks:
        return 0.0
    best_score = max(float(item.get("rerank_score") or item.get("combined_score") or 0.0) for item in retrieved_chunks)
    evidence_bonus = min(len(retrieved_chunks) / 10.0, 1.0) * 0.20
    return round(min(best_score + evidence_bonus, 1.0), 3)


def rag_build_summary(
    project_id: str,
    summaries: list[IndexedDocumentSummary],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "adapter_mode": RAG_ADAPTER_MODE,
        "document_count": len(summaries),
        "chunk_count": sum(summary.chunk_count for summary in summaries),
        "documents": [summary.as_dict() for summary in summaries],
        "warnings": warnings + [warning for summary in summaries for warning in summary.warnings],
    }


def create_agent_run(
    db: Session,
    project: Project,
    agent_name: str,
    *,
    model_name: str,
    input_json: dict[str, Any],
) -> AgentRun:
    run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        agent_name=agent_name,
        model_name=model_name,
        status="running",
        input_json={**input_json, "adapter_mode": RAG_ADAPTER_MODE},
        output_json={},
    )
    db.add(run)
    db.flush()
    return run


def finish_agent_run(run: AgentRun, output_json: dict[str, Any]) -> None:
    run.status = "completed"
    run.output_json = output_json
