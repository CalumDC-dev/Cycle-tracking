"""Command line entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from .activity_import import load_activity_file
from .database import DEFAULT_DB, connect, init_db, reset_db
from .exporter import export_all
from .import_workbook import import_workbook
from .web import add_raw_activity, serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="workout-tracker")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Create database tables")
    init_parser.add_argument("--reset", action="store_true", help="Drop existing app tables first")

    import_parser = subparsers.add_parser("import-workbook", help="Import workbook data")
    import_parser.add_argument("workbook", help="Path to Workout tracking.xlsx")
    import_parser.add_argument("--reset", action="store_true", help="Drop existing app tables first")

    activity_parser = subparsers.add_parser("import-activities", help="Import raw activity files into review")
    activity_parser.add_argument("activity_file", help="Path to a CSV, JSON, TCX, FIT, ZIP, or directory of exports")
    activity_parser.add_argument("--source", default="strava", help="Source label for imported rows")

    serve_parser = subparsers.add_parser("serve", help="Run the local web UI")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    export_parser = subparsers.add_parser("export", help="Export CSV reports")
    export_parser.add_argument("--out", default="exports")

    args = parser.parse_args()
    db_path = Path(args.db)
    conn = connect(db_path)

    if args.command == "init-db":
        if args.reset:
            reset_db(conn)
        else:
            init_db(conn)
        print(f"Database ready: {db_path}")
    elif args.command == "import-workbook":
        stats = import_workbook(args.workbook, conn, reset=args.reset)
        print(f"Imported workbook into {db_path}")
        for key, value in stats.items():
            print(f"{key}: {value}")
    elif args.command == "import-activities":
        init_db(conn)
        rows = load_activity_file(args.activity_file, args.source)
        imported = 0
        for row in rows:
            add_raw_activity(conn, row)
            imported += 1
        print(f"Imported {imported} raw activities into {db_path}")
    elif args.command == "serve":
        init_db(conn)
        conn.close()
        serve(db_path, args.host, args.port)
    elif args.command == "export":
        init_db(conn)
        files = export_all(conn, args.out)
        for file in files:
            print(file)


if __name__ == "__main__":
    main()
