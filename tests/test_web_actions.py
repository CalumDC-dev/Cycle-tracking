import sqlite3
import unittest

from workout_tracker.calculations import calculated_laps, calculated_sprints
from workout_tracker.database import init_db
from workout_tracker.web import (
    add_lap_entry,
    add_mass_log,
    add_resistance_calibration_test,
    add_sprint_entry,
    calculate_resistance_calibration_preview,
    circuit_rows_with_goals,
    editable_calibration_profile,
    add_circuit,
    update_circuit,
    update_calibration_profile,
    update_mass_log,
    update_resistance_scaling,
)


class WebActionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.conn.execute(
            """
            INSERT INTO calibration_profiles (id, name, length_scale, active)
            VALUES (1, 'Test profile', 0.5, 1)
            """
        )
        self.conn.execute(
            "INSERT INTO resistance_scaling (resistance, scaling) VALUES (?, ?)",
            (4, 0.2),
        )
        self.conn.execute(
            "INSERT INTO met_lookup (hr_from, effort, met) VALUES (?, ?, ?)",
            (100, "Light", 2.0),
        )
        self.conn.execute(
            "INSERT INTO mass_log (measured_on, mass_kg) VALUES (?, ?)",
            ("2026-05-01", 80.0),
        )
        self.conn.execute(
            "INSERT INTO circuits (id, name, length, device_distance) VALUES (?, ?, ?, ?)",
            (1, "Manual Circuit", 2.0, 4.0),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_add_sprint_entry_inserts_values_used_by_calculations(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "day_number": "2",
                "sprint_index": "1",
                "duration_minutes": "5",
                "rpm": "130",
                "device_watts": "250",
                "hr": "120",
                "resistance": "4",
                "device_distance": "8",
                "notes": "manual",
            },
        )

        sprint = calculated_sprints(self.conn)[0]
        self.assertEqual(sprint.performed_on, "2026-05-02")
        self.assertAlmostEqual(sprint.estimated_watts, 50.0)
        self.assertAlmostEqual(sprint.calibrated_distance, 4.0)

    def test_add_lap_entry_requires_circuit_and_calculates_speed(self):
        add_lap_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "lap_index": "1",
                "circuit_id": "1",
                "lap_time_minutes": "4",
                "hr": "115",
                "resistance": "4",
                "rpm": "100",
                "notes": "",
            },
        )

        lap = calculated_laps(self.conn)[0]
        self.assertEqual(lap.circuit_name, "Manual Circuit")
        self.assertAlmostEqual(lap.average_speed, 30.0)

    def test_add_lap_entry_rejects_missing_circuit(self):
        with self.assertRaises(ValueError):
            add_lap_entry(
                self.conn,
                {
                    "performed_on": "2026-05-02",
                    "circuit_id": "",
                    "lap_time_minutes": "4",
                },
            )

    def test_circuit_goal_is_calculated_from_length_scale(self):
        rows = circuit_rows_with_goals(self.conn, include_inactive=True)

        self.assertAlmostEqual(rows[0]["calculated_device_distance"], 4.0)

    def test_circuit_add_and_update_ignore_manual_device_distance(self):
        add_circuit(
            self.conn,
            {
                "name": "New Circuit",
                "length": "3.0",
                "device_distance": "999",
            },
        )
        circuit = self.conn.execute("SELECT * FROM circuits WHERE name = ?", ("New Circuit",)).fetchone()
        self.assertIsNone(circuit["device_distance"])

        update_circuit(
            self.conn,
            {
                "id": str(circuit["id"]),
                "name": "New Circuit",
                "length": "4.0",
                "device_distance": "999",
                "active": "1",
            },
        )
        updated = self.conn.execute("SELECT * FROM circuits WHERE id = ?", (circuit["id"],)).fetchone()
        self.assertAlmostEqual(updated["length"], 4.0)
        self.assertIsNone(updated["device_distance"])

    def test_update_calibration_profile_edits_constants(self):
        update_calibration_profile(
            self.conn,
            {
                "id": "1",
                "name": "Updated",
                "length_scale": "0.42",
                "distance_per_stroke": "2.1",
            },
        )

        profile = editable_calibration_profile(self.conn)
        self.assertEqual(profile["name"], "Updated")
        self.assertAlmostEqual(profile["length_scale"], 0.42)
        self.assertAlmostEqual(profile["distance_per_stroke"], 2.1)

    def test_update_resistance_scaling_manual_factors(self):
        update_resistance_scaling(
            self.conn,
            {
                "scaling_1": "0.05",
                "scaling_4": "0.15",
                "scaling_12": "0.6",
            },
        )

        rows = {
            row["resistance"]: row["scaling"]
            for row in self.conn.execute("SELECT resistance, scaling FROM resistance_scaling")
        }
        self.assertAlmostEqual(rows[1], 0.05)
        self.assertAlmostEqual(rows[4], 0.15)
        self.assertAlmostEqual(rows[12], 0.6)

    def test_add_resistance_calibration_test_uses_expected_watts(self):
        add_resistance_calibration_test(
            self.conn,
            {
                "tested_on": "2026-05-03",
                "resistance": "5",
                "duration_minutes": "5",
                "device_watts": "300",
                "expected_watts": "60",
                "notes": "test",
            },
        )

        scaling = self.conn.execute(
            "SELECT scaling FROM resistance_scaling WHERE resistance = 5"
        ).fetchone()["scaling"]
        test = self.conn.execute(
            "SELECT calculated_scaling FROM resistance_calibration_tests WHERE resistance = 5"
        ).fetchone()
        self.assertAlmostEqual(scaling, 0.2)
        self.assertAlmostEqual(test["calculated_scaling"], 0.2)

    def test_calibration_preview_does_not_persist_factor(self):
        preview = calculate_resistance_calibration_preview(
            self.conn,
            {
                "tested_on": "2026-05-03",
                "resistance": "5",
                "duration_minutes": "5",
                "device_watts": "300",
                "expected_watts": "60",
            },
        )

        scaling = self.conn.execute(
            "SELECT scaling FROM resistance_scaling WHERE resistance = 5"
        ).fetchone()
        tests = self.conn.execute("SELECT COUNT(*) AS count FROM resistance_calibration_tests").fetchone()
        self.assertAlmostEqual(preview["calculated_scaling"], 0.2)
        self.assertIsNone(scaling)
        self.assertEqual(tests["count"], 0)

    def test_add_resistance_calibration_test_can_estimate_expected_watts_from_hr_and_mass(self):
        add_resistance_calibration_test(
            self.conn,
            {
                "tested_on": "2026-05-03",
                "resistance": "6",
                "duration_minutes": "5",
                "device_watts": "1000",
                "hr": "120",
                "mass_kg": "80",
            },
        )

        scaling = self.conn.execute(
            "SELECT scaling FROM resistance_scaling WHERE resistance = 6"
        ).fetchone()["scaling"]
        self.assertAlmostEqual(scaling, 0.1859555556)

    def test_add_and_update_mass_log(self):
        add_mass_log(self.conn, {"measured_on": "2026-05-04", "mass_kg": "79.5"})
        row = self.conn.execute("SELECT id, mass_kg FROM mass_log WHERE measured_on = ?", ("2026-05-04",)).fetchone()

        self.assertAlmostEqual(row["mass_kg"], 79.5)

        update_mass_log(
            self.conn,
            {"id": str(row["id"]), "measured_on": "2026-05-04", "mass_kg": "79.25"},
        )
        updated = self.conn.execute("SELECT mass_kg FROM mass_log WHERE id = ?", (row["id"],)).fetchone()
        self.assertAlmostEqual(updated["mass_kg"], 79.25)


if __name__ == "__main__":
    unittest.main()
