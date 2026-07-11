from __future__ import annotations


import httpx

from medagent.data.collectors.base import BaseCollector, CollectionResult


class UniProtCollector(BaseCollector):
    source_name = "uniprot"
    base_url = "https://rest.uniprot.org/uniprotkb"

    def collect_target_pack(self, target_payload: dict) -> list[CollectionResult]:
        accession = target_payload.get("uniprot_id")
        if not accession:
            return []

        try:
            data = self._fetch_accession(accession)
        except Exception as exc:
            return [CollectionResult(
                source=self.source_name,
                target_id=target_payload.get("target_id"),
                external_id=accession,
                document_type="target_profile",
                title=f"{target_payload.get('name')} UniProt profile",
                warnings=[f"uniprot_fetch_failed:{exc}"],
            )]

        if not data:
            return []

        text = self._format_accession(data, target_payload)
        return [CollectionResult(
            source=self.source_name,
            target_id=target_payload.get("target_id"),
            external_id=accession,
            document_type="target_profile",
            title=f"{target_payload.get('name')} UniProt profile",
            content=text,
            metadata={
                "source_url": f"https://www.uniprot.org/uniprotkb/{accession}",
                "accession": accession,
                "target_id": target_payload.get("target_id"),
            },
        )]

    def _fetch_accession(self, accession: str) -> dict | None:
        url = f"{self.base_url}/{accession}.json"
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url)
            if response.status_code != 200:
                return None
            return response.json()

    def _extract_gene_name(self, gene: dict) -> str:
        candidates = gene.get("geneName") or []
        if isinstance(candidates, dict):
            candidates = [candidates]
        for candidate in candidates:
            if isinstance(candidate, dict):
                value = candidate.get("value") or candidate.get("geneName", {}).get("value")
                if value:
                    return value
        return ""

    def _format_accession(self, data: dict, target_payload: dict) -> str:
        genes = data.get("genes", [])
        gene_names = ", ".join(
            self._extract_gene_name(gene)
            for gene in genes
        ) or "unknown"

        function = ""
        for comment in data.get("comments", []):
            if comment.get("commentType") == "FUNCTION":
                texts = comment.get("texts") or comment.get("text", [])
                if isinstance(texts, list):
                    function = "\n".join(item.get("value", "") for item in texts if isinstance(item, dict))
                elif isinstance(texts, str):
                    function = texts
                break

        disease_comments = []
        for comment in data.get("comments", []):
            if comment.get("commentType") == "DISEASE":
                texts = comment.get("texts") or comment.get("text", [])
                if isinstance(texts, list):
                    for item in texts:
                        if isinstance(item, dict):
                            disease_comments.append(item.get("value", ""))
                elif isinstance(texts, str):
                    disease_comments.append(texts)

        keywords = ", ".join(
            kw.get("name", "")
            for kw in data.get("keywords", [])
            if isinstance(kw, dict) and kw.get("name")
        )

        lines = [
            f"Target: {target_payload.get('name')} ({target_payload.get('target_id')})",
            f"UniProt accession: {data.get('primaryAccession')}",
            f"Gene: {gene_names}",
            f"Organism: {data.get('organism', {}).get('scientificName', 'unknown')}",
            f"Protein names: {data.get('proteinDescription', {}).get('recommendedName', {}).get('fullName', {}).get('value', 'unknown')}",
            "",
            f"Function: {function or 'Not described in this record.'}",
            "",
            f"Disease associations: {'; '.join(disease_comments) if disease_comments else 'None listed.'}",
            "",
            f"Keywords: {keywords or 'None'}",
        ]
        return "\n".join(lines)
