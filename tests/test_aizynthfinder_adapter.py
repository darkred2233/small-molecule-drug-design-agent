from medagent.services.aizynthfinder_adapter import (
    AiZynthFinderRequest,
    AiZynthFinderResult,
    aizynthfinder_tool_status,
    run_aizynthfinder_retrosynthesis,
)


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


def test_aizynthfinder_available_without_config_does_not_claim_real_route(tmp_path):
    request = AiZynthFinderRequest(smiles="CCO", output_dir=str(tmp_path))

    result = run_aizynthfinder_retrosynthesis(
        request,
        {"available": True, "mode": "local_cli", "path": "aizynthcli"},
    )

    assert not result.success
    assert not result.route_found
    assert result.adapter_mode == "aizynthfinder_model_not_configured"
    assert "aizynthfinder_config_not_configured" in result.warnings


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
