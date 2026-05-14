import sqlite3
import unittest

from workout_tracker.database import init_db


class DatabaseMigrationTests(unittest.TestCase):
    def test_init_db_adds_sync_columns_to_existing_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE raw_activities (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                source_activity_id TEXT,
                title TEXT,
                started_on TEXT,
                duration_seconds INTEGER,
                raw_distance REAL,
                raw_payload TEXT,
                review_status TEXT NOT NULL DEFAULT 'needs_review',
                session_type TEXT NOT NULL DEFAULT 'unknown',
                circuit_id INTEGER,
                calibration_profile_id INTEGER,
                classification_confidence REAL,
                classification_reason TEXT,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, source_activity_id)
            );
            CREATE TABLE sprint_entries (
                id INTEGER PRIMARY KEY,
                performed_on TEXT NOT NULL,
                day_number INTEGER,
                sprint_index INTEGER,
                duration_minutes REAL,
                rpm REAL,
                device_watts REAL,
                hr INTEGER,
                resistance INTEGER,
                device_distance REAL,
                raw_activity_id INTEGER,
                notes TEXT
            );
            CREATE TABLE lap_entries (
                id INTEGER PRIMARY KEY,
                performed_on TEXT NOT NULL,
                lap_index INTEGER,
                circuit_id INTEGER,
                lap_time_minutes REAL,
                hr INTEGER,
                resistance INTEGER,
                rpm REAL,
                raw_activity_id INTEGER,
                notes TEXT
            );
            CREATE TABLE resistance_calibration_tests (
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        init_db(conn)

        raw_columns = self._columns(conn, "raw_activities")
        sprint_columns = self._columns(conn, "sprint_entries")
        lap_columns = self._columns(conn, "lap_entries")
        calibration_columns = self._columns(conn, "resistance_calibration_tests")
        self.assertIn("hr", raw_columns)
        self.assertIn("duplicate_entry_type", raw_columns)
        self.assertIn("duplicate_entry_id", raw_columns)
        self.assertIn("duplicate_confidence", raw_columns)
        self.assertIn("duplicate_reason", raw_columns)
        self.assertIn("mechanical_efficiency", self._columns(conn, "calibration_profiles"))
        self.assertIn("started_at", sprint_columns)
        self.assertIn("started_at", lap_columns)
        self.assertIn("source_activity_id", calibration_columns)
        self.assertIn("source_file", calibration_columns)
        self.assertIn("file_sha256", calibration_columns)
        self.assertIn("raw_payload", calibration_columns)
        self.assertIn("quality_flags", calibration_columns)
        self.assertTrue(self._table_exists(conn, "duplicate_dismissals"))
        conn.close()

    def _columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

    def _table_exists(self, conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone() is not None


if __name__ == "__main__":
    unittest.main()
