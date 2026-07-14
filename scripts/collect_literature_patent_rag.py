from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from medagent.core.config import Settings
from medagent.data.collect_target_pack import PackDocument
from medagent.db.models import Base, Project, RagChunk, RagDocument, Target
from medagent.db.session import build_engine, build_session_factory
from medagent.services.bootstrap import seed_builtin_targets
from medagent.services.database import ensure_relational_schema
from medagent.services.rag import build_project_rag_index, delete_existing_document_by_source, query_project_rag
from medagent.services.rag_importers import import_pack_documents


DEFAULT_TARGET_IDS = [
    "TGT-HER2",
    "TGT-MET",
    "TGT-DPP4",
    "TGT-HMGCR",
    "TGT-HIV1-PROTEASE",
]


@dataclass
class LiteratureRecord:
    pmid: str
    title: str
    abstract: str
    journal: str | None
    pub_year: str | None
    doi: str | None
    authors: list[str]


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public paper/patent summaries and store them in project RAG.")
    parser.add_argument("--target-id", action="append", default=[], help="Target id to collect. Repeatable.")
    parser.add_argument("--all-targets", action="store_true", help="Collect every seeded target instead of the default validation set.")
    parser.add_argument("--database-url", default=None, help="Database URL. Defaults to project Settings.")
    parser.add_argument("--papers-per-target", type=int, default=3)
    parser.add_argument("--patents-per-target", type=int, default=2)
    parser.add_argument("--output", default="database/data_expansion_rag_verification.json")
    parser.add_argument("--skip-network", action="store_true", help="Only rebuild built-in RAG; skip PubMed/PubChem patent fetches.")
    parser.add_argument("--request-delay-seconds", type=float, default=0.0, help="Extra delay between targets for batch network runs.")
    args = parser.parse_args()
    if args.all_targets and args.target_id:
        parser.error("--all-targets cannot be combined with --target-id")

    settings = Settings(database_url=args.database_url) if args.database_url else Settings()
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    ensure_relational_schema(engine)
    session_factory = build_session_factory(settings)

    summaries: list[dict[str, Any]] = []
    with session_factory() as db:
        seed_builtin_targets(db)
        if args.all_targets:
            target_ids = [target_id for (target_id,) in db.query(Target.target_id).order_by(Target.target_id).all()]
        else:
            target_ids = args.target_id or DEFAULT_TARGET_IDS

        for index, target_id in enumerate(target_ids, start=1):
            print(f"[{index}/{len(target_ids)}] Building data expansion RAG for {target_id}")
            target = db.query(Target).filter_by(target_id=target_id).one_or_none()
            if target is None:
                summaries.append({"target_id": target_id, "warnings": ["target_not_found"]})
                continue
            project = ensure_project(db, target)
            build_summary = build_project_rag_index(
                db,
                settings,
                project,
                include_builtin_target=True,
                include_uploads=False,
                rebuild=True,
            )

            pack_documents: list[PackDocument] = []
            warnings: list[str] = []
            if not args.skip_network:
                try:
                    papers = fetch_pubmed_records(target, limit=args.papers_per_target)
                except Exception as exc:
                    papers = []
                    warnings.append(f"pubmed_fetch_failed:{type(exc).__name__}:{exc}")
                pack_documents.extend(paper_to_pack_document(target, paper) for paper in papers)
                try:
                    patents = fetch_patent_records(target, limit=args.patents_per_target)
                except Exception as exc:
                    patents = []
                    warnings.append(f"patent_fetch_failed:{type(exc).__name__}:{exc}")
                pack_documents.extend(patent_to_pack_document(target, patent) for patent in patents)
                if len(papers) < args.papers_per_target:
                    warnings.append(f"paper_count_below_requested:{len(papers)}/{args.papers_per_target}")
                if len(patents) < args.patents_per_target:
                    warnings.append(f"patent_count_below_requested:{len(patents)}/{args.patents_per_target}")

            for pack_doc in pack_documents:
                delete_existing_document_by_source(db, project.project_id, pack_doc.source)
            import_summary = import_pack_documents(db, settings, project, pack_documents)
            db.commit()

            query_summary = sample_queries(db, settings, project, target)
            summaries.append(
                {
                    "target_id": target.target_id,
                    "target_name": target.name,
                    "project_id": project.project_id,
                    "builtin_rag": build_summary,
                    "external_pack_import": import_summary,
                    "query_verification": query_summary,
                    "rag_totals": rag_totals(db, project.project_id),
                    "warnings": warnings + import_summary.get("warnings", []),
                }
            )
            if args.request_delay_seconds > 0 and index < len(target_ids):
                time.sleep(args.request_delay_seconds)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote RAG verification summary to {output_path}")
    for summary in summaries:
        print(
            f"{summary.get('target_id')}: docs={summary.get('rag_totals', {}).get('document_count')} "
            f"chunks={summary.get('rag_totals', {}).get('chunk_count')}"
        )
    return 0


