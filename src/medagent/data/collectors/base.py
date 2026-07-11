from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CollectionResult:
    source: str
    target_id: str | None = None
    external_id: str | None = None
    document_type: str = "external_collection"
    title: str | None = None
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        if self.content:
            parts.append(self.content)
        return "\n\n".join(parts)


class BaseCollector:
    source_name: str = "base"

    def collect_target_pack(self, target_payload: dict) -> list[CollectionResult]:
        raise NotImplementedError

    def collect_activity_pack(self, target_payload: dict, limit: int = 500) -> list[CollectionResult]:
        return []

    def collect_safety_pack(self, target_payload: dict, limit: int = 20) -> list[CollectionResult]:
        return []

    def collect_patent_pack(self, target_payload: dict, limit: int = 10) -> list[CollectionResult]:
        return []

    def collect_clinical_pack(self, target_payload: dict, limit: int = 10) -> list[CollectionResult]:
        return []
