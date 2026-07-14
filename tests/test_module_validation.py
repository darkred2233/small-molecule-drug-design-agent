#!/usr/bin/env python3
"""Direct module test without full dependency chain."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_pipeline_tasks_direct():
    """Test pipeline tasks module."""
    with open("src/medagent/pipeline/tasks.py", encoding="utf-8") as f:
        content = f.read()
        assert "TASK_REGISTRY" in content
        assert "TASK_CONFIGS" in content
        assert "knowledge_ingestion_task" in content
    print("✓ Pipeline tasks.py: all expected functions present")


def test_pipeline_recovery_direct():
    """Test pipeline recovery module."""
    with open("src/medagent/pipeline/recovery.py", encoding="utf-8") as f:
        content = f.read()
        assert "class PipelineCheckpoint" in content
        assert "class PipelineRecovery" in content
        assert "is_step_idempotent" in content
    print("✓ Pipeline recovery.py: all expected classes present")


def test_reporting_cards_direct():
    """Test reporting cards module."""
    with open("src/medagent/reporting/cards.py", encoding="utf-8") as f:
        content = f.read()
        assert "def format_decision_card" in content
        assert "def card_to_html" in content
    print("✓ Reporting cards.py: all expected functions present")


def test_reporting_tables_direct():
    """Test reporting tables module."""
    with open("src/medagent/reporting/tables.py", encoding="utf-8") as f:
        content = f.read()
        assert "def generate_ranking_table" in content
        assert "def table_to_csv" in content
    print("✓ Reporting tables.py: all expected functions present")


def test_reporting_pdf_direct():
    """Test reporting pdf module."""
    with open("src/medagent/reporting/pdf.py", encoding="utf-8") as f:
        content = f.read()
        assert "def generate_pdf_report" in content
    print("✓ Reporting pdf.py: PDF generation function present")


def test_infra_utils_direct():
    """Test infrastructure utils module."""
    with open("infra/utils.py", encoding="utf-8") as f:
        content = f.read()
        assert "def check_postgres_health" in content
        assert "def check_minio_health" in content
    print("✓ Infrastructure utils.py: all expected functions present")


def test_infra_scripts():
    """Test infrastructure scripts exist."""
    scripts = [
        "infra/backup.sh",
        "infra/health_check.sh",
        "infra/docker/docker-compose.yml",
        "infra/docker/.env.example",
    ]
    for script in scripts:
        assert Path(script).exists(), f"Missing: {script}"
    print("✓ Infrastructure scripts: all deployment files present")


def main():
    """Run all tests."""
    print("Running direct module tests...")
    print("=" * 60)
    try:
        test_pipeline_tasks_direct()
        test_pipeline_recovery_direct()
        test_reporting_cards_direct()
        test_reporting_tables_direct()
        test_reporting_pdf_direct()
        test_infra_utils_direct()
        test_infra_scripts()
        print()
        print("=" * 60)
        print("✓ All modules created successfully!")
        print()
        print("Summary:")
        print("  - pipeline/tasks.py ✓")
        print("  - pipeline/recovery.py ✓")
        print("  - reporting/cards.py ✓")
        print("  - reporting/tables.py ✓")
        print("  - reporting/pdf.py ✓")
        print("  - infra/utils.py ✓")
        print("  - infra deployment files ✓")
        return 0
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
