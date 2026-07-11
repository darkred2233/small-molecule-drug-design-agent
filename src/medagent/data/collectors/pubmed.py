from __future__ import annotations


import httpx

from medagent.data.collectors.base import BaseCollector, CollectionResult


class PubMedCollector(BaseCollector):
    source_name = "pubmed"
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    search_queries = [
        "{target} AND ({alias}) AND (inhibitor OR ligand) AND (SAR OR structure-activity OR crystal structure OR ADMET)",
        "{target} AND resistance OR mechanism",
        "{target} AND selectivity OR pharmacokinetics",
    ]

    def collect_target_pack(self, target_payload: dict) -> list[CollectionResult]:
        results: list[CollectionResult] = []
        seen_ids: set[str] = set()
        for query_template in self.search_queries:
            query = query_template.format(target=target_payload.get("name"), alias=target_payload.get("aliases", [""])[0])
            pmids = self._search_pmids(query, retmax=15)
            for pmid in pmids:
                if pmid in seen_ids:
                    continue
                seen_ids.add(pmid)
                summary = self._fetch_summary(pmid)
                if summary:
                    results.append(CollectionResult(
                        source=self.source_name,
                        target_id=target_payload.get("target_id"),
                        external_id=summary.get("uid"),
                        document_type="literature_summary",
                        title=summary.get("title") or f"PubMed {summary.get('uid')}",
                        content=self._format_summary(summary, target_payload),
                        metadata={
                            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{summary.get('uid')}/",
                            "pubmed_id": summary.get("uid"),
                            "target_id": target_payload.get("target_id"),
                        },
                    ))
                if len(results) >= 15:
                    break
            if len(results) >= 15:
                break
        return results

    def _search_pmids(self, query: str, retmax: int = 15) -> list[str]:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                f"{self.base_url}/esearch.fcgi",
                params={"db": "pubmed", "term": query, "retmax": retmax, "retmode": "json"},
            )
            if response.status_code != 200:
                return []
            data = response.json()
        return data.get("esearchresult", {}).get("idlist") or []

    def _fetch_summary(self, pmid: str) -> dict | None:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                f"{self.base_url}/esummary.fcgi",
                params={"db": "pubmed", "id": pmid, "retmode": "json"},
            )
            if response.status_code != 200:
                return None
            data = response.json()
        result = (data.get("result") or {}).get(pmid)
        if not isinstance(result, dict):
            return None
        return {"uid": pmid, "title": result.get("title"), "abstract": result.get("abstract"), "authors": result.get("authorlist")}

    def _format_summary(self, summary: dict, target_payload: dict) -> str:
        authors = summary.get("authors") or []
        author_text = ", ".join(authors[:6]) if isinstance(authors, list) else ""
        parts = [
            f"Target: {target_payload.get('name')} ({target_payload.get('target_id')})",
            f"Title: {summary.get('title')}",
            f"PubMed ID: {summary.get('uid')}",
        ]
        if author_text:
            parts.append(f"Authors: {author_text}")
        abstract = summary.get("abstract") or ""
        if abstract:
            parts.append(f"Abstract: {abstract[:1800]}")
        return "\n".join(parts)
