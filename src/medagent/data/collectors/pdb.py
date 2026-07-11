from __future__ import annotations

from typing import Any

import httpx

from medagent.data.collectors.base import BaseCollector, CollectionResult


class PDBCollector(BaseCollector):
    source_name = "rcsb_pdb"
    base_url = "https://data.rcsb.org/rest/v1"

    def collect_target_pack(self, target_payload: dict) -> list[CollectionResult]:
        results: list[CollectionResult] = []
        for pdb_id in target_payload.get("pdb_ids", [])[:8]:
            entry = self._fetch_entry(pdb_id)
            if not entry:
                continue
            nonpolymer = self._fetch_nonpolymer(pdb_id)
            ligand = (nonpolymer or [{}])[0] if nonpolymer else {}
            text = self._format_entry(entry, ligand, pdb_id, target_payload)
            results.append(CollectionResult(
                source=self.source_name,
                target_id=target_payload.get("target_id"),
                external_id=pdb_id,
                document_type="structure_summary",
                title=f"{target_payload.get('name')} PDB entry: {pdb_id}",
                content=text,
                metadata={
                    "source_url": f"https://www.rcsb.org/structure/{pdb_id}",
                    "pdb_id": pdb_id,
                    "target_id": target_payload.get("target_id"),
                    "resolution": entry.get("rcsb_entry_info", {}).get("resolution_combined"),
                    "ligand_id": ligand.get("chem_comp_id") if isinstance(ligand, dict) else None,
                },
            ))
        return results

    def _fetch_entry(self, pdb_id: str) -> dict | None:
        return self._get_json(f"{self.base_url}/core/entry/{pdb_id}")

    def _fetch_nonpolymer(self, pdb_id: str) -> Any:
        return self._get_json(f"{self.base_url}/core/nonpolymer_entity/{pdb_id}/1")

    def _get_json(self, url: str) -> Any:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url)
            if response.status_code != 200:
                return None
            return response.json()

    def _format_entry(self, entry: dict, ligand: dict, pdb_id: str, target_payload: dict) -> str:
        info = entry.get("rcsb_entry_info", {}) or {}
        title = entry.get("struct", {}).get("title") or pdb_id
        resolution = info.get("resolution_combined")
        method = entry.get("exptl", [{}])[0].get("method") if entry.get("exptl") else None
        ligand_id = ligand.get("chem_comp_id") if isinstance(ligand, dict) else None
        ligand_name = ligand.get("rcsb_nonpolymer_entity", {}).get("pdbx_description") if isinstance(ligand, dict) else None
        return "\n".join(
            [
                f"PDB entry: {pdb_id}",
                f"Title: {title}",
                f"Target: {target_payload.get('name')} ({target_payload.get('target_id')})",
                f"Method: {method}",
                f"Resolution: {resolution}",
                f"Co-crystal ligand: {ligand_name} ({ligand_id})" if ligand_id else "Co-crystal ligand: unknown",
                "Use this entry to support docking explanation, pocket residue analysis, and binding mode discussion.",
            ]
        )
