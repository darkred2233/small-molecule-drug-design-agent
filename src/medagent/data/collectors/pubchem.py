from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from medagent.data.collectors.base import BaseCollector, CollectionResult


class PubChemCollector(BaseCollector):
    source_name = "pubchem"
    property_url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/property/"
        "SMILES,ConnectivitySMILES,CanonicalSMILES,IsomericSMILES,InChIKey,"
        "MolecularFormula,MolecularWeight,ExactMass/JSON"
    )
    synonym_url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
    description_url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/"
        "JSON/?heading=Description&heading=Drug%20Information"
    )

    def collect_target_pack(self, target_payload: dict) -> list[CollectionResult]:
        results: list[CollectionResult] = []
        for drug_payload in target_payload.get("drugs", []):
            name = self._drug_name(drug_payload)
            if not name:
                continue
            result = self._collect_drug(name, target_payload.get("target_id"), target_payload.get("name"))
            if result:
                results.append(result)
        return results

    def _drug_name(self, drug_payload: Any) -> str:
        if isinstance(drug_payload, dict):
            return drug_payload.get("drug_name") or drug_payload.get("name") or ""
        if isinstance(drug_payload, (list, tuple)) and drug_payload:
            return str(drug_payload[0])
        return ""

    def _collect_drug(self, name: str, target_id: str | None, target_name: str | None) -> CollectionResult | None:
        try:
            properties = self._fetch_properties(name)
        except Exception as exc:
            return CollectionResult(
                source=self.source_name,
                target_id=target_id,
                external_id=name,
                document_type="reference_drug",
                title=f"{target_name} reference drug: {name}",
                warnings=[f"pubchem_property_failed:{exc}"],
            )

        if not properties:
            return CollectionResult(
                source=self.source_name,
                target_id=target_id,
                external_id=name,
                document_type="reference_drug",
                title=f"{target_name} reference drug: {name}",
                warnings=["pubchem_property_not_found"],
            )

        cid = properties.get("CID")
        synonyms: list[str] = []
        description = ""
        if cid is not None:
            try:
                synonyms = self._fetch_synonyms(cid)
            except Exception:
                synonyms = []
            try:
                description = self._fetch_description(cid)
            except Exception:
                description = ""

        canonical_smiles = (
            properties.get("CanonicalSMILES")
            or properties.get("ConnectivitySMILES")
            or properties.get("SMILES")
        )
        isomeric_smiles = properties.get("IsomericSMILES") or properties.get("SMILES") or canonical_smiles

        parts = [
            f"Reference drug: {name}",
            f"Target context: {target_name} ({target_id})",
            f"CID: {cid}",
            f"SMILES: {canonical_smiles}",
            f"Isomeric SMILES: {isomeric_smiles}",
            f"InChIKey: {properties.get('InChIKey')}",
            f"Formula: {properties.get('MolecularFormula')}",
            f"MW: {properties.get('MolecularWeight')}",
        ]
        if synonyms:
            parts.append("Synonyms: " + ", ".join(synonyms[:10]))
        if description:
            parts.append(f"Description: {description[:900]}")
        return CollectionResult(
            source=self.source_name,
            target_id=target_id,
            external_id=str(cid) if cid is not None else name,
            document_type="reference_drug",
            title=f"{target_name} reference drug: {name}",
            content="\n".join(parts),
            metadata={
                "source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid is not None else f"https://pubchem.ncbi.nlm.nih.gov/#query={urllib.parse.quote(name)}",
                "pubchem_cid": cid,
                "target_id": target_id,
                "drug_name": name,
            },
        )

    def _fetch_properties(self, name: str) -> dict | None:
        url = self.property_url.format(name=urllib.parse.quote(name))
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        properties = (payload.get("PropertyTable") or {}).get("Properties") or []
        return properties[0] if properties else None

    def _fetch_synonyms(self, cid: int) -> list[str]:
        url = self.synonym_url.format(cid=cid)
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [item.get("Synonym") for item in (payload.get("InformationList") or {}).get("Information", []) if isinstance(item, dict)]

    def _fetch_description(self, cid: int) -> str:
        url = self.description_url.format(cid=cid)
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return self._extract_description(payload)

    def _extract_description(self, payload: Any) -> str:
        if isinstance(payload, dict):
            sections = payload.get("Record", {}).get("Section") or []
            for section in sections:
                if not isinstance(section, dict):
                    continue
                for subsection in section.get("Section") or []:
                    if not isinstance(subsection, dict):
                        continue
                    for info in subsection.get("Information") or []:
                        if not isinstance(info, dict):
                            continue
                        value = info.get("Value")
                        if isinstance(value, str) and value.strip():
                            return value.strip()[:1200]
                        if isinstance(value, list):
                            texts = [part.get("string") for part in value if isinstance(part, dict) and isinstance(part.get("string"), str)]
                            if texts:
                                return " ".join(texts)[:1200]
        return ""
