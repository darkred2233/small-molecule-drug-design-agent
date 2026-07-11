from dataclasses import dataclass
from typing import Protocol

import httpx

from medagent.core.config import Settings


class Reranker(Protocol):
    model_name: str

    def rerank(self, query: str, documents: list[str], *, top_n: int) -> list[tuple[int, float]]:
        ...


@dataclass
class LocalScoreReranker:
    model_name: str = "local-score-rerank"

    def rerank(self, query: str, documents: list[str], *, top_n: int) -> list[tuple[int, float]]:
        return [(index, 1.0 - index * 0.001) for index, _ in enumerate(documents[:top_n])]


@dataclass
class DashScopeReranker:
    api_key: str
    model_name: str
    endpoint_url: str
    timeout_seconds: float = 30.0

    def rerank(self, query: str, documents: list[str], *, top_n: int) -> list[tuple[int, float]]:
        if not documents:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "query": query,
            "documents": documents,
            "top_n": top_n,
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.endpoint_url, headers=headers, json=payload)
            response.raise_for_status()
        return parse_rerank_response(response.json())


def build_reranker(settings: Settings) -> Reranker:
    if settings.dashscope_api_key and settings.dashscope_rerank_url and settings.rag_use_remote_rerank:
        return DashScopeReranker(
            api_key=settings.dashscope_api_key,
            model_name=settings.rerank_model,
            endpoint_url=settings.dashscope_rerank_url,
        )
    return LocalScoreReranker()


def parse_rerank_response(body: dict) -> list[tuple[int, float]]:
    raw_results = body.get("results") or (body.get("output") or {}).get("results") or []
    parsed: list[tuple[int, float]] = []
    for item in raw_results:
        index = item.get("index")
        if index is None:
            index = item.get("document_index")
        score = item.get("relevance_score")
        if score is None:
            score = item.get("score")
        if index is None:
            continue
        parsed.append((int(index), float(score if score is not None else 0.0)))
    return parsed
