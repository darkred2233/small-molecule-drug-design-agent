import argparse
import json
from pathlib import Path

from medagent.core.config import Settings
from medagent.services.database import initialize_database, initialize_sqlite_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(prog="medagent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    db_parser = subparsers.add_parser("db")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)

    init_parser = db_subparsers.add_parser("init")
    init_parser.add_argument("--database-url", default=None)

    snapshot_parser = db_subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--output", default="database/medagent_seed.sqlite")

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

    parser.error("Unsupported command")


if __name__ == "__main__":
    main()
