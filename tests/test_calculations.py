import sqlite3
import unittest

from workout_tracker.calculations import (
    best_laps_by_circuit,
    calculated_laps,
    calculated_sprints,
    daily_summary,
    dashboard_metrics,
    suggest_activity_classification,
)
from workout_tracker.database import init_db


class CalculationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self._seed()

    def tearDown(self):
        self.conn.close()

    def test_sprint_calculations_apply_resistance_and_distance_scaling(self):
        sprint = calculated_sprints(self.conn)[0]

        self.assertEqual(sprint.performed_on, "2026-05-01")
        self.assertAlmostEqual(sprint.estimated_watts, 45.0)
        self.assertAlmostEqual(sprint.calibrated_distance, 4.5)
        self.assertAlmostEqual(sprint.calories_watts, 27.0)
        self.assertAlmostEqual(sprint.calories_mets, 37.3333333333)

    def test_lap_calculations_apply_circuit_length_and_met_lookup(self):
        lap = calculated_laps(self.conn)[0]

        self.assertEqual(lap.circuit_name, "Test Circuit")
        self.assertAlmostEqual(lap.average_speed, 30.0)
        self.assertAlmostEqual(lap.calories_mets, 12.8)

    def test_daily_summary_combines_sprint_and_lap_outputs(self):
        summary = daily_summary(self.conn)

        self.assertEqual(len(summary), 1)
        row = summary[0]
        self.assertEqual(row["sprint_count"], 1)
        self.assertEqual(row["lap_count"], 1)
        self.assertAlmostEqual(row["total_distance"], 6.0)
        self.assertAlmostEqual(row["total_calories"], 39.8)
        self.assertAlmostEqual(row["average_watts"], 45.0)
        self.assertAlmostEqual(row["average_rpm"], 115.0)

    def test_dashboard_metrics_report_best_lap_and_mass_change(self):
        metrics = dashboard_metrics(self.conn)

        self.assertEqual(metrics["workout_days"], 1)
        self.assertEqual(metrics["sprint_count"], 1)
        self.assertEqual(metrics["lap_count"], 1)
        self.assertAlmostEqual(metrics["best_lap_minutes"], 3.0)
        self.assertEqual(metrics["best_lap_circuit"], "Test Circuit")
        self.assertEqual(metrics["best_laps_by_circuit"][0]["circuit_name"], "Test Circuit")
        self.assertAlmostEqual(metrics["mass_change"], -1.0)

    def test_best_laps_by_circuit_keeps_each_circuit_separate(self):
        self.conn.execute(
            """
            INSERT INTO circuits (id, name, length, device_distance)
            VALUES (2, 'Short Circuit', 0.5, 1.1111111111)
            """
        )
        self.conn.executemany(
            """
            INSERT INTO lap_entries (
                performed_on, lap_index, circuit_id, lap_time_minutes,
                hr, resistance, rpm
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-05-02", 1, 1, 2.5, 130, 4, 112),
                ("2026-05-02", 1, 2, 1.0, 130, 4, 112),
            ],
        )
        self.conn.commit()

        leaderboard = best_laps_by_circuit(conn=self.conn)

        self.assertEqual([row["circuit_name"] for row in leaderboard], ["Short Circuit", "Test Circuit"])
        self.assertAlmostEqual(leaderboard[0]["lap_time_minutes"], 1.0)
        self.assertAlmostEqual(leaderboard[1]["lap_time_minutes"], 2.5)

    def test_classifier_suggests_lap_when_raw_distance_matches_circuit_target(self):
        suggestion = suggest_activity_classification(self.conn, 3.31)

        self.assertEqual(suggestion["session_type"], "lap")
        self.assertEqual(suggestion["circuit_id"], 1)
        self.assertGreater(suggestion["confidence"], 0.99)

    def test_classifier_leaves_non_matching_distance_for_review(self):
        suggestion = suggest_activity_classification(self.conn, 20.0)

        self.assertEqual(suggestion["session_type"], "unknown")
        self.assertEqual(suggestion["confidence"], 0.0)

    def _seed(self):
        self.conn.execute(
            """
            INSERT INTO calibration_profiles (id, name, length_scale, distance_per_stroke, active)
            VALUES (1, 'Test profile', 0.45, 2.5, 1)
            """
        )
        self.conn.execute(
            "INSERT INTO resistance_scaling (resistance, scaling) VALUES (?, ?)",
            (4, 0.15),
        )
        self.conn.executemany(
            "INSERT INTO met_lookup (hr_from, effort, met) VALUES (?, ?, ?)",
            [
                (120, "Moderate", 2.8),
                (130, "Moderate+", 3.2),
            ],
        )
        self.conn.executemany(
            "INSERT INTO mass_log (measured_on, mass_kg) VALUES (?, ?)",
            [
                ("2026-04-01", 81.0),
                ("2026-05-01", 80.0),
            ],
        )
        self.conn.execute(
            """
            INSERT INTO circuits (id, name, length, device_distance)
            VALUES (1, 'Test Circuit', 1.5, 3.3333333333)
            """
        )
        self.conn.execute(
            """
            INSERT INTO sprint_entries (
                performed_on, day_number, sprint_index, duration_minutes,
                rpm, device_watts, hr, resistance, device_distance
            )
            VALUES ('2026-05-01', 1, 1, 10, 120, 300, 120, 4, 10)
            """
        )
        self.conn.execute(
            """
            INSERT INTO lap_entries (
                performed_on, lap_index, circuit_id, lap_time_minutes,
                hr, resistance, rpm
            )
            VALUES ('2026-05-01', 1, 1, 3, 130, 4, 110)
            """
        )
        self.conn.commit()


if __name__ == "__main__":
    unittest.main()
