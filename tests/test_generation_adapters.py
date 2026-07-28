import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdkit import Chem

from medagent.services import autogrow4_adapter, molecule_generation, targetdiff_adapter
from medagent.services.autogrow4_adapter import AutoGrow4Request
from medagent.services.targetdiff_adapter import TargetDiffRequest
from medagent.services.wsl_runtime import windows_path_from_wsl


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


def _vina_gpu_record(requested_count: int, *, success_count: int | None = None):
    completed = requested_count if success_count is None else success_count
    return {
        "adapter_mode": "vina_gpu_2_1_batch",
        "cpu_fallback_enabled": False,
        "gpu_id": 0,
        "requested_count": requested_count,
        "failed_smiles_names": [],
        "failure": None,
        "batches": [
            {
                "exit_code": 0,
                "input_count": requested_count,
                "success_count": completed,
            }
        ],
    }


def _write_simulated_autogrow_generation(
    output: Path,
    generation: int,
    smiles: list[str],
    *,
    gpu_record: dict | None = None,
) -> None:
    generation_dir = output / "Run_0" / f"generation_{generation}"
    generation_dir.mkdir(parents=True, exist_ok=True)
    ranked = generation_dir / f"generation_{generation}_ranked.smi"
    ranked.write_text(
        "".join(
            f"{value}\tGen_{generation}_Candidate_{index}\t{-6.0 - generation / 10}\n"
            for index, value in enumerate(smiles, start=1)
        ),
        encoding="utf-8",
    )
    if gpu_record is not None:
        (generation_dir / "vina_gpu_batches.jsonl").write_text(
            json.dumps(gpu_record) + "\n",
            encoding="utf-8",
        )


def _stub_autogrow_gpu_runtime(monkeypatch, tmp_path) -> None:
    gpu_executable = tmp_path / "vina_gpu.exe"
    opencl_path = tmp_path / "opencl"
    gpu_executable.write_text("binary", encoding="utf-8")
    opencl_path.mkdir()
    monkeypatch.setattr(
        autogrow4_adapter,
        "get_tool_runtime_config",
        lambda *_args, **_kwargs: SimpleNamespace(
            environment_dict=lambda: {
                "MEDAGENT_VINA_GPU_EXECUTABLE": str(gpu_executable),
                "MEDAGENT_VINA_GPU_OPENCL_BINARY_PATH": str(opencl_path),
            }
        ),
    )
    monkeypatch.setattr(
        autogrow4_adapter,
        "resolve_configured_path",
        lambda value: Path(str(value)),
    )


def test_autogrow_local_config_records_receptor_grid_and_vina(tmp_path):
    request = _autogrow_request(tmp_path)
    config = autogrow4_adapter._autogrow4_config(
        request,
        receptor_file=request.receptor_file,
        seeds_file=str(tmp_path / "seeds.smi"),
        output_dir=str(tmp_path / "output"),
    )
    command = autogrow4_adapter._build_autogrow4_command(
        "config.json", ["python.exe", "RunAutogrow.py"]
    )

    assert config["filename_of_receptor"] == request.receptor_file
    assert config["center_z"] == 3.0
    assert config["dock_choice"] == "VinaGpuBatchDocking"
    assert config["scoring_choice"] == "VINA"
    assert config["conversion_choice"] == "ObabelConversion"
    assert config["multithread_mode"] == "multithreading"
    assert config["number_of_processors"] == 8
    assert config["docking_exhaustiveness"] == 2
    assert config["docking_timeout_limit"] == 300
    assert (
        config["number_of_mutants_first_generation"]
        + config["number_of_crossovers_first_generation"]
        == request.population_size
    )
    assert config["number_of_crossovers_first_generation"] == 0
    assert config["number_elitism_advance_from_previous_gen_first_generation"] == 0
    assert config["top_mols_to_seed_next_generation_first_generation"] == 1
    assert config["diversity_mols_to_seed_first_generation"] == 0
    assert command == ["python.exe", "RunAutogrow.py", "-j", "config.json"]


