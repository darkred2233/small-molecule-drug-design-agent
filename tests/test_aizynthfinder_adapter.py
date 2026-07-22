import json
from pathlib import Path

from medagent.services import aizynthfinder_adapter
from medagent.services.aizynthfinder_adapter import AiZynthFinderRequest, AiZynthFinderResult


def test_unavailable_local_aizynthfinder_never_claims_a_route(tmp_path):
    result = aizynthfinder_adapter.run_aizynthfinder_retrosynthesis(
        AiZynthFinderRequest(smiles="CCO", output_dir=str(tmp_path)),
        {"available": False},
    )

    assert result.success is False
    assert result.route_found is False
    assert result.adapter_mode == "aizynthfinder_unavailable"
    assert result.warnings == ["aizynthfinder_not_installed"]


def test_local_command_uses_isolated_cli_entrypoint(tmp_path):
    command = aizynthfinder_adapter._build_aizynthfinder_local_command(
        {"path": "C:/local/envs/aizynthfinder/aizynthcli.exe"},
        tmp_path / "config.yml",
        tmp_path / "targets.smi",
        tmp_path / "routes.json",
    )

    assert command[0] == "C:/local/envs/aizynthfinder/aizynthcli.exe"
    assert "--config" in command and "--smiles" in command and "--output" in command


def test_local_execution_passes_config_smiles_and_output_to_cli(tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    config.write_text("stock: {}\n", encoding="utf-8")
    captured = {}

    def fake_run_command(**kwargs):
        captured.update(kwargs)
        return AiZynthFinderResult("aizynthfinder_local", "aizynthfinder", True, route_found=False)

    monkeypatch.setattr(aizynthfinder_adapter, "_run_command", fake_run_command)
    result = aizynthfinder_adapter.run_aizynthfinder_retrosynthesis(
        AiZynthFinderRequest(smiles="CCO", output_dir=str(tmp_path / "output"), config_file=str(config)),
        {"available": True, "path": "aizynthcli.exe"},
    )

    assert result.success is True
    command = captured["command"]
    assert command[0] == "aizynthcli.exe"
    assert Path(command[command.index("--config") + 1]) == config


def test_parser_preserves_route_tree_stock_and_max_steps(tmp_path):
    output = tmp_path / "routes.json"
    output.write_text(
        json.dumps(
            {
                "is_solved": True,
                "number_of_solved_routes": 1,
                "number_of_steps": 2,
                "top_score": 0.91,
                "stock_info": {"CCO": "in_stock"},
                "trees": [{"smiles": "CCOC", "children": []}],
            }
        ),
        encoding="utf-8",
    )

    parsed = aizynthfinder_adapter._parse_aizynthfinder_output(output, max_steps=1)

    assert parsed["parsed"] is True
    assert parsed["route_found"] is False
    assert parsed["route_score"] == 0.91
    assert parsed["stock_info"] == {"CCO": "in_stock"}
    assert "aizynthfinder_route_exceeds_max_steps" in parsed["warnings"]
