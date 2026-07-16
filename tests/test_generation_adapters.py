import tomllib

from medagent.services import autogrow4_adapter
from medagent.services import reinvent4_adapter
from medagent.services.autogrow4_adapter import AutoGrow4Request
from medagent.services.reinvent4_adapter import Reinvent4Request


def test_autogrow4_docker_command_uses_real_cli_arguments(tmp_path):
    receptor = tmp_path / "protein.pdb"
    output = tmp_path / "output"
    request = AutoGrow4Request(
        seed_smiles=["CCO"],
        receptor_file=str(receptor),
        output_dir=str(output),
        num_generations=3,
        population_size=20,
        constraints={
            "grid_center": [1.0, 2.0, 3.0],
            "grid_size": [18.0, 19.0, 20.0],
        },
    )

    command = autogrow4_adapter._build_autogrow4_command(
        request,
        receptor_file="/data/protein.pdb",
        seeds_file="/data/seeds.smi",
        output_dir="/data/output",
        executable=["-m", "autogrow4"],
        docker=True,
    )

    assert command[:2] == ["-m", "autogrow4"]
    assert "--filename_of_receptor" in command
    assert "--source_compound_file" in command
    assert "--root_output_folder" in command
    assert "--receptor" not in command
    assert command[command.index("--center_z") + 1] == "3.0"
    assert command[command.index("--size_y") + 1] == "19.0"
    assert "--number_of_mutants" in command
    assert "--number_of_crossovers" in command


def test_autogrow4_parser_reads_nested_ranked_smi(tmp_path):
    ranked = tmp_path / "Run_0" / "generation_2" / "generation_2_ranked.smi"
    ranked.parent.mkdir(parents=True)
    ranked.write_text("CCO\tligand_1\t-7.4\nCCN\tligand_2\t-6.8\n", encoding="utf-8")

    smiles, scores = autogrow4_adapter._parse_autogrow4_output(tmp_path)

    assert smiles == ["CCO", "CCN"]
    assert scores == [-7.4, -6.8]


def test_reinvent4_config_uses_real_sampling_schema(tmp_path):
    config = tmp_path / "config.toml"
    prior = tmp_path / "reinvent.prior"
    output = tmp_path / "sampling.csv"
    request = Reinvent4Request(
        seed_smiles=["CCO"],
        output_dir=str(tmp_path),
        num_molecules=12,
        prior_file=str(prior),
    )

    reinvent4_adapter._write_reinvent4_config(
        config,
        request,
        output,
        model_file=str(prior),
        device="cuda:0",
    )
    content = config.read_text(encoding="utf-8")
    parsed = tomllib.loads(content)

    assert 'run_type = "sampling"' in content
    assert 'device = "cuda:0"' in content
    assert parsed["parameters"]["model_file"] == str(prior)
    assert "num_smiles = 12" in content
    assert "[run_type]" not in content
    assert "[scoring]" not in content


def test_reinvent4_docker_command_does_not_repeat_entrypoint(tmp_path):
    prior = tmp_path / "reinvent.prior"
    command = reinvent4_adapter._build_reinvent4_docker_command(
        docker_image="reinvent4:latest",
        data_dir=tmp_path,
        prior_file=prior,
        use_gpu=True,
    )

    image_index = command.index("reinvent4:latest")
    assert command[image_index + 1] == "/data/config.toml"
    assert "reinvent" not in command
    assert f"{prior.resolve()}:/data/model.prior:ro" in command
    assert command[command.index("--gpus") + 1] == "all"


def test_reinvent4_resolves_prior_from_settings(tmp_path, monkeypatch):
    prior = tmp_path / "reinvent.prior"
    prior.write_bytes(b"prior")

    monkeypatch.delenv("REINVENT4_PRIOR_FILE", raising=False)
    monkeypatch.setattr(
        reinvent4_adapter,
        "get_settings",
        lambda: type("SettingsStub", (), {"reinvent4_prior_file": str(prior)})(),
    )

    assert reinvent4_adapter._resolve_prior_file() == prior.resolve()
