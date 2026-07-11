from __future__ import annotations

from typing import Any

import httpx

from medagent.data.collectors.base import BaseCollector, CollectionResult


class SafetyCollector(BaseCollector):
    source_name = "openfda_placeholder"
    base_url = "https://api.fda.gov/drug/label.json"

    def collect_target_pack(self, target_payload: dict) -> list[CollectionResult]:
        results: list[CollectionResult] = []
        seen: set[str] = set()
        for drug_payload in target_payload.get("drugs", []):
            name = self._drug_name(drug_payload)
            if not name:
                continue
            text, source_url, external_id = self._fetch_drug_label(name)
            if not text:
                continue
            key = (name, external_id)
            if key in seen:
                continue
            seen.add(key)
            results.append(CollectionResult(
                source=self.source_name,
                target_id=target_payload.get("target_id"),
                external_id=external_id or name,
                document_type="safety_evidence",
                title=f"{target_payload.get('name')} safety evidence: {name}",
                content=text,
                metadata={
                    "source_url": source_url,
                    "target_id": target_payload.get("target_id"),
                    "drug_name": name,
                },
            ))
        return results or [CollectionResult(
            source=self.source_name,
            target_id=target_payload.get("target_id"),
            document_type="safety_evidence",
            title=f"{target_payload.get('name')} safety evidence",
            warnings=["openfda_label_fetch_skipped_or_empty"],
        )]

    def _drug_name(self, drug_payload: Any) -> str:
        if isinstance(drug_payload, dict):
            return drug_payload.get("drug_name") or drug_payload.get("name") or ""
        if isinstance(drug_payload, (list, tuple)) and drug_payload:
            return str(drug_payload[0])
        return ""

    def _fetch_drug_label(self, drug_name: str) -> tuple[str, str, str | None]:
        try:
            url = f"{self.base_url}?search=openfda.generic_name:\"{drug_name.upper()}\"&limit=1"
            with httpx.Client(timeout=20.0) as client:
                response = client.get(url)
            if response.status_code != 200:
                return "", url, None
            data = response.json()
            results = data.get("results") or []
            if not results:
                return "", url, None
            item = results[0]
            set_id = item.get("set_id")
            warnings = item.get("warnings") or item.get("boxed_warning") or []
            adverse = item.get("adverse_reactions") or []
            interactions = item.get("drug_interactions") or []
            parts = [
                f"Drug label evidence: {drug_name}",
                f"Set ID: {set_id}",
            ]
            if warnings:
                parts.append("Warnings: " + self._join_texts(warnings[:2]))
            if adverse:
                parts.append("Adverse reactions: " + self._join_texts(adverse[:2]))
            if interactions:
                parts.append("Drug interactions: " + self._join_texts(interactions[:2]))
            return "\n".join(parts), url, set_id
        except Exception:
            return "", self.base_url, None

    def _join_texts(self, values: Any) -> str:
        if isinstance(values, list):
            texts = [v for v in values if isinstance(v, str) and v.strip()]
            return " | ".join(texts[:3])
        return str(values or "")
