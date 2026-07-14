import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from medagent.services import aizynthfinder_adapter
from medagent.services.aizynthfinder_adapter import (
    AiZynthFinderRequest,
    AiZynthFinderResult,
    aizynthfinder_tool_status,
    run_aizynthfinder_retrosynthesis,
)

ROOT = Path(__file__).resolve().parents[1]


def test_aizynthfinder_status_has_stable_shape():
    status = aizynthfinder_tool_status()

    assert set(status) == {
        "available",
        "mode",
        "version",
        "path",
        "docker_image",
        "model_configured",
    }


def test_aizynthfinder_unavailable_returns_safe_fallback(tmp_path):
    request = AiZynthFinderRequest(smiles="CCO", output_dir=str(tmp_path))

    result = run_aizynthfinder_retrosynthesis(request, {"available": False})

    assert not result.success
    assert result.adapter_mode == "aizynthfinder_unavailable"
    assert "aizynthfinder_not_installed" in result.warnings


def test_aizynthfinder_available_without_config_does_not_claim_real_route(tmp_path, monkeypatch):
    monkeypatch.delenv("AIZYNTHFINDER_CONFIG", raising=False)
    monkeypatch.delenv("MEDAGENT_AIZYNTHFINDER_CONFIG", raising=False)
    monkeypatch.setattr(aizynthfinder_adapter, "_default_config_path", lambda: None)
    request = AiZynthFinderRequest(smiles="CCO", output_dir=str(tmp_path))

    result = run_aizynthfinder_retrosynthesis(
        request,
        {"available": True, "mode": "local_cli", "path": "aizynthcli"},
    )

    assert not result.success
    assert not result.route_found
    assert result.adapter_mode == "aizynthfinder_model_not_configured"
    assert "aizynthfinder_config_not_configured" in result.warnings