def ensure_project(db, target: Target) -> Project:
    project_id = f"PROJ-DATAEXP-{target.target_id.removeprefix('TGT-').replace('/', '-')}"
    project = db.query(Project).filter_by(project_id=project_id).one_or_none()
    if project is None:
        project = Project(
            project_id=project_id,
            name=f"{target.name} data expansion RAG validation",
            target_id=target.target_id,
            objective="Validate expanded literature and patent RAG coverage.",
        )
        db.add(project)
        db.flush()
    else:
        project.target_id = target.target_id
        project.objective = "Validate expanded literature and patent RAG coverage."
    return project


def fetch_pubmed_records(target: Target, *, limit: int) -> list[LiteratureRecord]:
    search_ids = search_pubmed(target, retmax=max(limit * 6, 12))
    if not search_ids:
        return []
    records = fetch_pubmed_details(search_ids)
    usable = [record for record in records if record.abstract.strip()]
    return usable[:limit]


def search_pubmed(target: Target, *, retmax: int) -> list[str]:
    terms = [target.name, *(target.aliases or [])]
    title_abs_terms = " OR ".join(f'"{term}"[Title/Abstract]' for term in terms if term)
    if not title_abs_terms:
        title_abs_terms = f'"{target.target_id}"[Title/Abstract]'
    query = (
        f"({title_abs_terms}) AND "
        "(inhibitor[Title/Abstract] OR ligand[Title/Abstract] OR SAR[Title/Abstract] "
        'OR "drug design"[Title/Abstract] OR resistance[Title/Abstract] OR selectivity[Title/Abstract]) '
        'AND ("2014/01/01"[Date - Publication] : "3000"[Date - Publication])'
    )
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        + urllib.parse.urlencode({"db": "pubmed", "term": query, "retmax": retmax, "retmode": "json", "sort": "relevance"})
    )
    payload = fetch_json(url)
    time.sleep(0.34)
    return (payload.get("esearchresult") or {}).get("idlist") or []


def fetch_pubmed_details(pmids: list[str]) -> list[LiteratureRecord]:
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
        + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
    )
    with urllib.request.urlopen(url, timeout=45) as response:
        root = ElementTree.fromstring(response.read())
    records: list[LiteratureRecord] = []
    for article in root.findall("PubmedArticle"):
        citation = article.find("MedlineCitation")
        if citation is None:
            continue
        pmid = text_at(citation, "PMID")
        article_node = citation.find("Article")
        if article_node is None or not pmid:
            continue
        title = flatten_text(article_node.find("ArticleTitle"))
        abstract = " ".join(flatten_text(node) for node in article_node.findall("Abstract/AbstractText")).strip()
        journal = text_at(article_node, "Journal/Title")
        pub_year = (
            text_at(article_node, "Journal/JournalIssue/PubDate/Year")
            or text_at(article_node, "ArticleDate/Year")
            or text_at(citation, "DateCompleted/Year")
        )
        doi = None
        for elocation in article_node.findall("ELocationID"):
            if elocation.attrib.get("EIdType") == "doi" and elocation.text:
                doi = elocation.text.strip()
                break
        authors = []
        for author in article_node.findall("AuthorList/Author"):
            last = text_at(author, "LastName")
            initials = text_at(author, "Initials")
            if last:
                authors.append(f"{last} {initials}".strip())
        records.append(LiteratureRecord(pmid, title, abstract, journal, pub_year, doi, authors))
    time.sleep(0.34)
    return records


def fetch_patent_records(target: Target, *, limit: int) -> list[dict[str, Any]]:
    patents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for drug in target.drugs:
        cid = drug.pubchem_cid
        if cid is None:
            continue
        for patent_id in fetch_pubchem_patent_ids(int(cid)):
            normalized = normalize_patent_id(patent_id)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            patents.append(
                {
                    "patent_id": normalized,
                    "raw_patent_id": patent_id,
                    "drug_name": drug.drug_name,
                    "pubchem_cid": cid,
                    "source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}#section=Patents",
                    "uspto_pdf_url": uspto_pdf_url(normalized),
                }
            )
            if len(patents) >= limit:
                return patents
    return patents


def fetch_pubchem_patent_ids(cid: int) -> list[str]:
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON/?heading=Patents"
    try:
        payload = fetch_json(url)
    except Exception:
        return []
    patents: list[str] = []
    collect_patent_strings(payload, patents)
    time.sleep(0.2)
    return patents


