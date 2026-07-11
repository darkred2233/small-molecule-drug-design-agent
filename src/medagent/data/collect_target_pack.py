from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from medagent.data.collectors.chembl import ChEMBLCollector
from medagent.data.collectors.clinical import ClinicalCollector
from medagent.data.collectors.pdb import PDBCollector
from medagent.data.collectors.pubchem import PubChemCollector
from medagent.data.collectors.pubmed import PubMedCollector
from medagent.data.collectors.safety import SafetyCollector
from medagent.data.collectors.uniprot import UniProtCollector


@dataclass
class PackDocument:
    target_id: str
    document_type: str
    title: str
    source: str
    content: str
    metadata: dict[str, Any]


class TargetPackBuilder:
    def __init__(self, target_payload: dict) -> None:
        self.target_payload = target_payload
        self.collectors = [
            UniProtCollector(),
            ChEMBLCollector(),
            PubChemCollector(),
            PDBCollector(),
            PubMedCollector(),
            SafetyCollector(),
            ClinicalCollector(),
        ]

    def build(self, skip_network: bool = False) -> list[PackDocument]:
        docs: list[PackDocument] = []
        target_id = self.target_payload.get("target_id")
        name = self.target_payload.get("name")
        drugs = self._normalize_drugs(self.target_payload.get("drugs", []))
        payload = {**self.target_payload, "drugs": drugs}

        for collector in self.collectors:
            if skip_network and collector.source_name not in {"uniprot"}:
                continue
            results = collector.collect_target_pack(payload)
            for result in results:
                docs.append(PackDocument(
                    target_id=result.target_id or target_id or "unknown",
                    document_type=result.document_type,
                    title=result.title or f"{name} {collector.source_name}",
                    source=result.source,
                    content=result.content or result.as_text(),
                    metadata={
                        **(result.metadata or {}),
                        "external_id": result.external_id,
                        "source_name": result.source,
                    },
                ))

        deduped = self._dedupe(docs)
        return self._attach_core(deduped, drugs)

    def _dedupe(self, docs: list[PackDocument]) -> list[PackDocument]:
        seen: set[str] = set()
        out: list[PackDocument] = []
        for doc in docs:
            key = (doc.document_type, doc.title, doc.source)
            if key in seen:
                continue
            seen.add(key)
            out.append(doc)
        return out

    def _attach_core(self, docs: list[PackDocument], drugs: list[tuple[str, str, str, str]]) -> list[PackDocument]:
        core = PackDocument(
            target_id=self.target_payload.get("target_id", "unknown"),
            document_type="target_profile",
            title=f"{self.target_payload.get('name')} core profile",
            source="builtin_core",
            content=self._format_core(drugs),
            metadata={
                "source_name": "builtin_core",
                "target_id": self.target_payload.get("target_id"),
            },
        )
        return [core] + docs

    def _format_core(self, drugs: list[tuple[str, str, str, str]]) -> str:
        lines = [
            f"Target: {self.target_payload.get('name')} ({self.target_payload.get('target_id')})",
            f"Aliases: {', '.join(self.target_payload.get('aliases', []))}",
            f"UniProt: {self.target_payload.get('uniprot_id') or 'unknown'}",
            f"Species: {self.target_payload.get('species') or 'unknown'}",
            f"Representative PDB structures: {', '.join(self.target_payload.get('pdb_ids', []))}",
            "",
            self.target_payload.get("summary") or "",
        ]
        lines.extend([
            "",
            "Representative drugs and mechanisms:",
        ])
        for drug_name, drug_status, mechanism, indication in drugs:
            lines.append(
                f"- {drug_name}: {mechanism or 'mechanism unknown'}; "
                f"status={drug_status or 'unknown'}; indication={indication or 'unknown'}"
            )
        return "\n".join(lines)

    def _normalize_drugs(self, drugs: Any) -> list[tuple[str, str, str, str]]:
        if not drugs:
            return []
        normalized: list[tuple[str, str, str, str]] = []
        for item in drugs:
            if isinstance(item, dict):
                normalized.append((
                    item.get("drug_name") or item.get("name") or "unknown",
                    item.get("drug_status") or item.get("status") or "unknown",
                    item.get("mechanism") or "unknown",
                    item.get("indication") or "unknown",
                ))
            elif isinstance(item, (list, tuple)) and len(item) >= 4:
                normalized.append((str(item[0]), str(item[1]), str(item[2]), str(item[3])))
        return normalized


def build_pack_documents(target_payload: dict) -> list[PackDocument]:
    return TargetPackBuilder(target_payload).build()