def test_aizynthfinder_local_run_uses_smiles_file_and_parses_output(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yml"
    config_file.write_text("policy: {}\nstock: {}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        smiles_file = Path(cmd[cmd.index("--smiles") + 1])
        assert smiles_file.read_text(encoding="utf-8").strip() == "CCO"
        assert str(smiles_file) != "CCO"

        output_file = Path(cmd[cmd.index("--output") + 1])
        _write_aizynthfinder_json(output_file, is_solved=True, steps=2, score=0.873)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(aizynthfinder_adapter.subprocess, "run", fake_run)

    result = run_aizynthfinder_retrosynthesis(
        AiZynthFinderRequest(
            smiles="CCO",
            output_dir=str(tmp_path / "out"),
            config_file=str(config_file),
            max_steps=3,
        ),
        {"available": True, "mode": "local_cli", "path": "aizynthcli"},
    )

    assert result.success
    assert result.route_found
    assert result.num_steps == 2
    assert result.route_score == 0.873
    assert result.adapter_mode == "aizynthfinder_local"
    assert captured["cwd"] == str(config_file.parent)


def test_aizynthfinder_python_package_mode_uses_module_entrypoint(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yml"
    config_file.write_text("policy: {}\nstock: {}\n", encoding="utf-8")
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        captured["cmd"] = cmd
        output_file = Path(cmd[cmd.index("--output") + 1])
        _write_aizynthfinder_json(output_file, is_solved=True, steps=1, score=0.5)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(aizynthfinder_adapter.subprocess, "run", fake_run)

    result = run_aizynthfinder_retrosynthesis(
        AiZynthFinderRequest(
            smiles="CCO",
            output_dir=str(tmp_path / "out"),
            config_file=str(config_file),
        ),
        {"available": True, "mode": "python_package"},
    )

    assert result.success
    assert captured["cmd"][:3] == [
        sys.executable,
        "-m",
        "aizynthfinder.interfaces.aizynthcli",
    ]


def test_aizynthfinder_route_above_max_steps_is_not_claimed(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yml"
    config_file.write_text("policy: {}\nstock: {}\n", encoding="utf-8")

    def fake_run(cmd, **_kwargs):
        output_file = Path(cmd[cmd.index("--output") + 1])
        _write_aizynthfinder_json(output_file, is_solved=True, steps=7, score=0.9)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(aizynthfinder_adapter.subprocess, "run", fake_run)

    result = run_aizynthfinder_retrosynthesis(
        AiZynthFinderRequest(
            smiles="CCO",
            output_dir=str(tmp_path / "out"),
            config_file=str(config_file),
            max_steps=3,
        ),
        {"available": True, "mode": "local_cli", "path": "aizynthcli"},
    )

    assert result.success
    assert not result.route_found
    assert result.num_steps == 7
    assert "aizynthfinder_route_exceeds_max_steps" in result.warnings


def test_aizynthfinder_parse_failure_is_not_success(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yml"
    config_file.write_text("policy: {}\nstock: {}\n", encoding="utf-8")

    def fake_run(cmd, **_kwargs):
        output_file = Path(cmd[cmd.index("--output") + 1])
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("not-json", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(aizynthfinder_adapter.subprocess, "run", fake_run)

    result = run_aizynthfinder_retrosynthesis(
        AiZynthFinderRequest(
            smiles="CCO",
            output_dir=str(tmp_path / "out"),
            config_file=str(config_file),
        ),
        {"available": True, "mode": "local_cli", "path": "aizynthcli"},
    )

    assert not result.success
    assert not result.route_found
    assert "aizynthfinder_output_parse_failed" in result.warnings


def test_aizynthfinder_does_not_reuse_stale_output(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yml"
    config_file.write_text("policy: {}\nstock: {}\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    stale_output = output_dir / "aizynthfinder_routes.json"
    _write_aizynthfinder_json(stale_output, is_solved=True, steps=1, score=0.99)

    def fake_run(cmd, **_kwargs):
        assert not stale_output.exists()
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(aizynthfinder_adapter.subprocess, "run", fake_run)

    result = run_aizynthfinder_retrosynthesis(
        AiZynthFinderRequest(
            smiles="CCO",
            output_dir=str(output_dir),
            config_file=str(config_file),
        ),
        {"available": True, "mode": "local_cli", "path": "aizynthcli"},
    )

    assert not result.success
    assert not result.route_found
    assert "aizynthfinder_output_missing" in result.warnings


def test_docker_tool_catalog_includes_aizynthfinder():
    spec = importlib.util.spec_from_file_location(
        "manage_docker_tools",
        ROOT / "scripts" / "manage_docker_tools.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.TOOLS["aizynthfinder"]["service"] == "aizynthfinder"
    assert module.TOOLS["aizynthfinder"]["image"] == "aizynthfinder:latest"


def test_docker_compose_declares_aizynthfinder_service():
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = ROOT / "docker" / "aizynthfinder" / "Dockerfile"

    assert "aizynthfinder:" in compose_text
    assert "build: docker/aizynthfinder" in compose_text
    assert dockerfile.exists()


def test_retrosynthesis_analysis_falls_back_after_aizynthfinder_adapter_warning(monkeypatch):
    from medagent.services import aizynthfinder_adapter
    from medagent.services.synthesis_workflow import run_retrosynthesis_analysis

    def fake_retrosynthesis(*_args, **_kwargs):
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_model_not_configured",
            tool_name="aizynthfinder",
            success=False,
            warnings=["aizynthfinder_config_not_configured"],
        )

    monkeypatch.setattr(
        aizynthfinder_adapter,
        "run_aizynthfinder_retrosynthesis",
        fake_retrosynthesis,
    )

    result = run_retrosynthesis_analysis("CCO")

    assert result.success
    assert result.route_found
    assert "aizynthfinder_config_not_configured" in result.warnings
    assert "retrosynthesis_estimated_not_actual" in result.warnings


def _write_aizynthfinder_json(
    output_file: Path,
    *,
    is_solved: bool,
    steps: int,
    score: float,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "target": "CCO",
                        "is_solved": is_solved,
                        "number_of_steps": steps,
                        "number_of_solved_routes": 1 if is_solved else 0,
                        "top_score": score,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
