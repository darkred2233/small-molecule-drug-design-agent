import json
from pathlib import Path

from medagent.services.scientific_execution import (
    CapabilitySnapshot,
    EvidenceLevel,
    ScientificResult,
    build_execution_plan,
    sha256_file,
)


def _snapshot(**overrides):
    values = {
        "tools": {
            "crem": {"available": True, "version": "1.0"},
            "targetdiff": {"available": False},
            "autogrow4": {"available": False},
            "vina": {"available": True, "version": "1.2"},
            "gnina": {"available": False},
            "admet_ai": {"available": False},
            "aizynthfinder": {"available": False},
            "rdkit": {"available": True, "version": "2024.03"},
        },
        "source_release_ids": ["REL-UNIPROT-2026"],
        "target_resource": {
            "target_id": "TGT-EGFR",
            "prepared_receptor": True,
            "verified_pocket": True,
            "reference_ligand": False,
            "targetdiff_pocket": True,
            "artifact_hashes_complete": True,
        },
        "runtime": {"wsl_available": True, "gpu_available": False},
    }
    values.update(overrides)
    return CapabilitySnapshot.create(**values)


def test_execution_plan_blocks_unavailable_tools_without_inventing_results():
    plan = build_execution_plan(_snapshot(), formal_round=True)

    assert plan.formal_round_allowed is True
    assert plan.stage("vina_screen").allowed is True
    assert plan.stage("gnina_refine").allowed is False
    assert plan.stage("gnina_refine").reason_codes == ["gnina_unavailable"]
    assert plan.stage("admet_batch").execution_mode == "rdkit_surrogate"
    assert plan.stage("admet_batch").evidence_level is EvidenceLevel.L1
    assert plan.stage("retrosynthesis_batch").execution_mode == "sa_score_only"


def test_execution_plan_requires_a_frozen_release_for_formal_rounds():
    plan = build_execution_plan(_snapshot(source_release_ids=[]), formal_round=True)

    assert plan.formal_round_allowed is False
    assert "source_releases_not_frozen" in plan.blockers


def test_predicted_pocket_is_usable_for_computational_stages_with_a_warning():
    plan = build_execution_plan(
        _snapshot(
            target_resource={
                "target_id": "TGT-EGFR",
                "prepared_receptor": True,
                "pocket_predicted": True,
                "artifact_hashes_complete": True,
            },
            tools={
                "crem": {"available": False},
                "targetdiff": {"available": True},
                "autogrow4": {"available": True},
                "vina": {"available": True},
                "gnina": {"available": True},
                "admet_ai": {"available": True},
                "aizynthfinder": {"available": True, "model_configured": True},
                "rdkit": {"available": True},
            },
        ),
        formal_round=True,
    )

    assert plan.stage("prepare_target_resource").allowed is True
    assert plan.stage("generate_candidates").allowed is True
    assert plan.stage("vina_screen").allowed is True
    assert "predicted_not_experimentally_validated" in plan.stage("vina_screen").warnings


def test_generation_stage_allows_targetdiff_when_crem_is_unavailable():
    plan = build_execution_plan(
        _snapshot(
            tools={
                "crem": {"available": False},
                "targetdiff": {"available": True},
                "autogrow4": {"available": False},
                "vina": {"available": False},
                "gnina": {"available": False},
                "admet_ai": {"available": False},
                "aizynthfinder": {"available": False},
                "rdkit": {"available": True},
            }
        )
    )

    assert plan.stage("generate_candidates").allowed is True


def test_scientific_result_rejects_external_validation_claims_for_surrogates():
    result = ScientificResult.surrogate(
        stage="admet_batch",
        tool_name="rdkit",
        payload={"risk": "low"},
        warnings=["admet_ai_unavailable"],
    )

    assert result.status == "succeeded"
    assert result.evidence_level is EvidenceLevel.L1
    assert result.execution_mode == "surrogate"
    assert result.is_eligible_for_external_validation is False
    assert "surrogate_result_not_external_validation" in result.warnings


def test_capability_snapshot_converts_paths_for_json_storage():
    snapshot = _snapshot(
        tools={"gnina": {"available": True, "path": Path("/opt/gnina")}},
        target_resource={"prepared_receptor_path": Path("/tmp/receptor.pdbqt")},
        runtime={"working_directory": Path("/tmp/workflow")},
    )

    payload = snapshot.as_dict()

    assert payload["tools"]["gnina"]["path"] == str(Path("/opt/gnina"))
    assert payload["target_resource"]["prepared_receptor_path"] == str(Path("/tmp/receptor.pdbqt"))
    assert payload["runtime"]["working_directory"] == str(Path("/tmp/workflow"))
    json.dumps(payload)


def test_sha256_file_is_stable(tmp_path):
    artifact = Path(tmp_path) / "artifact.txt"
    artifact.write_text("reproducible", encoding="utf-8")

    assert sha256_file(artifact) == sha256_file(artifact)
