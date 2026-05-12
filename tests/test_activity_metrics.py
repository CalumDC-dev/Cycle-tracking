import json
import sqlite3
import unittest

from workout_tracker.activity_metrics import ActivitySample, analyse_activity_samples, source_metric_rows
from workout_tracker.database import init_db


class ActivityMetricsTests(unittest.TestCase):
    def test_analyse_activity_samples_calculates_peaks_and_quality_flags(self):
        samples = [
            ActivitySample(elapsed_seconds=float(index), watts=100 + index * 10, cadence=80 + index, speed_mps=5.0)
            for index in range(10)
        ]

        metrics = analyse_activity_samples(samples, duration_seconds=10)

        self.assertEqual(metrics["analysis_version"], 1)
        self.assertEqual(metrics["sample_count"], 10)
        self.assertAlmostEqual(metrics["average_watts"], 145.0)
        self.assertAlmostEqual(metrics["best_5s_watts"], 170.0)
        self.assertAlmostEqual(metrics["best_5s_cadence"], 87.0)
        self.assertIn("missing_source_hr", metrics["data_quality_flags"])

    def test_source_metric_rows_flattens_payload_for_export_and_dashboard(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute("INSERT INTO resistance_scaling (resistance, scaling) VALUES (?, ?)", (4, 0.2))
        conn.execute(
            """
            INSERT INTO raw_activities (
                source, source_activity_id, title, started_on, duration_seconds,
                raw_distance, hr, review_status, session_type, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "strava",
                "abc",
                "Kinomap",
                "2026-05-12T08:00:00",
                300,
                8.0,
                128,
                "already_logged",
                "sprint",
                json.dumps(
                    {
                        "average_watts": 250,
                        "best_300s_watts": 245,
                        "average_cadence": 120,
                        "data_quality_flags": ["missing_source_hr"],
                    }
                ),
            ),
        )

        rows = source_metric_rows(conn)
        conn.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_activity_id"], "abc")
        self.assertEqual(rows[0]["resistance"], 4)
        self.assertEqual(rows[0]["average_watts"], 50)
        self.assertEqual(rows[0]["best_300s_watts"], 49)
        self.assertEqual(rows[0]["device_average_watts"], 250)
        self.assertEqual(rows[0]["data_quality_flags"], "missing_source_hr")


if __name__ == "__main__":
    unittest.main()
