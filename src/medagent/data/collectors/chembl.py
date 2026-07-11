from __future__ import annotations

from typing import Any

import httpx

from medagent.data.collectors.base import BaseCollector, CollectionResult


class ChEMBLCollector(BaseCollector):
    source_name = "chembl"
    base_url = "https://www.ebi.ac.uk/chembl/api/data"

    def collect_target_pack(self, target_payload: dict) -> list[CollectionResult]:
        results: list[CollectionResult] = []
        chembl_id = target_payload.get("chembl_target_id")
        uniprot_id = target_payload.get("uniprot_id")
        target_id = target_payload.get("target_id")
        name = target_payload.get("name")

        if chembl_id:
            target_data = self._get_json(f"{self.base_url}/target/{chembl_id}.json")
            if target_data:
                results.append(CollectionResult(
                    source=self.source_name,
                    target_id=target_id,
                    external_id=chembl_id,
                    document_type="target_profile",
                    title=f"{name} ChEMBL target record",
                    content=self._format_target(target_data),
                    metadata={
                        "source_url": f"https://www.ebi.ac.uk/chembl/api/data/target/{chembl_id}.json",
                        "chembl_target_id": chembl_id,
                        "target_id": target_id,
                    },
                ))

        if uniprot_id:
            target_results = self._get_json(
                f"{self.base_url}/target/search.json",
                params={"q": uniprot_id, "limit": 1},
            )
            target_data = None
            if isinstance(target_results, dict):
                target_data = (target_results.get("targets") or [None])[0]
            elif isinstance(target_results, list):
                target_data = target_results[0] if target_results else None

            if target_data:
                fetched_chembl_id = target_data.get("target_chembl_id")
                if fetched_chembl_id and fetched_chembl_id != chembl_id:
                    detailed = self._get_json(f"{self.base_url}/target/{fetched_chembl_id}.json")
                    if detailed:
                        results.append(CollectionResult(
                            source=self.source_name,
                            target_id=target_id,
                            external_id=fetched_chembl_id,
                            document_type="target_profile",
                            title=f"{name} ChEMBL target record",
                            content=self._format_target(detailed),
                            metadata={
                                "source_url": f"https://www.ebi.ac.uk/chembl/api/data/target/{fetched_chembl_id}.json",
                                "chembl_target_id": fetched_chembl_id,
                                "target_id": target_id,
                            },
                        ))
        return results

    def collect_activity_pack(self, target_payload: dict, limit: int = 500) -> list[CollectionResult]:
        chembl_id = target_payload.get("chembl_target_id")
        uniprot_id = target_payload.get("uniprot_id")
        target_id = target_payload.get("target_id")
        name = target_payload.get("name")

        resolved_chembl_id = chembl_id
        if not resolved_chembl_id and uniprot_id:
            target_results = self._get_json(
                f"{self.base_url}/target/search.json",
                params={"q": uniprot_id, "limit": 1},
            )
            if isinstance(target_results, dict):
                resolved_chembl_id = ((target_results.get("targets") or [{}])[0]).get("target_chembl_id")

        if not resolved_chembl_id:
            return [CollectionResult(
                source=self.source_name,
                target_id=target_id,
                document_type="activity_summary",
                title=f"{name} ChEMBL activities",
                warnings=["chembl_target_id_not_resolved"],
            )]

        activities = self._get_json(
            f"{self.base_url}/activity.json",
            params={
                "target_chembl_id": resolved_chembl_id,
                "pchembl_value__gte": 5,
                "limit": min(limit, 1000),
                "format": "json",
            },
        )
        if not activities:
            return [CollectionResult(
                source=self.source_name,
                target_id=target_id,
                external_id=resolved_chembl_id,
                document_type="activity_summary",
                title=f"{name} ChEMBL activities",
                warnings=["chembl_activity_empty"],
            )]

        seen_docs: set[str] = set()
        results: list[CollectionResult] = []
        for item in activities:
            doc_id = item.get("document_chembl_id") or "summary"
            if doc_id not in seen_docs:
                seen_docs.add(doc_id)
                doc = self._get_json(f"{self.base_url}/document/{doc_id}.json") if doc_id != "summary" else None
                title = (doc or {}).get("title") or f"ChEMBL document {doc_id}"
                abstract = (doc or {}).get("abstract") or ""
                results.append(CollectionResult(
                    source=self.source_name,
                    target_id=target_id,
                    external_id=doc_id,
                    document_type="activity_summary",
                    title=f"{name} activity document: {title}",
                    content=self._format_activity(item, abstract, name),
                    metadata={
                        "source_url": f"https://www.ebi.ac.uk/chembl/api/data/activity.json?target_chembl_id={resolved_chembl_id}",
                        "chembl_target_id": resolved_chembl_id,
                        "document_chembl_id": doc_id,
                        "target_id": target_id,
                    },
                ))
            if len(results) >= 40:
                break

        if not results:
            results.append(CollectionResult(
                source=self.source_name,
                target_id=target_id,
                external_id=resolved_chembl_id,
                document_type="activity_summary",
                title=f"{name} ChEMBL activities",
                content=f"Found {len(activities)} activities for {resolved_chembl_id}, but no distinct documents were extracted.",
                metadata={
                    "source_url": f"https://www.ebi.ac.uk/chembl/api/data/activity.json?target_chembl_id={resolved_chembl_id}",
                    "chembl_target_id": resolved_chembl_id,
                    "target_id": target_id,
                },
            ))
        return results

    def collect_safety_pack(self, target_payload: dict, limit: int = 20) -> list[CollectionResult]:
        results: list[CollectionResult] = []
        mechanisms = self._get_json(
            f"{self.base_url}/mechanism.json",
            params={"target_chembl_id": target_payload.get("chembl_target_id"), "limit": min(limit, 100)},
        )
        warnings = []
        for item in mechanisms or []:
            results.append(CollectionResult(
                source=self.source_name,
                target_id=target_payload.get("target_id"),
                external_id=item.get("mechanism_id") or item.get("chembl_id"),
                document_type="mechanism_or_safety",
                title=f"{target_payload.get('name')} mechanism record",
                content=self._format_mechanism(item),
                metadata={
                    "source_url": "https://www.ebi.ac.uk/chembl/api/data/mechanism.json",
                    "target_id": target_payload.get("target_id"),
                },
            ))
        if not results:
            warnings.append("chembl_mechanism_empty")
        return [CollectionResult(
            source=self.source_name,
            target_id=target_payload.get("target_id"),
            external_id=target_payload.get("chembl_target_id"),
            document_type="mechanism_or_safety",
            title=f"{target_payload.get('name')} mechanism/safety summary",
            warnings=warnings or ["chembl_mechanism_empty"],
        )]

    def _get_json(self, url: str, params: dict | None = None) -> Any:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, params=params)
            if response.status_code != 200:
                return None
            return response.json()

    def _format_target(self, data: dict) -> str:
        sections = [
            f"ChEMBL target: {data.get('pref_name') or data.get('target_chembl_id')}",
            f"Type: {data.get('target_type')}",
            f"Organism: {data.get('organism', {})}",
        ]
        if data.get("ligand_gated_ion_channel") or data.get("protein_gated_ion_channel"):
            sections.append("Ion channel type noted in target metadata.")
        if data.get("zyme"):
            sections.append(f"Enzyme classification: {data.get('zyme')}")
        if data.get("tax_id"):
            sections.append(f"NCBI tax ID: {data.get('tax_id')}")
        return "\n".join(sections)

    def _format_activity(self, item: dict, abstract: str, target_name: str) -> str:
        molecule = item.get("molecule", {}) or {}
        parts = [
            f"Target: {target_name}",
            f"Assay type: {item.get('assay_type')}",
            f"Relation: {item.get('relation')}",
            f"pChEMBL: {item.get('pchembl_value')}",
            f"Value: {item.get('standard_value')} {item.get('standard_units')}",
            f"Type: {item.get('standard_type')}",
            f"Molecule: {molecule.get('pref_name') or molecule.get('chembl_id')}",
        ]
        if abstract:
            parts.append(f"Abstract: {abstract[:700]}")
        return "\n".join(parts)

    def _format_mechanism(self, item: dict) -> str:
        parts = [
            f"Mechanism ID: {item.get('mechanism_id') or item.get('chembl_id')}",
            f"Mechanism of action: {item.get('mechanism_of_action')}",
            f"Target: {item.get('target_name')}",
            f"Target chembl_id: {item.get('target_chembl_id')}",
            f"Molecule: {item.get('molecule_chembl_id')}",
            f"Action type: {item.get('action_type')}",
        ]
        return "\n".join(parts)
