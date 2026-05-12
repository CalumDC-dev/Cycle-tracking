"""CSV export helpers."""

from __future__ import annotations

import csv
from pathlib import Path
import sqlite3
from typing import Iterable

from .activity_metrics import source_metric_rows
from .calculations import calculated_laps, calculated_sprints, daily_summary


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