def test_autogrow_small_source_pool_uses_mutation_only(tmp_path):
    request = _autogrow_request(tmp_path)
    request = AutoGrow4Request(
        seed_smiles=["CCO", "CCN", "c1ccccc1", "CC(=O)O"],
        receptor_file=request.receptor_file,
        output_dir=request.output_dir,
        num_generations=1,
        population_size=4,
        constraints={
            "grid_center": [1, 2, 3],
            "grid_size": [18, 18, 18],
            "crossover_fraction": 0.5,
        },
    )

    config = autogrow4_adapter._autogrow4_config(
        request,
        receptor_file=request.receptor_file,
        seeds_file=str(tmp_path / "seeds.smi"),
        output_dir=str(tmp_path / "output"),
    )

    assert config["number_of_crossovers"] == 0
    assert config["number_of_mutants"] == 2
    assert config["number_elitism_advance_from_previous_gen"] == 1


def test_autogrow_survives_source_pool_shrinking_after_docking(tmp_path):
    request = _autogrow_request(tmp_path)
    request = AutoGrow4Request(
        seed_smiles=[f"{'C' * index}N" for index in range(1, 22)],
        receptor_file=request.receptor_file,
        output_dir=request.output_dir,
        num_generations=3,
        population_size=50,
        constraints={
            "grid_center": [1, 2, 3],
            "grid_size": [18, 18, 18],
            "crossover_fraction": 0.5,
        },
    )

    config = autogrow4_adapter._autogrow4_config(
        request,
        receptor_file=request.receptor_file,
        seeds_file=str(tmp_path / "seeds.smi"),
        output_dir=str(tmp_path / "output"),
    )

    # campaign-CEA3C9499E had 21 inputs but only five ranked survivors by the
    # next generation. Later generations must not still demand 50 mutations.
    assert config["use_docked_source_compounds"] is False
    assert config["selector_choice"] == "Rank_Selector"
    assert config["top_mols_to_seed_next_generation_first_generation"] == 3
    assert config["top_mols_to_seed_next_generation"] == 3
    assert config["number_of_crossovers_first_generation"] == 25
    assert config["number_of_crossovers"] == 1
    assert config["number_of_mutants"] == 3
    assert config["number_elitism_advance_from_previous_gen"] == 1
    assert (
        config["number_of_crossovers"]
        + config["number_of_mutants"]
        + config["number_elitism_advance_from_previous_gen"]
        == 5
    )


def test_autogrow_timeout_covers_all_gpu_waits_and_retries(tmp_path):
    request = replace(
        _autogrow_request(tmp_path, generations=5),
        population_size=50,
        timeout_seconds=3600,
    )

    timeout = autogrow4_adapter._effective_timeout_seconds(
        request,
        {
            "MEDAGENT_VINA_GPU_WAIT_TIMEOUT_SECONDS": "300",
            "MEDAGENT_VINA_GPU_BATCH_TIMEOUT_SECONDS": "1800",
            "MEDAGENT_VINA_GPU_RETRY_COUNT": "1",
            "MEDAGENT_VINA_GPU_MAX_BATCH_SIZE": "128",
        },
    )

    assert timeout == 19800


def test_autogrow_gpu_evidence_accepts_a_recovered_retry():
    record = _vina_gpu_record(5)
    record["batches"].insert(
        0,
        {"exit_code": 2, "input_count": 5, "success_count": 0},
    )

    assert autogrow4_adapter._successful_vina_gpu_record(record) is True


def test_autogrow_five_generation_output_accumulates_fifty_unique_candidates(tmp_path):
    output = tmp_path / "output"
    for generation in range(1, 6):
        ranked = output / f"generation_{generation}" / f"generation_{generation}_ranked.smi"
        ranked.parent.mkdir(parents=True)
        rows = [
            f"{'C' * carbon_count}N\tGen_{generation}_Mutant_{carbon_count}\t{-5.0 - generation / 10}\n"
            for carbon_count in range((generation - 1) * 12 + 1, generation * 12 + 1)
        ]
        ranked.write_text("".join(rows), encoding="utf-8")

    smiles, scores = autogrow4_adapter._parse_autogrow4_output(
        output, generated_only=True
    )

    assert len(smiles) == 60
    assert len(scores) == 60
    assert smiles[:12] == [f"{'C' * count}N" for count in range(49, 61)]


