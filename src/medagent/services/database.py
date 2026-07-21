import logging
from pathlib import Path

from sqlalchemy import func, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import Base, Molecule, Project, Target, TargetDrugLibrary
from medagent.db.session import build_engine, build_session_factory
from medagent.services.bootstrap import seed_builtin_targets

logger = logging.getLogger(__name__)

RAG_EMBEDDING_DIMENSIONS = 2048
PGVECTOR_IVFFLAT_MAX_DIMENSIONS = 2000


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

    if "seed_ligands" in table_names:
        _ensure_missing_columns(
            engine,
            "seed_ligands",
            [("activity_type", "VARCHAR(40)")],
        )

    if "rankings" in table_names:
        _ensure_missing_columns(
            engine,
            "rankings",
            _ranking_columns(),
        )

    if "docking_results" in table_names:
        _ensure_missing_columns(
            engine,
            "docking_results",
            _docking_result_columns(engine.dialect.name),
        )

    if "critiques" in table_names:
        _ensure_missing_columns(
            engine,
            "critiques",
            _critique_columns(engine.dialect.name),
        )

    if "advisor_suggestions" in table_names:
        _ensure_missing_columns(
            engine,
            "advisor_suggestions",
            _advisor_suggestion_columns(engine.dialect.name),
        )

    if "project_rounds" in table_names:
        _ensure_missing_columns(
            engine,
            "project_rounds",
            _project_round_columns(engine.dialect.name),
        )
        _migrate_round_execution_config_snapshot(engine)

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


def _docking_result_columns(dialect_name: str) -> list[tuple[str, str]]:
    json_type = "JSONB DEFAULT '{}'::jsonb" if dialect_name == "postgresql" else "JSON DEFAULT '{}'"
    return [
        ("diffdock_confidence", "FLOAT"),
        ("raw_output", json_type),
    ]


def _critique_columns(dialect_name: str) -> list[tuple[str, str]]:
    json_type = "JSONB DEFAULT NULL" if dialect_name == "postgresql" else "JSON DEFAULT NULL"
    return [
        ("con_score", "FLOAT"),
        ("llm_critique_json", json_type),
        ("llm_provider", "VARCHAR(80)"),
        ("analysis_method", "VARCHAR(80) DEFAULT 'heuristic_self_refutation'"),
    ]


def _advisor_suggestion_columns(dialect_name: str) -> list[tuple[str, str]]:
    json_list = "JSONB DEFAULT '[]'::jsonb" if dialect_name == "postgresql" else "JSON DEFAULT '[]'"
    json_dict = "JSONB DEFAULT '{}'::jsonb" if dialect_name == "postgresql" else "JSON DEFAULT '{}'"
    return [
        ("next_round_constraints", json_list),
        ("suggested_generation_config", json_dict),
    ]


def _project_round_columns(dialect_name: str) -> list[tuple[str, str]]:
    json_type = "JSONB DEFAULT NULL" if dialect_name == "postgresql" else "JSON DEFAULT NULL"
    return [("execution_config_snapshot_json", json_type)]


def _migrate_round_execution_config_snapshot(engine: Engine) -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("project_rounds")}
    if "run_plan_snapshot_json" not in columns or "execution_config_snapshot_json" not in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE project_rounds "
                "SET execution_config_snapshot_json = run_plan_snapshot_json "
                "WHERE execution_config_snapshot_json IS NULL "
                "AND run_plan_snapshot_json IS NOT NULL"
            )
        )


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

        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE rag_chunks "
                    f"ADD COLUMN IF NOT EXISTS embedding_vector vector({RAG_EMBEDDING_DIMENSIONS})"
                )
            )

        if RAG_EMBEDDING_DIMENSIONS > PGVECTOR_IVFFLAT_MAX_DIMENSIONS:
            logger.info(
                "Skipping rag_chunks.embedding_vector IVFFlat index because pgvector "
                "limits IVFFlat vector dimensions to %s and the configured embedding "
                "dimension is %s.",
                PGVECTOR_IVFFLAT_MAX_DIMENSIONS,
                RAG_EMBEDDING_DIMENSIONS,
            )
            return

        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_vector "
                    "ON rag_chunks USING ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100)"
                )
            )
    except SQLAlchemyError:
        logger.exception("Failed to initialize pgvector columns for rag_chunks")
        raise