def collect_patent_strings(value: Any, patents: list[str]) -> None:
    if isinstance(value, dict):
        string_value = value.get("String")
        if isinstance(string_value, str) and re.match(r"^[A-Z]{2}\d", string_value):
            patents.append(string_value)
        for child in value.values():
            collect_patent_strings(child, patents)
    elif isinstance(value, list):
        for child in value:
            collect_patent_strings(child, patents)


def paper_to_pack_document(target: Target, paper: LiteratureRecord) -> PackDocument:
    source = f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/"
    content = "\n".join(
        [
            f"Target: {target.name} ({target.target_id})",
            "Document type: PubMed literature abstract",
            f"Title: {paper.title}",
            f"PMID: {paper.pmid}",
            f"DOI: {paper.doi or 'unknown'}",
            f"Journal: {paper.journal or 'unknown'}",
            f"Publication year: {paper.pub_year or 'unknown'}",
            f"Authors: {', '.join(paper.authors[:8]) or 'unknown'}",
            "",
            f"Abstract: {paper.abstract}",
        ]
    )
    return PackDocument(
        target_id=target.target_id,
        document_type="literature_summary",
        title=paper.title or f"{target.name} PubMed {paper.pmid}",
        source=source,
        content=content,
        metadata={
            "source_name": "pubmed",
            "source_url": source,
            "pubmed_id": paper.pmid,
            "doi": paper.doi,
            "journal": paper.journal,
            "pub_year": paper.pub_year,
            "target_id": target.target_id,
        },
    )


def patent_to_pack_document(target: Target, patent: dict[str, Any]) -> PackDocument:
    patent_id = patent["patent_id"]
    source = patent["uspto_pdf_url"] or patent["source_url"]
    title = f"{target.name} patent link: {patent_id} ({patent['drug_name']})"
    content = "\n".join(
        [
            f"Target: {target.name} ({target.target_id})",
            "Document type: patent identifier summary",
            f"Patent identifier: {patent_id}",
            f"Representative drug context: {patent['drug_name']}",
            f"PubChem CID: {patent['pubchem_cid']}",
            f"PubChem patent section: {patent['source_url']}",
            f"USPTO public PDF: {patent['uspto_pdf_url'] or 'not available'}",
            "",
            "Summary: PubChem lists this patent identifier in the compound patent section for the representative drug. "
            "Use the linked USPTO publication PDF as the primary patent document for claim-level review before using the "
            "record as design evidence.",
        ]
    )
    return PackDocument(
        target_id=target.target_id,
        document_type="patent_summary",
        title=title,
        source=source,
        content=content,
        metadata={
            "source_name": "pubchem_patents_uspto",
            "source_url": patent["source_url"],
            "uspto_pdf_url": patent["uspto_pdf_url"],
            "patent_id": patent_id,
            "drug_name": patent["drug_name"],
            "pubchem_cid": patent["pubchem_cid"],
            "target_id": target.target_id,
        },
    )


def sample_queries(db, settings: Settings, project: Project, target: Target) -> list[dict[str, Any]]:
    queries = [
        f"{target.name} inhibitor resistance SAR patent",
        f"{target.name} selectivity ADMET safety",
    ]
    out: list[dict[str, Any]] = []
    for query in queries:
        result = query_project_rag(
            db,
            settings,
            project,
            query=query,
            query_type="data_expansion_validation",
            top_k=5,
            create_evidence=False,
        )
        out.append(
            {
                "query": query,
                "retrieved_chunks": len(result.get("retrieved_chunks", [])),
                "confidence": result.get("confidence"),
                "top_titles": [chunk.get("title") for chunk in result.get("retrieved_chunks", [])[:3]],
            }
        )
    return out


def rag_totals(db, project_id: str) -> dict[str, Any]:
    documents = db.query(RagDocument).filter_by(project_id=project_id).all()
    document_ids = [document.document_id for document in documents]
    chunk_count = 0
    if document_ids:
        chunk_count = db.query(RagChunk).filter(RagChunk.document_id.in_(document_ids)).count()
    type_counts: dict[str, int] = {}
    for document in documents:
        type_counts[document.document_type] = type_counts.get(document.document_type, 0) + 1
    return {"document_count": len(documents), "chunk_count": chunk_count, "document_type_counts": type_counts}


def normalize_patent_id(raw: str) -> str | None:
    text = raw.strip().upper().replace("-", "")
    match = re.match(r"^([A-Z]{2})(\d+)", text)
    if not match:
        return None
    return f"{match.group(1)}{match.group(2)}"


def uspto_pdf_url(patent_id: str) -> str | None:
    match = re.match(r"^US(\d+)$", patent_id)
    if not match:
        return None
    return f"https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/{match.group(1)}"


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def flatten_text(node: ElementTree.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def text_at(node: ElementTree.Element, path: str) -> str | None:
    child = node.find(path)
    if child is None or child.text is None:
        return None
    return child.text.strip()


if __name__ == "__main__":
    raise SystemExit(main())
