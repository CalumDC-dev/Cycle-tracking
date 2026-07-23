import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from workout_tracker.database import init_db
from workout_tracker.exporter import backup_bundle_bytes, export_all


class ExporterTests(unittest.TestCase):
    def test_export_all_writes_source_metrics_csv(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute(
            """
            INSERT INTO calibration_profiles (id, name, length_scale, active)
            VALUES (1, 'Test profile', 0.5, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO raw_activities (
                source, source_activity_id, title, started_on, review_status,
                session_type, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "strava",
                "abc",
                "Kinomap",
                "2026-05-12T08:00:00",
                "already_logged",
                "sprint",
                json.dumps(
                    {
                        "average_watts": 250,
                        "best_300s_watts": 240,
                        "source_hr_basis": "record_samples",
                        "average_source_hr": 122.5,
                        "average_active_source_hr": 123.0,
                        "average_raw_source_hr": 113.5,
                        "source_hr_coverage_pct": 80,
                        "hr_dropout_seconds": 306,
                        "data_quality_flags": ["hr_dropout_suspected"],
                    }
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            files = export_all(conn, temp_dir)
            source_file = Path(temp_dir) / "source_metrics.csv"
            text = source_file.read_text(encoding="utf-8")

        conn.close()

        self.assertIn(source_file, files)
        self.assertIn("average_watts", text)
        self.assertIn("source_hr_basis", text)
        self.assertIn("average_active_source_hr", text)
        self.assertIn("average_raw_source_hr", text)
        self.assertIn("source_hr_coverage_pct", text)
        self.assertIn("hr_dropout_seconds", text)
        self.assertIn("hr_dropout_suspected", text)
        self.assertIn("250", text)

    def test_backup_bundle_includes_sqlite_snapshot_and_core_csvs(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute(
            """
            INSERT INTO calibration_profiles (id, name, length_scale, active)
            VALUES (1, 'Test profile', 0.5, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO sprint_entries (performed_on, sprint_index, duration_minutes)
            VALUES ('2026-05-12', 1, 5)
            """
        )
        conn.execute(
            """
            INSERT INTO challenge_progress (challenge_key, updated_on, team_miles)
            VALUES ('uk_coastline', '2026-06-08', 5300)
            """
        )
        conn.commit()

        bundle = backup_bundle_bytes(conn)

        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_path = Path(temp_dir) / "backup.zip"
            bundle_path.write_bytes(bundle)
            with ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                sqlite_path = Path(temp_dir) / "workout_tracker.sqlite"
                sqlite_path.write_bytes(archive.read("workout_tracker.sqlite"))
                sprint_csv = archive.read("data/sprint_entries.csv").decode("utf-8")
                challenge_csv = archive.read("data/challenge_progress.csv").decode("utf-8")

            snapshot = sqlite3.connect(sqlite_path)
            try:
                sprint_count = snapshot.execute("SELECT COUNT(*) FROM sprint_entries").fetchone()[0]
            finally:
                snapshot.close()
        conn.close()

        self.assertEqual(manifest["format"], "workout-tracker-backup")
        self.assertIn("reports/daily_summary.csv", names)
        self.assertIn("data/resistance_scaling.csv", names)
        self.assertIn("data/challenge_progress.csv", names)
        self.assertIn("2026-05-12", sprint_csv)
        self.assertIn("uk_coastline", challenge_csv)
        self.assertEqual(sprint_count, 1)


if __name__ == "__main__":
    unittest.main()
