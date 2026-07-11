from pathlib import Path


def test_final_package_imports_keep_legacy_paths_compatible():
    from medagent.agents.orchestrator import PipelineOrchestrator as LegacyOrchestrator
    from medagent.configs.settings import Settings as FinalSettings
    from medagent.core.config import Settings as LegacySettings
    from medagent.pipeline.orchestrator import PipelineOrchestrator as FinalOrchestrator
    from medagent.reporting.project_report import build_project_report as final_report
    from medagent.services.project_report import build_project_report as legacy_report

    assert FinalOrchestrator is LegacyOrchestrator
    assert final_report is legacy_report
    assert FinalSettings is LegacySettings


def test_final_structure_directories_have_landing_files():
    repo_root = Path(__file__).resolve().parents[1]

    expected_paths = [
        repo_root / "configs" / "models.yaml",
        repo_root / "configs" / "scoring.yaml",
        repo_root / "configs" / "filters.yaml",
        repo_root / "configs" / "tools.yaml",
        repo_root / "infra" / "README.md",
        repo_root / "infra" / "docker" / "README.md",
        repo_root / "infra" / "postgres" / "README.md",
        repo_root / "infra" / "minio" / "README.md",
        repo_root / "infra" / "prefect" / "README.md",
    ]

    missing = [path for path in expected_paths if not path.exists()]
    assert missing == []


def test_tools_status_response_includes_aizynthfinder():
    from medagent.api.tools_router import ToolStatusResponse

    assert "aizynthfinder" in ToolStatusResponse.model_fields

