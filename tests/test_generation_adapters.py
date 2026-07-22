import json
from types import SimpleNamespace

from rdkit import Chem

from medagent.services import autogrow4_adapter, targetdiff_adapter
from medagent.services.autogrow4_adapter import AutoGrow4Request
from medagent.services.targetdiff_adapter import TargetDiffRequest


def _autogrow_request(tmp_path, *, generations=2):
    receptor = tmp_path / "receptor.pdb"
    receptor.write_text("HEADER RECEPTOR\n", encoding="utf-8")
    return AutoGrow4Request(
        seed_smiles=["CCO"],
        receptor_file=str(receptor),
        output_dir=str(tmp_path / "artifacts"),
        num_generations=generations,
        population_size=10,
        constraints={"grid_center": [1, 2, 3], "grid_size": [18, 18, 18]},
    )


def test_autogrow_local_config_records_receptor_grid_and_vina(tmp_path):
    request = _autogrow_request(tmp_path)
    config = autogrow4_adapter._autogrow4_config(
        request,
        receptor_file=request.receptor_file,
        seeds_file=str(tmp_path / "seeds.smi"),
        output_dir=str(tmp_path / "output"),
    )
    command = autogrow4_adapter._build_autogrow4_command("config.json", ["python.exe", "RunAutogrow.py"])

    assert config["filename_of_receptor"] == request.receptor_file
    assert config["center_z"] == 3.0
    assert config["dock_choice"] == "VinaDocking"
    assert command == ["python.exe", "RunAutogrow.py", "-j", "config.json"]


def test_autogrow_requires_requested_generation_to_complete(tmp_path, monkeypatch):
    request = _autogrow_request(tmp_path, generations=2)
    script = tmp_path / "RunAutogrow.py"
    script.write_text("# entrypoint", encoding="utf-8")

    def fake_run(command, **_kwargs):
        config = json.loads((tmp_path / "ignored").read_text()) if False else json.loads(
            __import__("pathlib").Path(command[-1]).read_text(encoding="utf-8")
        )
        ranked = __import__("pathlib").Path(config["root_output_folder"]) / "generation_1" / "ranked.smi"
        ranked.parent.mkdir(parents=True)
        ranked.write_text("CCCO\tgenerated_1\t-7.2\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(autogrow4_adapter.subprocess, "run", fake_run)
    result = autogrow4_adapter.run_autogrow4_generation(
        request,
        {"available": True, "python_executable": "python.exe", "script": str(script)},
    )

    assert result.success is False
    assert result.adapter_mode == "autogrow4_local_generation"
    assert result.warnings == ["autogrow4_generated_generation_missing"]


def test_targetdiff_runs_a_local_python_entrypoint_and_reads_sdf_output(tmp_path, monkeypatch):
    pocket = tmp_path / "pocket.pdb"
    entrypoint = tmp_path / "sample_for_pdb.py"
    output = tmp_path / "targetdiff-output"
    pocket.write_text("HEADER POCKET\n", encoding="utf-8")
    entrypoint.write_text("# entrypoint", encoding="utf-8")

    def fake_run(command, **_kwargs):
        output.mkdir(exist_ok=True)
        writer = Chem.SDWriter(str(output / "generated.sdf"))
        writer.write(Chem.MolFromSmiles("CCO"))
        writer.close()
        assert command[:2] == ["python.exe", str(entrypoint)]
        assert "--pdb_path" in command and "--out_dir" in command
        return SimpleNamespace(returncode=0, stdout="sampled", stderr="")

    monkeypatch.setattr(targetdiff_adapter.subprocess, "run", fake_run)
    result = targetdiff_adapter.run_targetdiff_generation(
        TargetDiffRequest(str(pocket), str(output), num_samples=1),
        {"available": True, "python_executable": "python.exe", "entrypoint": str(entrypoint)},
    )

    assert result.success is True
    assert result.adapter_mode == "targetdiff_local_generation"
    assert result.generated_smiles == ["CCO"]
    assert result.provenance["generated_pose_is_docking_evidence"] is False
