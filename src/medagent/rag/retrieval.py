import math
from dataclasses import dataclass

from medagent.db.models import RagChunk, RagDocument
from medagent.rag.embedding import cosine_similarity, tokenize


@dataclass
class RetrievalCandidate:
    chunk: RagChunk
    document: RagDocument
    vector_score: float = 0.0
    keyword_score: float = 0.0
    combined_score: float = 0.0
    rerank_score: float | None = None


def retrieve_candidates(
    *,
    query: str,
    query_embedding: list[float],
    chunks: list[RagChunk],
    documents_by_id: dict[str, RagDocument],
    vector_top_k: int,
    keyword_top_k: int,
) -> list[RetrievalCandidate]:
    vector_candidates = vector_recall(query_embedding, chunks, documents_by_id, vector_top_k)
    keyword_candidates = keyword_recall(query, chunks, documents_by_id, keyword_top_k)
    merged: dict[str, RetrievalCandidate] = {}

    for candidate in vector_candidates + keyword_candidates:
        existing = merged.get(candidate.chunk.chunk_id)
        if existing is None:
            merged[candidate.chunk.chunk_id] = candidate
        else:
            existing.vector_score = max(existing.vector_score, candidate.vector_score)
            existing.keyword_score = max(existing.keyword_score, candidate.keyword_score)

    candidates = list(merged.values())
    max_keyword = max([candidate.keyword_score for candidate in candidates] or [0.0])
    for candidate in candidates:
        keyword_normalized = candidate.keyword_score / max_keyword if max_keyword > 0 else 0.0
        candidate.combined_score = round(candidate.vector_score * 0.62 + keyword_normalized * 0.38, 6)

    return sorted(candidates, key=lambda item: (-item.combined_score, item.chunk.chunk_id))


def vector_recall(
    query_embedding: list[float],
    chunks: list[RagChunk],
    documents_by_id: dict[str, RagDocument],
    top_k: int,
) -> list[RetrievalCandidate]:
    candidates = []
    for chunk in chunks:
        embedding = list(chunk.embedding_json or [])
        score = cosine_similarity(query_embedding, embedding)
        if score <= 0:
            continue
        document = documents_by_id.get(chunk.document_id)
        if document is None:
            continue
        candidates.append(RetrievalCandidate(chunk=chunk, document=document, vector_score=round(score, 6)))
    return sorted(candidates, key=lambda item: (-item.vector_score, item.chunk.chunk_id))[:top_k]


def keyword_recall(
    query: str,
    chunks: list[RagChunk],
    documents_by_id: dict[str, RagDocument],
    top_k: int,
) -> list[RetrievalCandidate]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    tokenized_chunks = [(chunk, tokenize(chunk.content)) for chunk in chunks]
    average_length = sum(len(tokens) for _, tokens in tokenized_chunks) / max(len(tokenized_chunks), 1)
    document_frequency: dict[str, int] = {}
    for _, tokens in tokenized_chunks:
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1

    candidates = []
    document_count = len(tokenized_chunks)
    for chunk, tokens in tokenized_chunks:
        score = bm25_score(
            query_tokens=query_tokens,
            document_tokens=tokens,
            document_frequency=document_frequency,
            document_count=document_count,
            average_length=average_length,
        )
        if score <= 0:
            continue
        document = documents_by_id.get(chunk.document_id)
        if document is None:
            continue
        candidates.append(RetrievalCandidate(chunk=chunk, document=document, keyword_score=round(score, 6)))
    return sorted(candidates, key=lambda item: (-item.keyword_score, item.chunk.chunk_id))[:top_k]


def bm25_score(
    *,
    query_tokens: list[str],
    document_tokens: list[str],
    document_frequency: dict[str, int],
    document_count: int,
    average_length: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not document_tokens:
        return 0.0
    frequencies: dict[str, int] = {}
    for token in document_tokens:
        frequencies[token] = frequencies.get(token, 0) + 1

    score = 0.0
    document_length = len(document_tokens)
    for token in query_tokens:
        frequency = frequencies.get(token, 0)
        if frequency == 0:
            continue
        df = document_frequency.get(token, 0)
        idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
        denominator = frequency + k1 * (1 - b + b * document_length / max(average_length, 1.0))
        score += idf * (frequency * (k1 + 1)) / denominator
    return score
