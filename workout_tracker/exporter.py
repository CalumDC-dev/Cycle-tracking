"""CSV export helpers."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterable
from zipfile import ZIP_DEFLATED, ZipFile

from .activity_metrics import source_metric_rows
from .calculations import calculated_laps, calculated_sprints, daily_summary

BACKUP_TABLES = [
    "calibration_profiles",
    "resistance_scaling",
    "resistance_calibration_tests",
    "met_lookup",
    "mass_log",
    "circuits",
    "raw_activities",
    "sprint_entries",
    "lap_entries",
    "import_log",
]


def export_all(conn: sqlite3.Connection, out_dir: str | Path = "exports") -> list[Path]:
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    files = [
        _write_dicts(output / "daily_summary.csv", daily_summary(conn)),
        _write_dicts(output / "sprints.csv", [sprint.__dict__ for sprint in calculated_sprints(conn)]),
        _write_dicts(output / "laps.csv", [lap.__dict__ for lap in calculated_laps(conn)]),
        _write_dicts(output / "source_metrics.csv", source_metric_rows(conn)),
        _write_query(conn, output / "circuits.csv", "SELECT * FROM circuits ORDER BY name"),
        _write_query(conn, output / "raw_activities.csv", "SELECT * FROM raw_activities ORDER BY imported_at DESC, id DESC"),
    ]
    return files


def backup_bundle_bytes(conn: sqlite3.Connection) -> bytes:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "generated_at": generated_at,
                    "format": "workout-tracker-backup",
                    "version": 1,
                    "sqlite_snapshot": "workout_tracker.sqlite",
                    "data_tables": [f"data/{table}.csv" for table in BACKUP_TABLES],
                    "reports": [
                        "reports/daily_summary.csv",
                        "reports/sprints.csv",
                        "reports/laps.csv",
                        "reports/source_metrics.csv",
                    ],
                },
                indent=2,
            )
            + "\n",
        )
        archive.writestr("workout_tracker.sqlite", sqlite_snapshot_bytes(conn))
        for table in BACKUP_TABLES:
            archive.writestr(f"data/{table}.csv", table_csv_text(conn, table))
        archive.writestr("reports/daily_summary.csv", csv_text(daily_summary(conn)))
        archive.writestr("reports/sprints.csv", csv_text([sprint.__dict__ for sprint in calculated_sprints(conn)]))
        archive.writestr("reports/laps.csv", csv_text([lap.__dict__ for lap in calculated_laps(conn)]))
        archive.writestr("reports/source_metrics.csv", csv_text(source_metric_rows(conn)))
    return buffer.getvalue()


def backup_filename(now: datetime | None = None) -> str:
    current = now or datetime.now()
    return f"workout-tracker-backup-{current:%Y%m%d-%H%M%S}.zip"


def sqlite_snapshot_bytes(conn: sqlite3.Connection) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as handle:
        path = Path(handle.name)
    try:
        snapshot = sqlite3.connect(path)
        try:
            conn.backup(snapshot)
        finally:
            snapshot.close()
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def table_csv_text(conn: sqlite3.Connection, table_name: str) -> str:
    if table_name not in BACKUP_TABLES:
        raise ValueError(f"Table is not part of the backup set: {table_name}")
    rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table_name} ORDER BY id").fetchall()]
    return csv_text(rows)


def csv_text(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _write_dicts(path: Path, rows: list[dict[str, object]]) -> Path:
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_query(conn: sqlite3.Connection, path: Path, query: str) -> Path:
    rows = [dict(row) for row in conn.execute(query).fetchall()]
    return _write_dicts(path, rows)
