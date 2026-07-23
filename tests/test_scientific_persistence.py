from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from medagent.db.models import Base, Project, Target, TargetResourcePackage
from medagent.services.database import ensure_relational_schema
from medagent.services.target_resource_packages import seed_golden_target_resource_packages
from medagent.services.scientific_workflow import prepare_round_preflight
from migrations.add_scientific_execution_tables import apply_migration


def test_scientific_migration_upgrades_binding_sites_and_creates_audit_tables(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE binding_sites ("
                "id INTEGER PRIMARY KEY, binding_site_id VARCHAR(80), target_id VARCHAR(80))"
            )
        )

    result = apply_migration(database_url)

    assert "scientific_artifacts" in result["created_tables"]
    assert "execution_manifests" in result["created_tables"]
    columns = {column["name"] for column in inspect(engine).get_columns("binding_sites")}
    assert {"structure_id", "reference_ligand_id", "validation_status", "artifact_id"} <= columns


def test_golden_target_resource_registry_contains_the_ten_requested_targets(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'resources.db'}")
    Base.metadata.create_all(engine)
    ensure_relational_schema(engine)

    from sqlalchemy.orm import Session

    with Session(engine) as db:
        for target_id in (
            "TGT-EGFR", "TGT-BRAF", "TGT-ALK", "TGT-MET", "TGT-JAK2",
            "TGT-BTK", "TGT-PI3K", "TGT-PARP1", "TGT-KRAS-G12C", "TGT-HDAC6",
        ):
            db.add(Target(target_id=target_id, name=target_id, aliases=[], pdb_ids=[]))
        db.commit()

    with Session(engine) as db:
        summary = seed_golden_target_resource_packages(db)
        db.commit()
        packages = db.query(TargetResourcePackage).all()

    assert summary["target_count"] == 10
    assert len(packages) == 10
    egfr = next(package for package in packages if package.target_id == "TGT-EGFR")
    assert egfr.uniprot_accession == "P00533"
    assert egfr.status == "metadata_ready"


def test_preflight_freezes_capabilities_and_blocks_unprepared_structural_stages(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'preflight.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(project_id="PROJ-EGFR", name="EGFR", target_id="TGT-EGFR")
        db.add(project)
        db.flush()
        preflight = prepare_round_preflight(
            db,
            project,
            formal_round=True,
            tool_capabilities={
                "crem": {"available": True},
                "targetdiff": {"available": True},
                "autogrow4": {"available": True},
                "vina": {"available": True},
                "gnina": {"available": True},
                "admet_ai": {"available": True},
                "aizynthfinder": {"available": True, "model_configured": True},
                "rdkit": {"available": True},
            },
        )

    stages = {item["stage"]: item for item in preflight["plan"]["stages"]}
    assert preflight["plan"]["formal_round_allowed"] is True
    assert stages["vina_screen"]["allowed"] is False
    assert "verified_pocket_required" in stages["vina_screen"]["reason_codes"]
    assert preflight["target_resource_packet_id"].startswith("PACKET-")
