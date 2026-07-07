from pathlib import Path

from sqlalchemy import func, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import Base, Molecule, Project, Target, TargetDrugLibrary
from medagent.db.session import build_engine, build_session_factory
from medagent.services.bootstrap import seed_builtin_targets


def initialize_database(settings: Settings) -> dict:
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    ensure_relational_schema(engine)
    session_factory = build_session_factory(settings)
    with session_factory() as db:
        seed_builtin_targets(db)
        return database_summary(db)


def initialize_sqlite_snapshot(output_path: Path) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    return initialize_database(Settings(database_url=f"sqlite:///{output_path}"))


def database_summary(db: Session) -> dict:
    target_ids = [row[0] for row in db.query(Target.target_id).order_by(Target.target_id).all()]
    return {
        "target_count": db.scalar(func.count(Target.id)) or 0,
        "drug_count": db.scalar(func.count(TargetDrugLibrary.id)) or 0,
        "project_count": db.scalar(func.count(Project.id)) or 0,
        "molecule_count": db.scalar(func.count(Molecule.id)) or 0,
        "target_ids": target_ids,
    }


def ensure_relational_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    if "target_drug_library" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("target_drug_library")}
    missing_columns = [
        (name, column_type)
        for name, column_type in _target_drug_library_columns(engine.dialect.name)
        if name not in existing_columns
    ]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for name, column_type in missing_columns:
            connection.execute(text(f"ALTER TABLE target_drug_library ADD COLUMN {name} {column_type}"))


def _target_drug_library_columns(dialect_name: str) -> list[tuple[str, str]]:
    if dialect_name == "postgresql":
        return [
            ("canonical_smiles", "TEXT"),
            ("isomeric_smiles", "TEXT"),
            ("inchi_key", "VARCHAR(120)"),
            ("pubchem_cid", "INTEGER"),
            ("external_refs", "JSONB DEFAULT '{}'::jsonb"),
        ]
    return [
        ("canonical_smiles", "TEXT"),
        ("isomeric_smiles", "TEXT"),
        ("inchi_key", "VARCHAR(120)"),
        ("pubchem_cid", "INTEGER"),
        ("external_refs", "JSON DEFAULT '{}'"),
    ]
