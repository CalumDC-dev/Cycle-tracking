"""SQLite schema and low-level database helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB = Path("data/workout_tracker.sqlite")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS calibration_profiles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    length_scale REAL NOT NULL,
    distance_per_stroke REAL,
    mechanical_efficiency REAL NOT NULL DEFAULT 0.22,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resistance_scaling (
    id INTEGER PRIMARY KEY,
    resistance INTEGER NOT NULL UNIQUE,
    scaling REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS resistance_calibration_tests (
    id INTEGER PRIMARY KEY,
    tested_on TEXT NOT NULL,
    resistance INTEGER NOT NULL,
    duration_minutes REAL,
    device_watts REAL NOT NULL,
    expected_watts REAL NOT NULL,
    hr INTEGER,
    mass_kg REAL,
    calculated_scaling REAL NOT NULL,
    notes TEXT,
    source TEXT,
    source_activity_id TEXT,
    source_title TEXT,
    source_started_on TEXT,
    source_file TEXT,
    file_sha256 TEXT,
    raw_payload TEXT,
    quality_flags TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS met_lookup (
    id INTEGER PRIMARY KEY,
    hr_from INTEGER NOT NULL UNIQUE,
    effort TEXT NOT NULL,
    met REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mass_log (
    id INTEGER PRIMARY KEY,
    measured_on TEXT NOT NULL UNIQUE,
    mass_kg REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS circuits (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    length REAL NOT NULL,
    device_distance REAL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS raw_activities (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_activity_id TEXT,
    title TEXT,
    started_on TEXT,
    duration_seconds INTEGER,
    raw_distance REAL,
    hr INTEGER,
    raw_payload TEXT,
    review_status TEXT NOT NULL DEFAULT 'needs_review',
    session_type TEXT NOT NULL DEFAULT 'unknown',
    circuit_id INTEGER REFERENCES circuits(id),
    calibration_profile_id INTEGER REFERENCES calibration_profiles(id),
    classification_confidence REAL,
    classification_reason TEXT,
    duplicate_entry_type TEXT,
    duplicate_entry_id INTEGER,
    duplicate_confidence REAL,
    duplicate_reason TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, source_activity_id)
);

CREATE TABLE IF NOT EXISTS sprint_entries (
    id INTEGER PRIMARY KEY,
    performed_on TEXT NOT NULL,
    started_at TEXT,
    day_number INTEGER,
    sprint_index INTEGER,
    duration_minutes REAL,
    rpm REAL,
    device_watts REAL,
    hr INTEGER,
    resistance INTEGER,
    device_distance REAL,
    raw_activity_id INTEGER REFERENCES raw_activities(id),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS lap_entries (
    id INTEGER PRIMARY KEY,
    performed_on TEXT NOT NULL,
    started_at TEXT,
    lap_index INTEGER,
    circuit_id INTEGER REFERENCES circuits(id),
    lap_time_minutes REAL,
    hr INTEGER,
    resistance INTEGER,
    rpm REAL,
    raw_activity_id INTEGER REFERENCES raw_activities(id),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS duplicate_dismissals (
    id INTEGER PRIMARY KEY,
    entry_type TEXT NOT NULL,
    first_entry_id INTEGER NOT NULL,
    second_entry_id INTEGER NOT NULL,
    dismissed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entry_type, first_entry_id, second_entry_id)
);

CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sprint_rows INTEGER NOT NULL DEFAULT 0,
    lap_rows INTEGER NOT NULL DEFAULT 0,
    circuit_rows INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sprint_entries_performed_on ON sprint_entries(performed_on);
CREATE INDEX IF NOT EXISTS idx_lap_entries_performed_on ON lap_entries(performed_on);
CREATE INDEX IF NOT EXISTS idx_raw_activities_review_status ON raw_activities(review_status);
"""


def connect(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _apply_migrations(conn)
    conn.commit()


def reset_db(conn: sqlite3.Connection) -> None:
    tables = [
        "import_log",
        "duplicate_dismissals",
        "lap_entries",
        "sprint_entries",
        "raw_activities",
        "circuits",
        "mass_log",
        "met_lookup",
        "resistance_calibration_tests",
        "resistance_scaling",
        "calibration_profiles",
    ]
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in tables:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "calibration_profiles", "mechanical_efficiency", "REAL NOT NULL DEFAULT 0.22")
    _ensure_column(conn, "sprint_entries", "started_at", "TEXT")
    _ensure_column(conn, "lap_entries", "started_at", "TEXT")
    _ensure_column(conn, "raw_activities", "hr", "INTEGER")
    _ensure_column(conn, "raw_activities", "duplicate_entry_type", "TEXT")
    _ensure_column(conn, "raw_activities", "duplicate_entry_id", "INTEGER")
    _ensure_column(conn, "raw_activities", "duplicate_confidence", "REAL")
    _ensure_column(conn, "raw_activities", "duplicate_reason", "TEXT")
    _ensure_column(conn, "resistance_calibration_tests", "source", "TEXT")
    _ensure_column(conn, "resistance_calibration_tests", "source_activity_id", "TEXT")
    _ensure_column(conn, "resistance_calibration_tests", "source_title", "TEXT")
    _ensure_column(conn, "resistance_calibration_tests", "source_started_on", "TEXT")
    _ensure_column(conn, "resistance_calibration_tests", "source_file", "TEXT")
    _ensure_column(conn, "resistance_calibration_tests", "file_sha256", "TEXT")
    _ensure_column(conn, "resistance_calibration_tests", "raw_payload", "TEXT")
    _ensure_column(conn, "resistance_calibration_tests", "quality_flags", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
