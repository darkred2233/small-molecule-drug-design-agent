from pathlib import Path

from sqlalchemy import func, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
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
    table_names = set(inspector.get_table_names())

    if "target_drug_library" in table_names:
        _ensure_missing_columns(
            engine,
            "target_drug_library",
            _target_drug_library_columns(engine.dialect.name),
        )

    if "binding_sites" in table_names:
        _ensure_missing_columns(
            engine,
            "binding_sites",
            _binding_site_columns(engine.dialect.name),
        )

    if "rankings" in table_names:
        _ensure_missing_columns(
            engine,
            "rankings",
            _ranking_columns(),
        )

    if "critiques" in table_names:
        _ensure_missing_columns(
            engine,
            "critiques",
            _critique_columns(),
        )

    if "advisor_suggestions" in table_names:
        _ensure_missing_columns(
            engine,
            "advisor_suggestions",
            _advisor_suggestion_columns(engine.dialect.name),
        )

    if "rag_chunks" in table_names:
        _ensure_missing_columns(
            engine,
            "rag_chunks",
            _rag_chunk_columns(engine.dialect.name),
        )
        if engine.dialect.name == "postgresql":
            _ensure_pgvector_columns(engine)


def _ensure_missing_columns(
    engine: Engine,
    table_name: str,
    column_specs: list[tuple[str, str]],
) -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing_columns = [
        (name, column_type)
        for name, column_type in column_specs
        if name not in existing_columns
    ]
    if not missing_columns:
        return

    with engine.begin() as connection:
        for name, column_type in missing_columns:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {column_type}"))


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


def _binding_site_columns(dialect_name: str) -> list[tuple[str, str]]:
    json_type = "JSONB DEFAULT '{}'::jsonb" if dialect_name == "postgresql" else "JSON DEFAULT '{}'"
    return [
        ("project_id", "VARCHAR(80)"),
        ("source_file_id", "VARCHAR(80)"),
        ("receptor_file", "TEXT"),
        ("prepared_receptor_file", "TEXT"),
        ("preparation_status", "VARCHAR(80) DEFAULT 'uploaded'"),
        ("preparation_json", json_type),
    ]


def _ranking_columns() -> list[tuple[str, str]]:
    return [("project_id", "VARCHAR(80)")]


def _critique_columns() -> list[tuple[str, str]]:
    return [("con_score", "FLOAT")]


def _advisor_suggestion_columns(dialect_name: str) -> list[tuple[str, str]]:
    json_list = "JSONB DEFAULT '[]'::jsonb" if dialect_name == "postgresql" else "JSON DEFAULT '[]'"
    json_dict = "JSONB DEFAULT '{}'::jsonb" if dialect_name == "postgresql" else "JSON DEFAULT '{}'"
    return [
        ("next_round_constraints", json_list),
        ("suggested_generation_config", json_dict),
    ]


def _rag_chunk_columns(dialect_name: str) -> list[tuple[str, str]]:
    json_type = "JSONB DEFAULT '[]'::jsonb" if dialect_name == "postgresql" else "JSON DEFAULT '[]'"
    metadata_type = "JSONB DEFAULT '{}'::jsonb" if dialect_name == "postgresql" else "JSON DEFAULT '{}'"
    return [
        ("embedding_json", json_type),
        ("token_count", "INTEGER"),
        ("metadata_json", metadata_type),
    ]


def _ensure_pgvector_columns(engine: Engine) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(text("ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS embedding_vector vector(2048)"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_vector "
                    "ON rag_chunks USING ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100)"
                )
            )
    except SQLAlchemyError:
        return
