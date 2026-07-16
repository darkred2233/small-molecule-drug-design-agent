from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.rag.rerank import LocalScoreReranker
from medagent.services.rag import retrieval_support_score


def make_client(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            storage_local_root=str(tmp_path / "uploads"),
            rag_chunk_size=240,
            rag_chunk_overlap=30,
            rag_use_remote_embeddings=False,
            rag_use_remote_rerank=False,
        )
    )
    return TestClient(app)


def create_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={
            "name": "EGFR RAG program",
            "target_id": "TGT-EGFR",
            "objective": "retrieve target and scaffold evidence",
        },
    )
    assert response.status_code == 201
    return response.json()["project_id"]


def test_ingest_text_file_builds_rag_index_and_query_creates_evidence(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project(client)
        payload = (
            "EGFR kinase inhibitors often rely on hinge binding near Met793. "
            "Quinazoline-like scaffolds can preserve potency, while high LogP and cationic side chains "
            "may raise hERG liability concerns."
        )
        upload_response = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("egfr_notes.txt", payload.encode("utf-8"), "text/plain")},
        )
        assert upload_response.status_code == 202

        ingest_response = client.post(f"/projects/{project_id}/ingest")

        assert ingest_response.status_code == 202
        ingest_body = ingest_response.json()
        assert ingest_body["parsed_files"] == 1
        assert ingest_body["rag"]["chunk_count"] >= 2

        documents_response = client.get(f"/projects/{project_id}/rag/documents")
        documents = documents_response.json()
        assert documents_response.status_code == 200
        assert {document["document_type"] for document in documents} >= {"builtin_target", "text"}

        query_response = client.post(
            f"/projects/{project_id}/rag/query",
            json={"query": "EGFR Met793 quinazoline hERG risk", "query_type": "risk_check", "top_k": 3},
        )

        assert query_response.status_code == 200
        query_body = query_response.json()
        assert query_body["retrieved_chunks"]
        assert query_body["evidence_ids"]
        assert query_body["confidence"] is None
        assert query_body["confidence_semantics"] == "not_calibrated"
        assert query_body["retrieval_support_score_semantics"] == "heuristic_not_probability"
        assert 0.0 <= query_body["retrieval_support_score"] <= 1.0
        assert query_body["embedding_model"] == "local-hash-embedding"
        assert query_body["rerank_model"] is None
        assert query_body["retrieved_chunks"][0]["retrieval_rank"] == 1
        assert all(item["rerank_score"] is None for item in query_body["retrieved_chunks"])
        assert all(
            item["evidence_confidence"] is None
            and item["evidence_confidence_semantics"] == "not_calibrated"
            and item["score_semantics"] == "heuristic_retrieval_score_not_probability"
            for item in query_body["retrieved_chunks"]
        )
        assert any("hERG" in chunk["content"] for chunk in query_body["retrieved_chunks"])

        links_response = client.get(f"/projects/{project_id}/evidence-links")
        assert links_response.status_code == 200
        assert {link["evidence_id"] for link in links_response.json()} >= set(query_body["evidence_ids"])
        assert all(link["confidence"] is None for link in links_response.json())


def test_rag_build_indexes_builtin_target_without_uploads(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project(client)

        response = client.post(
            f"/projects/{project_id}/rag/build",
            json={"include_builtin_target": True, "include_uploads": False},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["document_count"] == 1
        assert body["chunk_count"] >= 1
        assert body["documents"][0]["document_type"] == "builtin_target"


def test_rag_crawl_indexes_url_text(tmp_path, monkeypatch):
    from medagent.services import rag as rag_service

    def fake_fetch_url_text(url: str, *, timeout_seconds: float):
        return (
            "BTK covalent inhibitors use a cysteine-targeting acrylamide warhead and require selectivity checks.",
            "BTK inhibitor overview",
        )

    monkeypatch.setattr(rag_service, "fetch_url_text", fake_fetch_url_text)

    with make_client(tmp_path) as client:
        project_id = create_project(client)

        crawl_response = client.post(
            f"/projects/{project_id}/rag/crawl",
            json={"urls": ["https://example.test/btk-review"], "document_type": "database_page"},
        )

        assert crawl_response.status_code == 202
        assert crawl_response.json()["chunk_count"] >= 1

        query_response = client.post(
            f"/projects/{project_id}/rag/query",
            json={"query": "BTK acrylamide warhead selectivity", "top_k": 2},
        )

        assert query_response.status_code == 200
        assert any("acrylamide" in item["content"] for item in query_response.json()["retrieved_chunks"])


def test_local_reranker_does_not_fabricate_relevance_scores():
    reranker = LocalScoreReranker()

    assert reranker.rerank("query", ["first", "second"], top_n=2) == []


def test_retrieval_support_score_has_no_result_count_bonus():
    chunks = [
        {"combined_score": 0.42, "rerank_score": None},
        {"combined_score": 0.31, "rerank_score": None},
        {"combined_score": 0.18, "rerank_score": None},
    ]

    assert retrieval_support_score(chunks) == 0.42