def test_autogrow_simulates_fifty_candidates_across_five_gpu_generations(
    tmp_path, monkeypatch
):
    receptor = tmp_path / "receptor.pdb"
    script = tmp_path / "AutoGrow4" / "RunAutogrow.py"
    receptor.write_text("HEADER RECEPTOR\n", encoding="utf-8")
    script.parent.mkdir()
    script.write_text("# entrypoint\n", encoding="utf-8")
    request = AutoGrow4Request(
        seed_smiles=[f"{'C' * count}N" for count in range(1, 21)],
        receptor_file=str(receptor),
        output_dir=str(tmp_path / "artifacts"),
        num_generations=5,
        population_size=50,
        constraints={
            "grid_center": [2.6, -2.3, -19.4],
            "grid_size": [28.3, 18.0, 18.4],
            "crossover_fraction": 0.5,
            "docking_backend": "vina_gpu_2_1_batch",
            "gpu_required": True,
            "gpu_id": 0,
            "cpu_fallback": False,
        },
    )
    captured = {}

    def fake_run(command, **_kwargs):
        config = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        captured["config"] = config
        output = Path(config["root_output_folder"])
        first_generation = [f"{'C' * count}N" for count in range(1, 51)]
        _write_simulated_autogrow_generation(
            output, 1, first_generation, gpu_record=_vina_gpu_record(50)
        )
        for generation in range(2, 6):
            first_new_carbon = 51 + ((generation - 2) * 4)
            later_generation = [
                first_generation[0],
                *[
                    f"{'C' * count}O"
                    for count in range(first_new_carbon, first_new_carbon + 4)
                ],
            ]
            _write_simulated_autogrow_generation(
                output,
                generation,
                later_generation,
                gpu_record=_vina_gpu_record(5),
            )
        return SimpleNamespace(returncode=0, stdout="simulated", stderr="")

    _stub_autogrow_gpu_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(autogrow4_adapter.subprocess, "run", fake_run)
    result = autogrow4_adapter.run_autogrow4_generation(
        request,
        {
            "available": True,
            "python_executable": "python.exe",
            "script": str(script),
        },
    )

    config = captured["config"]
    assert config["number_of_mutants_first_generation"] == 25
    assert config["number_of_crossovers_first_generation"] == 25
    assert config["number_of_mutants"] == 3
    assert config["number_of_crossovers"] == 1
    assert config["number_elitism_advance_from_previous_gen"] == 1
    assert result.success is True
    assert result.adapter_mode == "vina_gpu_2_1_batch"
    assert len(result.generated_smiles) == 66
    assert result.provenance["cpu_fallback"] is False
    assert result.provenance["requested_count"] == 50
    assert result.provenance["seed_count"] == 20
    assert result.provenance["vina_gpu_provenance"]["successful_generations"] == [
        1,
        2,
        3,
        4,
        5,
    ]


