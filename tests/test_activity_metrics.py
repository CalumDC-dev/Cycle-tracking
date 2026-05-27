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

    def test_analyse_activity_samples_trims_trailing_inactive_time(self):
        samples = [
            ActivitySample(elapsed_seconds=0, watts=200, cadence=80, speed_mps=5.0, hr=120),
            ActivitySample(elapsed_seconds=60, watts=210, cadence=82, speed_mps=5.1, hr=122),
            ActivitySample(elapsed_seconds=300, watts=215, cadence=83, speed_mps=5.2, hr=123),
            ActivitySample(elapsed_seconds=301, watts=0, cadence=0, speed_mps=0, hr=118),
            ActivitySample(elapsed_seconds=420, watts=0, cadence=0, speed_mps=0, hr=112),
        ]

        metrics = analyse_activity_samples(samples, duration_seconds=420)

        self.assertEqual(metrics["sample_count"], 3)
        self.assertEqual(metrics["raw_sample_count"], 5)
        self.assertEqual(metrics["trimmed_sample_count"], 2)
        self.assertAlmostEqual(metrics["active_duration_seconds"], 301)
        self.assertAlmostEqual(metrics["trailing_inactive_trim_seconds"], 119)
        self.assertAlmostEqual(metrics["average_watts"], 208.3333333333)
        self.assertAlmostEqual(metrics["average_source_hr"], 121.6666666667)
        self.assertIn("trailing_inactive_trimmed", metrics["data_quality_flags"])

    def test_analyse_activity_samples_ignores_sustained_low_hr_dropout_during_effort(self):
        samples = [
            ActivitySample(elapsed_seconds=float(index), watts=240, cadence=95, speed_mps=9.0, hr=118)
            for index in range(30)
        ]
        samples.extend(
            ActivitySample(elapsed_seconds=float(index), watts=275, cadence=105, speed_mps=11.0, hr=65)
            for index in range(30, 70)
        )
        samples.extend(
            ActivitySample(elapsed_seconds=float(index), watts=300, cadence=115, speed_mps=12.0, hr=126)
            for index in range(70, 100)
        )

        metrics = analyse_activity_samples(samples, duration_seconds=100)

        self.assertAlmostEqual(metrics["average_raw_source_hr"], 99.2)
        self.assertAlmostEqual(metrics["average_source_hr"], 122.0)
        self.assertEqual(metrics["min_source_hr"], 118)
        self.assertEqual(metrics["hr_dropout_sample_count"], 40)
        self.assertAlmostEqual(metrics["hr_dropout_seconds"], 40)
        self.assertIn("hr_dropout_suspected", metrics["data_quality_flags"])

    def test_analyse_activity_samples_keeps_short_low_hr_periods(self):
        samples = [
            ActivitySample(elapsed_seconds=float(index), watts=220, cadence=90, speed_mps=8.0, hr=65)
            for index in range(10)
        ]
        samples.extend(
            ActivitySample(elapsed_seconds=float(index), watts=240, cadence=95, speed_mps=9.0, hr=115)
            for index in range(10, 30)
        )

        metrics = analyse_activity_samples(samples, duration_seconds=30)

        self.assertAlmostEqual(metrics["average_source_hr"], 98.3333333333)
        self.assertNotIn("hr_dropout_suspected", metrics.get("data_quality_flags", []))

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
                        "average_source_hr": 122.5,
                        "average_raw_source_hr": 113.5,
                        "hr_dropout_seconds": 306,
                        "data_quality_flags": ["hr_dropout_suspected"],
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
        self.assertEqual(rows[0]["average_source_hr"], 122.5)
        self.assertEqual(rows[0]["average_raw_source_hr"], 113.5)
        self.assertEqual(rows[0]["hr_dropout_seconds"], 306)
        self.assertEqual(rows[0]["data_quality_flags"], "hr_dropout_suspected")

    def test_source_metric_rows_uses_interpolated_resistance_scaling(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.executemany(
            "INSERT INTO resistance_scaling (resistance, scaling) VALUES (?, ?)",
            [(1, 0.05), (4, 0.2)],
        )
        conn.execute(
            """
            INSERT INTO raw_activities (
                id, source, source_activity_id, title, started_on, review_status,
                session_type, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "strava",
                "interp",
                "Interpolated source",
                "2026-05-12T08:00:00",
                "already_logged",
                "sprint",
                json.dumps({"average_watts": 300}),
            ),
        )
        conn.execute(
            """
            INSERT INTO sprint_entries (performed_on, resistance, raw_activity_id)
            VALUES ('2026-05-12', 2, 1)
            """
        )
        conn.commit()

        rows = source_metric_rows(conn)
        conn.close()

        self.assertEqual(rows[0]["resistance"], 2)
        self.assertAlmostEqual(rows[0]["average_watts"], 30.0)


if __name__ == "__main__":
    unittest.main()
