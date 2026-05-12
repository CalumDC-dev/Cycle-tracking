import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from workout_tracker.database import init_db
from workout_tracker.exporter import export_all


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
                json.dumps({"average_watts": 250, "best_300s_watts": 240}),
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            files = export_all(conn, temp_dir)
            source_file = Path(temp_dir) / "source_metrics.csv"
            text = source_file.read_text(encoding="utf-8")

        conn.close()

        self.assertIn(source_file, files)
        self.assertIn("average_watts", text)
        self.assertIn("250", text)


if __name__ == "__main__":
    unittest.main()
