from pathlib import Path


def test_current_package_imports_expose_round_orchestrator():
    from medagent.configs.settings import Settings as FinalSettings
    from medagent.core.config import Settings as LegacySettings
    from medagent.pipeline.round_orchestrator import RoundOrchestrator
    from medagent.reporting.project_report import build_project_report as final_report
    from medagent.services.project_report import build_project_report as legacy_report

    assert RoundOrchestrator.__name__ == "RoundOrchestrator"
    assert final_report is legacy_report
    assert FinalSettings is LegacySettings


def test_final_structure_directories_have_landing_files():
    repo_root = Path(__file__).resolve().parents[1]

    expected_paths = [
        repo_root / "configs" / "models.yaml",
        repo_root / "configs" / "scoring.yaml",
        repo_root / "configs" / "filters.yaml",
        repo_root / "configs" / "tools.yaml",
    ]

    missing = [path for path in expected_paths if not path.exists()]
    assert missing == []


def test_tools_status_response_includes_aizynthfinder():
    from medagent.api.tools_router import ToolStatusResponse

    assert "aizynthfinder" in ToolStatusResponse.model_fields
