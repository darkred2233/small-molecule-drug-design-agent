from sqlalchemy import create_engine, inspect, text

from medagent.db.models import Base
from migrations.add_docking_diffdock_confidence import apply_migration as apply_diffdock_migration
from migrations.add_docking_raw_output import apply_migration
from migrations.add_seed_ligand_activity_type import (
    apply_migration as apply_seed_activity_type_migration,
)
from migrations.add_llm_critique_fields import (
    apply_migration as apply_critique_provenance_migration,
)
from migrations.add_round_provenance import apply_migration as apply_round_provenance_migration
from migrations.run_all import apply_all


def test_add_docking_raw_output_upgrades_existing_sqlite_table(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE docking_results ("
                "id INTEGER PRIMARY KEY, molecule_id VARCHAR(64), vina_score FLOAT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO docking_results (id, molecule_id, vina_score) "
                "VALUES (1, 'MOL-LEGACY', -7.1)"
            )
        )

    assert apply_migration(database_url) is True
    assert apply_migration(database_url) is False

    columns = {column["name"] for column in inspect(engine).get_columns("docking_results")}
    assert "raw_output" in columns
    with engine.connect() as connection:
        raw_output = connection.execute(
            text("SELECT raw_output FROM docking_results WHERE id = 1")
        ).scalar_one()
    assert raw_output == "{}"


def test_add_diffdock_confidence_upgrades_existing_sqlite_table(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy-diffdock.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE docking_results ("
                "id INTEGER PRIMARY KEY, molecule_id VARCHAR(64), cnn_score FLOAT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO docking_results (id, molecule_id, cnn_score) "
                "VALUES (1, 'MOL-LEGACY', 0.81)"
            )
        )

    assert apply_diffdock_migration(database_url) is True
    assert apply_diffdock_migration(database_url) is False

    columns = {column["name"] for column in inspect(engine).get_columns("docking_results")}
    assert "diffdock_confidence" in columns
    with engine.connect() as connection:
        values = connection.execute(
            text(
                "SELECT cnn_score, diffdock_confidence FROM docking_results "
                "WHERE id = 1"
            )
        ).one()
    assert values == (0.81, None)


def test_add_seed_ligand_activity_type_upgrades_existing_sqlite_table(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy-seeds.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE seed_ligands ("
                "id INTEGER PRIMARY KEY, ligand_id VARCHAR(80), activity_value FLOAT)"
            )
        )

    assert apply_seed_activity_type_migration(database_url) is True
    assert apply_seed_activity_type_migration(database_url) is False
    columns = {column["name"] for column in inspect(engine).get_columns("seed_ligands")}
    assert "activity_type" in columns


def test_add_critique_provenance_upgrades_existing_sqlite_table(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy-critiques.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE critiques ("
                "id INTEGER PRIMARY KEY, critique_id VARCHAR(80), reason TEXT)"
            )
        )

    assert apply_critique_provenance_migration(database_url) == [
        "llm_critique_json",
        "llm_provider",
        "analysis_method",
    ]
    assert apply_critique_provenance_migration(database_url) == []
    columns = {column["name"] for column in inspect(engine).get_columns("critiques")}
    assert {"llm_critique_json", "llm_provider", "analysis_method"} <= columns


def test_apply_all_is_idempotent_on_current_schema(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'current-schema.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)

    expected = {
        "docking_raw_output": False,
        "docking_diffdock_confidence": False,
        "seed_ligand_activity_type": False,
        "llm_critique_fields": [],
        "round_provenance": {"added_columns": [], "round_reports_created": False},
    }

    assert apply_all(database_url) == expected
    assert apply_all(database_url) == expected


def test_round_provenance_migration_adds_lineage_fields_and_report_table(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'round-provenance.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)

    result = apply_round_provenance_migration(database_url)
    assert result["added_columns"] == []
    assert result["round_reports_created"] is False
    columns = {column["name"] for column in inspect(engine).get_columns("molecules")}
    assert {
        "campaign_run_id",
        "generation_method",
        "parent_molecule_ids",
        "provenance_json",
        "generation_metadata_json",
    } <= columns
    assert inspect(engine).has_table("round_reports")
