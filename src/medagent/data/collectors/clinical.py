from __future__ import annotations


import httpx

from medagent.data.collectors.base import BaseCollector, CollectionResult


class ClinicalCollector(BaseCollector):
    source_name = "clinicaltrials_placeholder"
    base_url = "https://clinicaltrials.gov/api/v2/studies"

    def collect_target_pack(self, target_payload: dict) -> list[CollectionResult]:
        query = target_payload.get("name") or target_payload.get("target_id", "")
        return self._search(query, target_payload.get("target_id"), limit=10)

    def _search(self, query: str, target_id: str | None, limit: int = 10) -> list[CollectionResult]:
        if not query:
            return [CollectionResult(
                source=self.source_name,
                target_id=target_id,
                document_type="clinical_evidence",
                title="Clinical evidence",
                warnings=["clinical_query_empty"],
            )]
        params = {"query": query, "pageSize": limit, "format": "json"}
        with httpx.Client(timeout=20.0) as client:
            response = client.get(self.base_url, params=params)
        if response.status_code != 200:
            return [CollectionResult(
                source=self.source_name,
                target_id=target_id,
                document_type="clinical_evidence",
                title="Clinical evidence",
                warnings=[f"clinicaltrials_fetch_failed:{response.status_code}"],
            )]
        data = response.json()
        studies = ((data.get("studies") or []) if isinstance(data, dict) else [])[:limit]
        results: list[CollectionResult] = []
        for study_wrapper in studies:
            study = (study_wrapper or {}).get("protocolSection") or {}
            identification = study.get("identificationModule") or {}
            description = study.get("descriptionModule") or {}
            results.append(CollectionResult(
                source=self.source_name,
                target_id=target_id,
                external_id=identification.get("nctId"),
                document_type="clinical_evidence",
                title=identification.get("officialTitle") or identification.get("briefTitle") or "Clinical trial",
                content=self._format_study(identification, description, target_id),
                metadata={
                    "source_url": f"https://clinicaltrials.gov/study/{identification.get('nctId')}" if identification.get("nctId") else self.base_url,
                    "target_id": target_id,
                },
            ))
        return results or [CollectionResult(
            source=self.source_name,
            target_id=target_id,
            document_type="clinical_evidence",
            title="Clinical evidence",
            warnings=["clinicaltrials_results_empty"],
        )]

    def _format_study(self, identification: dict, description: dict, target_id: str | None) -> str:
        parts = [
            f"Target: {target_id or 'unknown'}",
            f"NCT ID: {identification.get('nctId')}",
            f"Title: {identification.get('officialTitle') or identification.get('briefTitle')}",
        ]
        brief = description.get("briefSummary") or ""
        if brief:
            parts.append(f"Summary: {brief[:1400]}")
        return "\n".join(parts)
