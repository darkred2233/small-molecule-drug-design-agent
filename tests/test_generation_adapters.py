import json
import tomllib

from medagent.services import autogrow4_adapter
from medagent.services import reinvent4_adapter
from medagent.services.autogrow4_adapter import AutoGrow4Request
from medagent.services.reinvent4_adapter import Reinvent4Request


def test_autogrow4_docker_command_uses_json_entrypoint(tmp_path):
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

    config_path = tmp_path / "config.json"
    config = autogrow4_adapter._write_autogrow4_config(
        config_path,
        request,
        receptor_file="/data/protein.pdb",
        seeds_file="/data/seeds.smi",
        output_dir="/data/output",
        docker=True,
    )
    command = autogrow4_adapter._build_autogrow4_command(
        config_file="/data/config.json",
        executable=["-m", "autogrow4"],
    )

    assert command == ["-m", "autogrow4", "-j", "/data/config.json"]
    assert json.loads(config_path.read_text(encoding="utf-8")) == config
    assert config["filename_of_receptor"] == "/data/protein.pdb"
    assert config["source_compound_file"] == "/data/seeds.smi"
    assert config["root_output_folder"] == "/data/output"
    assert config["center_z"] == 3.0
    assert config["size_y"] == 19.0
    assert config["number_of_mutants"] > 0
    assert config["number_of_crossovers"] > 0


def test_autogrow4_parser_reads_nested_ranked_smi(tmp_path):
    ranked = tmp_path / "Run_0" / "generation_2" / "generation_2_ranked.smi"
    ranked.parent.mkdir(parents=True)
    ranked.write_text("CCO\tligand_1\t-7.4\nCCN\tligand_2\t-6.8\n", encoding="utf-8")

    smiles, scores = autogrow4_adapter._parse_autogrow4_output(tmp_path)

    assert smiles == ["CCO", "CCN"]
    assert scores == [-7.4, -6.8]


def test_autogrow4_parser_uses_highest_numeric_generation(tmp_path):
    generation_2 = tmp_path / "Run_0" / "generation_2" / "generation_2_ranked.smi"
    generation_10 = tmp_path / "Run_0" / "generation_10" / "generation_10_ranked.smi"
    generation_2.parent.mkdir(parents=True)
    generation_10.parent.mkdir(parents=True)
    generation_2.write_text("CCO\tligand_1\t-7.4\n", encoding="utf-8")
    generation_10.write_text("CCN\tligand_2\t-8.1\n", encoding="utf-8")

    smiles, scores = autogrow4_adapter._parse_autogrow4_output(tmp_path)

    assert smiles == ["CCN"]
    assert scores == [-8.1]


def test_autogrow4_parser_keeps_missing_fitness_as_none(tmp_path):
    ranked = tmp_path / "Run_0" / "generation_1" / "generation_1_ranked.smi"
    ranked.parent.mkdir(parents=True)
    ranked.write_text("CCO\tligand_1\n", encoding="utf-8")

    smiles, scores = autogrow4_adapter._parse_autogrow4_output(tmp_path)

    assert smiles == ["CCO"]
    assert scores == [None]


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


def test_reinvent4_parser_keeps_missing_sampling_score_as_none(tmp_path):
    output = tmp_path / "sampling.csv"
    output.write_text("SMILES\nCCO\n", encoding="utf-8")

    smiles, scores = reinvent4_adapter._parse_reinvent4_output(output)

    assert smiles == ["CCO"]
    assert scores == [None]
