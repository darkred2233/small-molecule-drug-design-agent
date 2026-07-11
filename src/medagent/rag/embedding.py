import hashlib
import math
import re
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from medagent.core.config import Settings


EmbeddingInputType = Literal["document", "query"]
TOKEN_RE = re.compile(r"[A-Za-z0-9_+\-\.]+|[\u4e00-\u9fff]")


class EmbeddingClient(Protocol):
    model_name: str
    dimension: int

    def embed_texts(self, texts: list[str], *, input_type: EmbeddingInputType) -> list[list[float]]:
        ...


@dataclass
class LocalHashEmbeddingClient:
    model_name: str = "local-hash-embedding"
    dimension: int = 2048

    def embed_texts(self, texts: list[str], *, input_type: EmbeddingInputType) -> list[list[float]]:
        return [hashing_embedding(text, self.dimension, input_type=input_type) for text in texts]


@dataclass
class DashScopeEmbeddingClient:
    api_key: str
    model_name: str
    dimension: int
    base_url: str
    timeout_seconds: float = 30.0

    def embed_texts(self, texts: list[str], *, input_type: EmbeddingInputType) -> list[list[float]]:
        if not texts:
            return []
        embeddings: list[list[float]] = []
        for batch in batched(texts, 10):
            embeddings.extend(self._embed_batch(batch, input_type=input_type))
        return embeddings

    def _embed_batch(self, texts: list[str], *, input_type: EmbeddingInputType) -> list[list[float]]:
        url = f"{self.base_url.rstrip('/')}/embeddings"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "input": texts,
            "dimensions": self.dimension,
            "encoding_format": "float",
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        body = response.json()
        data = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in data]


def build_embedding_client(settings: Settings) -> EmbeddingClient:
    if settings.dashscope_api_key and settings.rag_use_remote_embeddings:
        return DashScopeEmbeddingClient(
            api_key=settings.dashscope_api_key,
            model_name=settings.embedding_model,
            dimension=settings.rag_embedding_dimension,
            base_url=settings.dashscope_compatible_base_url,
        )
    return LocalHashEmbeddingClient(dimension=settings.rag_embedding_dimension)


def hashing_embedding(
    text: str,
    dimension: int,
    *,
    input_type: EmbeddingInputType,
) -> list[float]:
    vector = [0.0] * dimension
    tokens = tokenize(text)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    return normalize_vector(vector)


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 8) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))


def embedding_ref(model_name: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{model_name}:{digest}"


def batched(items: list[str], batch_size: int) -> list[list[str]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]
