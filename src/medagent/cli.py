import argparse
import json
from pathlib import Path

from medagent.core.config import Settings
from medagent.db.models import Base, Project
from medagent.db.session import build_session_factory
from medagent.services.bootstrap import seed_builtin_targets
from medagent.services.database import ensure_relational_schema, initialize_database, initialize_sqlite_snapshot
from medagent.services.ids import new_id
from medagent.services.rag import build_project_rag_index, crawl_project_urls, query_project_rag


def main() -> None:
    parser = argparse.ArgumentParser(prog="medagent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    db_parser = subparsers.add_parser("db")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)

    init_parser = db_subparsers.add_parser("init")
    init_parser.add_argument("--database-url", default=None)

    snapshot_parser = db_subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--output", default="database/medagent_seed.sqlite")

    rag_parser = subparsers.add_parser("rag")
    rag_subparsers = rag_parser.add_subparsers(dest="rag_command", required=True)

    rag_build_parser = rag_subparsers.add_parser("build")
    rag_build_parser.add_argument("--project-id", required=True)
    rag_build_parser.add_argument("--database-url", default=None)
    rag_build_parser.add_argument("--skip-builtin-target", action="store_true")
    rag_build_parser.add_argument("--skip-uploads", action="store_true")
    rag_build_parser.add_argument("--file-id", action="append", default=None)
    rag_build_parser.add_argument("--no-rebuild", action="store_true")

    rag_crawl_parser = rag_subparsers.add_parser("crawl")
    rag_crawl_parser.add_argument("--project-id", required=True)
    rag_crawl_parser.add_argument("--url", action="append", required=True)
    rag_crawl_parser.add_argument("--document-type", default="web")
    rag_crawl_parser.add_argument("--database-url", default=None)
    rag_crawl_parser.add_argument("--no-rebuild", action="store_true")

    rag_query_parser = rag_subparsers.add_parser("query")
    rag_query_parser.add_argument("--project-id", required=True)
    rag_query_parser.add_argument("--query", required=True)
    rag_query_parser.add_argument("--query-type", default="general")
    rag_query_parser.add_argument("--top-k", type=int, default=10)
    rag_query_parser.add_argument("--molecule-id", default=None)
    rag_query_parser.add_argument("--database-url", default=None)
    rag_query_parser.add_argument("--no-evidence", action="store_true")

    rag_collect_parser = rag_subparsers.add_parser("collect")
    rag_collect_parser.add_argument("--project-id", required=True)
    rag_collect_parser.add_argument("--database-url", default=None)
    rag_collect_parser.add_argument("--query", required=True)
    rag_collect_parser.add_argument("--query-type", default="general")
    rag_collect_parser.add_argument("--top-k", type=int, default=10)
    rag_collect_parser.add_argument("--molecule-id", default=None)
    rag_collect_parser.add_argument("--no-evidence", action="store_true")

    args = parser.parse_args()

    if args.command == "db" and args.db_command == "init":
        settings = Settings(database_url=args.database_url) if args.database_url else Settings()
        summary = initialize_database(settings)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "db" and args.db_command == "snapshot":
        summary = initialize_sqlite_snapshot(Path(args.output))
        print(json.dumps({"output": args.output, **summary}, ensure_ascii=False, indent=2))
        return

    if args.command == "rag":
        settings = Settings(database_url=args.database_url) if args.database_url else Settings()
        session_factory = build_session_factory(settings)
        engine = session_factory.kw["bind"]
        Base.metadata.create_all(bind=engine)
        ensure_relational_schema(engine)
        with session_factory() as db:
            seed_builtin_targets(db)
            project = db.query(Project).filter_by(project_id=args.project_id).one_or_none()
            if project is None:
                parser.error(f"Project not found: {args.project_id}")

            if args.rag_command == "build":
                output = build_project_rag_index(
                    db,
                    settings,
                    project,
                    include_builtin_target=not args.skip_builtin_target,
                    include_uploads=not args.skip_uploads,
                    file_ids=args.file_id,
                    rebuild=not args.no_rebuild,
                )
            elif args.rag_command == "crawl":
                output = crawl_project_urls(
                    db,
                    settings,
                    project,
                    urls=args.url,
                    document_type=args.document_type,
                    rebuild=not args.no_rebuild,
                )
            elif args.rag_command == "query":
                output = query_project_rag(
                    db,
                    settings,
                    project,
                    query=args.query,
                    query_type=args.query_type,
                    top_k=args.top_k,
                    molecule_id=args.molecule_id,
                    create_evidence=not args.no_evidence,
                )
            elif args.rag_command == "collect":
                from medagent.services.rag_collection import collect_and_index_project_packs
                output = collect_and_index_project_packs(db, settings, project)
                run = {
                    "agent_run_id": new_id("RUN"),
                    "agent_name": "rag_collection_agent",
                    "model_name": settings.embedding_model,
                    "status": "completed",
                    "input_json": {"query": args.query, "query_type": args.query_type, "top_k": args.top_k},
                    "output_json": output,
                }
                from medagent.db.models import AgentRun
                db.add(AgentRun(project_id=project.project_id, **run))
                db.commit()
                output = {"agent_run_id": run["agent_run_id"], "status": run["status"], **output}
            else:
                parser.error("Unsupported rag command")
            print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    parser.error("Unsupported command")


if __name__ == "__main__":
    main()
