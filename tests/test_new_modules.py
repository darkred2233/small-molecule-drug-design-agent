"""
Direct module test without full dependency chain.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_round_orchestrator_direct():
    """Test the current round orchestration entry point."""
    from medagent.pipeline import RoundOrchestrator

    for method in (
        "create_round_draft",
        "start_round",
        "run_round_assessment",
        "run_round_ranking",
        "run_round",
    ):
        assert callable(getattr(RoundOrchestrator, method, None))

    print("✓ RoundOrchestrator: all expected lifecycle methods present")


def test_pipeline_recovery_direct():
    """Test pipeline recovery module directly."""
    with open("src/medagent/pipeline/recovery.py", encoding="utf-8") as f:
        content = f.read()
        assert "class PipelineCheckpoint" in content
        assert "class PipelineRecovery" in content
        assert "is_step_idempotent" in content
        assert "should_retry_step" in content
        assert "get_recovery_strategy" in content

    print("✓ Pipeline recovery.py: all expected classes and functions present")


def test_reporting_cards_direct():
    """Test reporting cards module directly."""
    with open("src/medagent/reporting/cards.py", encoding="utf-8") as f:
        content = f.read()
        assert "def format_decision_card" in content
        assert "def format_reasoning_trace" in content
        assert "def format_decision_card_compact" in content
        assert "def group_cards_by_decision" in content
        assert "def generate_decision_summary" in content
        assert "def card_to_html" in content
        assert "def card_to_markdown" in content

    print("✓ Reporting cards.py: all expected functions present")


def test_reporting_tables_direct():
    """Test reporting tables module directly."""
    with open("src/medagent/reporting/tables.py", encoding="utf-8") as f:
        content = f.read()
        assert "def generate_ranking_table" in content
        assert "def generate_molecule_property_table" in content
        assert "def generate_constraint_table" in content
        assert "def generate_agent_run_table" in content
        assert "def table_to_csv" in content
        assert "def table_to_html" in content
        assert "def table_to_markdown" in content
        assert "def calculate_table_statistics" in content

    print("✓ Reporting tables.py: all expected functions present")


def test_reporting_pdf_direct():
    """Test reporting pdf module directly."""
    with open("src/medagent/reporting/pdf.py", encoding="utf-8") as f:
        content = f.read()
        assert "def generate_pdf_report" in content
        assert "from reportlab" in content
        assert "SimpleDocTemplate" in content

    print("✓ Reporting pdf.py: PDF generation function present")


def test_infra_utils_direct():
    """Test infrastructure utils module directly."""
    with open("infra/utils.py", encoding="utf-8") as f:
        content = f.read()
        assert "def check_postgres_health" in content
        assert "def check_minio_health" in content
        assert "def check_all_services" in content
        assert "def get_system_info" in content

    print("✓ Infrastructure utils.py: all expected functions present")


def test_infra_scripts():
    """Test infrastructure scripts exist."""
    assert Path("infra/backup.sh").exists(), "backup.sh should exist"
    assert Path("infra/health_check.sh").exists(), "health_check.sh should exist"
    assert Path("infra/docker/docker-compose.yml").exists(), "docker-compose.yml should exist"
    assert Path("infra/docker/.env.example").exists(), ".env.example should exist"

    print("✓ Infrastructure scripts: all deployment files present")


def test_reporting_init():
    """Test reporting __init__ is updated."""
    with open("src/medagent/reporting/__init__.py", encoding="utf-8") as f:
        content = f.read()
        assert "from medagent.reporting.cards import" in content
        assert "from medagent.reporting.pdf import" in content
        assert "from medagent.reporting.tables import" in content

    print("✓ Reporting __init__.py: properly exports new modules")


def main():
    """Run all tests."""
    print("Running direct module tests...")
    print("=" * 60)

    try:
        test_round_orchestrator_direct()
        test_pipeline_recovery_direct()
        test_reporting_cards_direct()
        test_reporting_tables_direct()
        test_reporting_pdf_direct()
        test_infra_utils_direct()
        test_infra_scripts()
        test_reporting_init()

        print()
        print("=" * 60)
        print("✓ All modules created successfully!")
        print()
        print("Summary of additions:")
        print("  - pipeline/round_orchestrator.py: round lifecycle orchestration")
        print("  - pipeline/recovery.py: Checkpoint and recovery system")
        print("  - reporting/cards.py: Decision card formatting")
        print("  - reporting/tables.py: Table generation utilities")
        print("  - reporting/pdf.py: PDF report generation")
        print("  - infra/utils.py: Health check utilities")
        print("  - infra/backup.sh: Backup script")
        print("  - infra/health_check.sh: Health check script")
        print("  - infra/docker/docker-compose.yml: Infrastructure setup")
        print("  - infra/docker/.env.example: Environment template")
        return 0

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