@pytest.mark.parametrize(
    "fault",
    [
        "missing_ranked",
        "empty_ranked",
        "missing_provenance",
        "batch_shortfall",
        "appended_failure",
        "malformed_failure",
    ],
)
def test_autogrow_simulation_rejects_incomplete_gpu_generation_evidence(
    tmp_path, monkeypatch, fault
):
    request = _autogrow_request(tmp_path, generations=5)
    script = tmp_path / "AutoGrow4" / "RunAutogrow.py"
    script.parent.mkdir()
    script.write_text("# entrypoint\n", encoding="utf-8")

    def fake_run(command, **_kwargs):
        config = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        output = Path(config["root_output_folder"])
        for generation in range(1, 6):
            record = _vina_gpu_record(5)
            _write_simulated_autogrow_generation(
                output,
                generation,
                [f"{'C' * generation}{element}" for element in "NOSPF"],
                gpu_record=record,
            )
        generation_three = output / "Run_0" / "generation_3"
        if fault == "missing_ranked":
            (generation_three / "generation_3_ranked.smi").unlink()
        elif fault == "empty_ranked":
            (generation_three / "generation_3_ranked.smi").write_text(
                "SMILES\tID\tScore\n", encoding="utf-8"
            )
        elif fault == "missing_provenance":
            (generation_three / "vina_gpu_batches.jsonl").unlink()
        elif fault == "batch_shortfall":
            (generation_three / "vina_gpu_batches.jsonl").write_text(
                json.dumps(_vina_gpu_record(5, success_count=4)) + "\n",
                encoding="utf-8",
            )
        elif fault == "appended_failure":
            failed = {
                **_vina_gpu_record(5),
                "failure": "RuntimeError:vina_gpu_batch_failed",
            }
            with (generation_three / "vina_gpu_batches.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps(failed) + "\n")
        else:
            malformed = {
                **_vina_gpu_record(5),
                "failure": ["unexpected", "json", "shape"],
            }
            (generation_three / "vina_gpu_batches.jsonl").write_text(
                json.dumps(malformed) + "\n",
                encoding="utf-8",
            )
        return SimpleNamespace(returncode=0, stdout="simulated", stderr="")

    _stub_autogrow_gpu_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(autogrow4_adapter.subprocess, "run", fake_run)
    result = autogrow4_adapter.run_autogrow4_generation(
        request,
        {
            "available": True,
            "python_executable": "python.exe",
            "script": str(script),
        },
    )

    assert result.success is False
    if fault not in {"missing_ranked", "empty_ranked"}:
        assert 3 not in result.provenance["vina_gpu_provenance"][
            "successful_generations"
        ]


def test_external_autogrow_candidates_are_deduplicated_after_canonicalization():
    generated = molecule_generation._external_generation_candidates(
        strategy="autogrow4",
        source="autogrow4_external_docking_guided",
        generated_smiles=["CCO", "OCC"],
        scores=[-7.0, -6.0],
        seeds=["CCN"],
        constraints={},
        rationale="test",
        labels=[],
        adapter_mode="vina_gpu_2_1_batch",
        provenance={},
    )

    assert [candidate.smiles for candidate in generated] == ["CCO"]


def test_autogrow_wsl_source_cache_is_versioned_and_excludes_git_metadata(tmp_path):
    source = tmp_path / "AutoGrow4"
    source.mkdir()
    (source / "RunAutogrow.py").write_text("print('run')\n", encoding="utf-8")
    git = source / ".git"
    git.mkdir()
    (git / "config").write_text("metadata", encoding="utf-8")

    before = autogrow4_adapter._source_tree_fingerprint(source)
    script = autogrow4_adapter._wsl_source_cache_script(
        "/mnt/c/work/AutoGrow4", f"/opt/medagent/cache/{before}", "/opt/medagent/cache"
    )

    (git / "config").write_text("changed metadata", encoding="utf-8")
    assert autogrow4_adapter._source_tree_fingerprint(source) == before
    (source / "RunAutogrow.py").write_text("print('changed')\n", encoding="utf-8")
    assert autogrow4_adapter._source_tree_fingerprint(source) != before
    assert "tar -C \"$source_dir\"" in script
    assert "--exclude=.git" in script
    assert "test -f \"$cache_dir/.ready\"" in script


def test_autogrow_wsl_source_cache_fingerprint_tracks_python_content(tmp_path):
    source = tmp_path / "AutoGrow4"
    source.mkdir()
    entrypoint = source / "RunAutogrow.py"
    entrypoint.write_text("print('one')\n", encoding="utf-8")
    original_stat = entrypoint.stat()
    before = autogrow4_adapter._source_tree_fingerprint(source)

    entrypoint.write_text("print('two')\n", encoding="utf-8")
    os.utime(
        entrypoint,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )

    assert entrypoint.stat().st_size == original_stat.st_size
    assert entrypoint.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert autogrow4_adapter._source_tree_fingerprint(source) != before


def test_autogrow_requires_requested_generation_to_complete(tmp_path, monkeypatch):
    request = _autogrow_request(tmp_path, generations=2)
    script = tmp_path / "RunAutogrow.py"
    script.write_text("# entrypoint", encoding="utf-8")

    def fake_run(command, **_kwargs):
        config = (
            json.loads((tmp_path / "ignored").read_text())
            if False
            else json.loads(__import__("pathlib").Path(command[-1]).read_text(encoding="utf-8"))
        )
        ranked = (
            __import__("pathlib").Path(config["root_output_folder"]) / "generation_1" / "ranked.smi"
        )
        ranked.parent.mkdir(parents=True)
        ranked.write_text("CCCO\t(seed_0+ZINC123)Gen_1_Mutant_1\t-7.2\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(autogrow4_adapter.subprocess, "run", fake_run)
    monkeypatch.setattr(
        autogrow4_adapter,
        "_prepare_wsl_source_cache",
        lambda *_args, **_kwargs: "/opt/medagent/autogrow4-cache/test-source",
    )
    result = autogrow4_adapter.run_autogrow4_generation(
        request,
        {"available": True, "python_executable": "python.exe", "script": str(script)},
    )

    assert result.success is False
    assert result.adapter_mode == "autogrow4_gpu_generation_failed"
    assert "autogrow4_generated_generation_missing" in result.warnings
    assert "autogrow4_vina_gpu_provenance_missing" in result.warnings


def test_autogrow_rejects_cpu_fallback_policy(tmp_path):
    request = _autogrow_request(tmp_path)
    script = tmp_path / "RunAutogrow.py"
    script.write_text("# entrypoint", encoding="utf-8")
    request = replace(
        request,
        constraints={**request.constraints, "cpu_fallback": True},
    )

    result = autogrow4_adapter.run_autogrow4_generation(
        request,
        {"available": True, "python_executable": "python.exe", "script": str(script)},
    )

    assert result.success is False
    assert result.adapter_mode == "autogrow4_gpu_policy_invalid"
    assert result.warnings == ["autogrow4_requires_vina_gpu_without_cpu_fallback"]


def test_autogrow_rejects_invalid_gpu_id_without_raising(tmp_path):
    request = _autogrow_request(tmp_path)
    script = tmp_path / "RunAutogrow.py"
    script.write_text("# entrypoint", encoding="utf-8")
    request = replace(
        request,
        constraints={**request.constraints, "gpu_id": "not-a-number"},
    )

    result = autogrow4_adapter.run_autogrow4_generation(
        request,
        {"available": True, "python_executable": "python.exe", "script": str(script)},
    )

    assert result.success is False
    assert result.adapter_mode == "autogrow4_gpu_policy_invalid"
    assert result.warnings == ["autogrow4_requires_vina_gpu_without_cpu_fallback"]


def test_autogrow_rejects_missing_gpu_runtime(tmp_path, monkeypatch):
    request = _autogrow_request(tmp_path)
    script = tmp_path / "RunAutogrow.py"
    script.write_text("# entrypoint", encoding="utf-8")
    monkeypatch.setattr(autogrow4_adapter, "resolve_configured_path", lambda _value: None)

    result = autogrow4_adapter.run_autogrow4_generation(
        request,
        {"available": True, "python_executable": "python.exe", "script": str(script)},
    )

    assert result.success is False
    assert result.adapter_mode == "autogrow4_vina_gpu_unavailable"
    assert result.warnings == ["autogrow4_vina_gpu_runtime_missing"]


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
        assert command[2].replace("\\", "/").endswith("configs/sampling.yml")
        assert "--pdb_path" in command and "--result_path" in command
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


def test_targetdiff_wsl_command_maps_input_and_output_paths(tmp_path, monkeypatch):
    pocket = tmp_path / "pocket.pdb"
    entrypoint = tmp_path / "TargetDiff" / "scripts" / "sample_for_pocket.py"
    output = tmp_path / "targetdiff-output"
    pocket.write_text("HEADER POCKET\n", encoding="utf-8")
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("# entrypoint", encoding="utf-8")
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        output.mkdir(exist_ok=True)
        writer = Chem.SDWriter(str(output / "generated.sdf"))
        writer.write(Chem.MolFromSmiles("CCO"))
        writer.close()
        return SimpleNamespace(returncode=0, stdout="sampled", stderr="")

    monkeypatch.setattr(targetdiff_adapter.subprocess, "run", fake_run)
    result = targetdiff_adapter.run_targetdiff_generation(
        TargetDiffRequest(str(pocket), str(output), num_samples=1),
        {
            "available": True,
            "runtime_scope": "wsl",
            "python_executable": "/opt/medagent/envs/targetdiff/bin/python",
            "entrypoint": str(entrypoint),
            "entrypoint_wsl": "/mnt/c/project/TargetDiff/scripts/sample_for_pocket.py",
            "source_dir_wsl": "/mnt/c/project/TargetDiff",
            "sampling_config_wsl": "/mnt/c/project/TargetDiff/configs/sampling.yml",
            "wsl_distribution": "Ubuntu",
            "wsl_user": "root",
        },
    )

    assert result.success is True
    assert result.generated_smiles == ["CCO"]
    assert captured["command"][:6] == ["wsl", "-d", "Ubuntu", "-u", "root", "--"]
    shell_command = captured["command"][-1]
    assert "sample_for_pocket.py" in shell_command
    assert "configs/sampling.yml" in shell_command
    assert "--result_path" in shell_command
    assert "PYTHONPATH=/mnt/c/project/TargetDiff" in shell_command


def test_autogrow_wsl_config_uses_linux_visible_paths(tmp_path, monkeypatch):
    request = _autogrow_request(tmp_path, generations=1)
    script = tmp_path / "AutoGrow4" / "RunAutogrow.py"
    script.parent.mkdir(parents=True)
    script.write_text("# entrypoint", encoding="utf-8")
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        captured["timeout"] = _kwargs["timeout"]
        shell_command = command[-1]
        config_token = next(
            token for token in shell_command.split() if token.endswith("config.json")
        )
        config_path = config_token.strip("'")
        windows_config = windows_path_from_wsl(config_path)
        config = json.loads(windows_config.read_text(encoding="utf-8"))
        assert config["filename_of_receptor"].startswith("/mnt/")
        assert config["source_compound_file"].startswith("/mnt/")
        assert config["root_output_folder"].startswith("/mnt/")
        generated = windows_path_from_wsl(config["root_output_folder"])
        ranked = generated / "generation_1" / "generation_1_ranked.smi"
        ranked.parent.mkdir(parents=True)
        ranked.write_text("CCCO\t(seed_0+ZINC123)Gen_1_Mutant_1\t-7.2\n", encoding="utf-8")
        _write_simulated_autogrow_generation(
            generated, 1, ["CCCO"], gpu_record=_vina_gpu_record(1)
        )
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(autogrow4_adapter.subprocess, "run", fake_run)
    monkeypatch.setattr(
        autogrow4_adapter,
        "_prepare_wsl_source_cache",
        lambda *_args, **_kwargs: "/opt/medagent/autogrow4-cache/test-source",
    )
    result = autogrow4_adapter.run_autogrow4_generation(
        request,
        {
            "available": True,
            "runtime_scope": "wsl",
            "python_executable": "/opt/medagent/envs/autogrow4/bin/python",
            "script": str(script),
            "script_wsl": "/mnt/c/project/AutoGrow4/RunAutogrow.py",
            "source_dir_wsl": "/mnt/c/project/AutoGrow4",
            "wsl_distribution": "Ubuntu",
            "wsl_user": "root",
        },
    )

    assert result.success is True
    assert result.adapter_mode == "vina_gpu_2_1_batch"
    assert result.provenance["cpu_fallback"] is False
    assert result.generated_smiles == ["CCCO"]
    assert captured["command"][:6] == ["wsl", "-d", "Ubuntu", "-u", "root", "--"]
    assert "timeout --kill-after=30s" in captured["command"][-1]
    assert captured["timeout"] > result.provenance["effective_timeout_seconds"]
    assert "/opt/medagent/autogrow4-cache/test-source/RunAutogrow.py" in captured["command"][-1]
    assert result.provenance["wsl_source_cache"] == "/opt/medagent/autogrow4-cache/test-source"
