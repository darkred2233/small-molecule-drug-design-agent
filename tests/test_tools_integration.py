from medagent.services.admet_adapter import ChempropADMETRequest, check_chemprop_available, run_chemprop_admet
from medagent.services.docking_adapters import DockingToolRequest, build_gnina_command, select_docking_tool
from medagent.services.molecule_generation import generation_tool_status
from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced


def test_rdkit_validates_a_known_drug_like_smiles():
    result = validate_and_calculate_enhanced("CC(=O)Oc1ccccc1C(=O)O")

    assert result.available is True
    assert result.valid is True
    assert result.descriptors is not None
    assert "rdkit_validation_passed" in result.labels


def test_rdkit_rejects_an_invalid_smiles():
    result = validate_and_calculate_enhanced("INVALID_SMILES")

    assert result.valid is False
    assert result.reason


def test_tool_catalog_exposes_only_local_generation_and_docking_runtimes(tmp_path):
    status = generation_tool_status()
    request = DockingToolRequest(
        receptor_file=str(tmp_path / "receptor.pdb"),
        ligand_file=str(tmp_path / "ligand.sdf"),
        output_dir=str(tmp_path / "output"),
        grid_center=[0, 0, 0],
        grid_size=[20, 20, 20],
    )
    command, _ = build_gnina_command("gnina.exe", request)

    assert {"crem", "targetdiff", "autogrow4"} <= status.keys()
    assert select_docking_tool(request, {"gnina": {"available": True}, "vina": {"available": False}}) == "gnina"


def test_admet_api_contract_reports_actual_runtime_availability():
    status = check_chemprop_available()
    result = run_chemprop_admet(
        ChempropADMETRequest(smiles_list=["CCO"], molecule_ids=["MOL-1"]),
        {"available": False, "warning": "not_configured"},
    )

    assert {"available", "mode", "runtime_available", "model_configured"} <= status.keys()
    assert result.success is False
    assert result.results == []
