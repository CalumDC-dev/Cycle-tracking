import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from workout_tracker.calculations import calculated_laps, calculated_sprints
from workout_tracker.database import init_db
from workout_tracker.web import (
    add_raw_activity,
    add_lap_entry,
    add_mass_log,
    add_resistance_calibration_test,
    add_sprint_entry,
    calculate_resistance_calibration_preview,
    circuit_rows_with_goals,
    editable_calibration_profile,
    add_circuit,
    confirm_duplicate_activity,
    find_activity_duplicate,
    import_activity_file_to_review,
    promote_raw_activity,
    raw_activity_has_entry,
    classify_activity,
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
                "started_at": "2026-05-02T07:30",
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
        self.assertEqual(sprint.started_at, "2026-05-02T07:30")
        self.assertAlmostEqual(sprint.estimated_watts, 50.0)
        self.assertAlmostEqual(sprint.calibrated_distance, 4.0)

    def test_add_lap_entry_requires_circuit_and_calculates_speed(self):
        add_lap_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "started_at": "2026-05-02T07:45",
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
        self.assertEqual(lap.started_at, "2026-05-02T07:45")
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

    def test_raw_activity_strong_duplicate_links_and_backfills_sprint_start(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-05",
                "duration_minutes": "5",
                "device_distance": "8",
                "hr": "127",
                "resistance": "4",
            },
        )
        sprint_id = self.conn.execute("SELECT id FROM sprint_entries WHERE performed_on = ?", ("2026-05-05",)).fetchone()["id"]

        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "abc123",
                "title": "Kinomap free-ride",
                "started_on": "2026-05-05T06:15",
                "duration_seconds": "300",
                "raw_distance": "8",
            },
        )

        raw = self.conn.execute("SELECT * FROM raw_activities WHERE source_activity_id = ?", ("abc123",)).fetchone()
        sprint = self.conn.execute("SELECT started_at FROM sprint_entries WHERE id = ?", (sprint_id,)).fetchone()
        self.assertEqual(raw["review_status"], "already_logged")
        self.assertEqual(raw["duplicate_entry_type"], "sprint")
        self.assertEqual(raw["duplicate_entry_id"], sprint_id)
        self.assertEqual(raw["hr"], 127)
        self.assertEqual(sprint["started_at"], "2026-05-05T06:15")

    def test_raw_activity_possible_duplicate_does_not_auto_backfill(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-06",
                "duration_minutes": "20",
                "device_distance": "8",
                "resistance": "4",
            },
        )

        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "possible",
                "started_on": "2026-05-06T06:15",
                "duration_seconds": "300",
                "raw_distance": "8",
            },
        )

        raw = self.conn.execute("SELECT * FROM raw_activities WHERE source_activity_id = ?", ("possible",)).fetchone()
        sprint = self.conn.execute("SELECT started_at FROM sprint_entries WHERE performed_on = ?", ("2026-05-06",)).fetchone()
        self.assertEqual(raw["review_status"], "possible_duplicate")
        self.assertIsNone(sprint["started_at"])

    def test_confirm_duplicate_backfills_possible_match(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-07",
                "duration_minutes": "20",
                "device_distance": "8",
                "hr": "131",
            },
        )
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "confirm-me",
                "started_on": "2026-05-07T06:15",
                "duration_seconds": "300",
                "raw_distance": "8",
            },
        )
        raw_id = self.conn.execute("SELECT id FROM raw_activities WHERE source_activity_id = ?", ("confirm-me",)).fetchone()["id"]

        confirm_duplicate_activity(self.conn, {"id": str(raw_id)})

        raw = self.conn.execute("SELECT * FROM raw_activities WHERE id = ?", (raw_id,)).fetchone()
        sprint = self.conn.execute("SELECT started_at FROM sprint_entries WHERE performed_on = ?", ("2026-05-07",)).fetchone()
        self.assertEqual(raw["review_status"], "already_logged")
        self.assertEqual(raw["hr"], 131)
        self.assertEqual(sprint["started_at"], "2026-05-07T06:15")

    def test_new_raw_activity_without_hr_goes_to_hr_queue(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "new-no-hr",
                "started_on": "2026-05-08T06:15",
                "duration_seconds": "300",
                "raw_distance": "3",
            },
        )

        raw = self.conn.execute("SELECT * FROM raw_activities WHERE source_activity_id = ?", ("new-no-hr",)).fetchone()
        self.assertEqual(raw["review_status"], "needs_hr")
        self.assertEqual(raw["session_type"], "sprint")

    def test_new_raw_activity_matching_circuit_goal_is_preclassified_as_lap(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "new-lap-guess",
                "started_on": "2026-05-08T07:15",
                "duration_seconds": "240",
                "raw_distance": "4",
            },
        )

        raw = self.conn.execute("SELECT * FROM raw_activities WHERE source_activity_id = ?", ("new-lap-guess",)).fetchone()
        self.assertEqual(raw["review_status"], "needs_hr")
        self.assertEqual(raw["session_type"], "lap")
        self.assertEqual(raw["circuit_id"], 1)

    def test_repeat_raw_activity_import_enriches_existing_payload_without_resetting_review(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "same-activity",
                "title": "Initial",
                "started_on": "2026-05-08T06:15",
                "duration_seconds": "300",
                "raw_distance": "3",
            },
        )
        self.conn.execute(
            "UPDATE raw_activities SET review_status = 'already_logged', raw_payload = ? WHERE source_activity_id = ?",
            (json.dumps({"existing": True}), "same-activity"),
        )
        self.conn.commit()

        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "same-activity",
                "title": "Better title",
                "started_on": "2026-05-08T06:15",
                "duration_seconds": "300",
                "raw_distance": "3",
                "raw_payload": json.dumps({"average_watts": 250.0, "archive_format": "strava_bulk_export"}),
            },
        )

        raw = self.conn.execute("SELECT * FROM raw_activities WHERE source_activity_id = ?", ("same-activity",)).fetchone()
        payload = json.loads(raw["raw_payload"])
        self.assertEqual(raw["review_status"], "already_logged")
        self.assertEqual(raw["title"], "Initial")
        self.assertTrue(payload["existing"])
        self.assertEqual(payload["average_watts"], 250.0)
        self.assertEqual(payload["archive_format"], "strava_bulk_export")

    def test_find_activity_duplicate_can_match_lap_by_circuit_goal(self):
        add_lap_entry(
            self.conn,
            {
                "performed_on": "2026-05-09",
                "circuit_id": "1",
                "lap_time_minutes": "4",
            },
        )

        duplicate = find_activity_duplicate(
            self.conn,
            started_on="2026-05-09T06:15",
            duration_seconds=240,
            raw_distance=4.0,
            session_type="lap",
            circuit_id=1,
        )

        self.assertIsNotNone(duplicate)
        assert duplicate is not None
        self.assertEqual(duplicate["entry_type"], "lap")
        self.assertGreaterEqual(duplicate["confidence"], 0.85)

    def test_classify_activity_keeps_activity_available_for_import(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "classify-me",
                "started_on": "2026-05-10T06:15",
                "duration_seconds": "300",
                "raw_distance": "4",
                "hr": "122",
            },
        )
        raw_id = self.conn.execute("SELECT id FROM raw_activities WHERE source_activity_id = ?", ("classify-me",)).fetchone()["id"]

        classify_activity(self.conn, {"id": str(raw_id), "session_type": "lap", "circuit_id": "1"})

        raw = self.conn.execute("SELECT review_status, session_type, circuit_id FROM raw_activities WHERE id = ?", (raw_id,)).fetchone()
        self.assertEqual(raw["review_status"], "ready_to_import")
        self.assertEqual(raw["session_type"], "lap")
        self.assertEqual(raw["circuit_id"], 1)

    def test_promote_raw_activity_imports_sprint_and_stores_manual_hr(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "new-sprint",
                "title": "Kinomap free-ride",
                "started_on": "2026-05-10T06:15",
                "duration_seconds": "300",
                "raw_distance": "8",
            },
        )
        raw_id = self.conn.execute("SELECT id FROM raw_activities WHERE source_activity_id = ?", ("new-sprint",)).fetchone()["id"]

        promote_raw_activity(
            self.conn,
            {
                "id": str(raw_id),
                "session_type": "sprint",
                "performed_on": "2026-05-10",
                "duration_minutes": "5",
                "hr": "128",
                "resistance": "4",
                "rpm": "116",
                "device_watts": "260",
                "entry_index": "2",
                "notes": "watch HR",
            },
        )

        sprint = self.conn.execute("SELECT * FROM sprint_entries WHERE raw_activity_id = ?", (raw_id,)).fetchone()
        raw = self.conn.execute("SELECT * FROM raw_activities WHERE id = ?", (raw_id,)).fetchone()
        self.assertEqual(raw["review_status"], "imported")
        self.assertEqual(raw["hr"], 128)
        self.assertEqual(raw["session_type"], "sprint")
        self.assertEqual(sprint["performed_on"], "2026-05-10")
        self.assertEqual(sprint["started_at"], "2026-05-10T06:15")
        self.assertEqual(sprint["sprint_index"], 2)
        self.assertAlmostEqual(sprint["duration_minutes"], 5.0)
        self.assertEqual(sprint["hr"], 128)
        self.assertEqual(sprint["resistance"], 4)
        self.assertAlmostEqual(sprint["rpm"], 116.0)
        self.assertAlmostEqual(sprint["device_watts"], 260.0)
        self.assertAlmostEqual(sprint["device_distance"], 8.0)
        self.assertTrue(raw_activity_has_entry(self.conn, raw_id))

    def test_promote_raw_activity_uses_source_payload_defaults_for_sprint(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "payload-sprint",
                "started_on": "2026-05-10T06:15",
                "duration_seconds": "300",
                "raw_distance": "8",
                "raw_payload": json.dumps({"average_cadence": 119.5, "average_watts": 287.25}),
            },
        )
        raw_id = self.conn.execute("SELECT id FROM raw_activities WHERE source_activity_id = ?", ("payload-sprint",)).fetchone()["id"]

        promote_raw_activity(
            self.conn,
            {
                "id": str(raw_id),
                "session_type": "sprint",
                "performed_on": "2026-05-10",
                "hr": "128",
            },
        )

        sprint = self.conn.execute("SELECT rpm, device_watts FROM sprint_entries WHERE raw_activity_id = ?", (raw_id,)).fetchone()
        self.assertAlmostEqual(sprint["rpm"], 119.5)
        self.assertAlmostEqual(sprint["device_watts"], 287.25)

    def test_promote_raw_activity_imports_lap_with_circuit_and_hr(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "new-lap",
                "started_on": "2026-05-11T06:15",
                "duration_seconds": "240",
                "raw_distance": "4",
            },
        )
        raw_id = self.conn.execute("SELECT id FROM raw_activities WHERE source_activity_id = ?", ("new-lap",)).fetchone()["id"]

        promote_raw_activity(
            self.conn,
            {
                "id": str(raw_id),
                "session_type": "lap",
                "performed_on": "2026-05-11",
                "duration_minutes": "4",
                "hr": "132",
                "resistance": "4",
                "rpm": "108",
                "entry_index": "1",
                "circuit_id": "1",
            },
        )

        lap = self.conn.execute("SELECT * FROM lap_entries WHERE raw_activity_id = ?", (raw_id,)).fetchone()
        raw = self.conn.execute("SELECT * FROM raw_activities WHERE id = ?", (raw_id,)).fetchone()
        self.assertEqual(raw["review_status"], "imported")
        self.assertEqual(raw["session_type"], "lap")
        self.assertEqual(raw["circuit_id"], 1)
        self.assertEqual(lap["started_at"], "2026-05-11T06:15")
        self.assertEqual(lap["lap_index"], 1)
        self.assertEqual(lap["circuit_id"], 1)
        self.assertAlmostEqual(lap["lap_time_minutes"], 4.0)
        self.assertEqual(lap["hr"], 132)

    def test_promote_raw_activity_requires_hr_and_prevents_double_import(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "needs-hr-import",
                "started_on": "2026-05-12T06:15",
                "duration_seconds": "300",
                "raw_distance": "8",
            },
        )
        raw_id = self.conn.execute("SELECT id FROM raw_activities WHERE source_activity_id = ?", ("needs-hr-import",)).fetchone()["id"]

        with self.assertRaises(ValueError):
            promote_raw_activity(
                self.conn,
                {
                    "id": str(raw_id),
                    "session_type": "sprint",
                    "performed_on": "2026-05-12",
                },
            )

        promote_raw_activity(
            self.conn,
            {
                "id": str(raw_id),
                "session_type": "sprint",
                "performed_on": "2026-05-12",
                "hr": "126",
            },
        )
        with self.assertRaises(ValueError):
            promote_raw_activity(
                self.conn,
                {
                    "id": str(raw_id),
                    "session_type": "sprint",
                    "performed_on": "2026-05-12",
                    "hr": "126",
                },
            )

    def test_import_activity_file_to_review_applies_duplicate_and_hr_status(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-13",
                "duration_minutes": "5",
                "device_distance": "8",
            },
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "activities.csv"
            path.write_text(
                "Activity ID,Activity Name,Activity Date,Elapsed Time,Distance\n"
                "duplicate,Known ride,2026-05-13T06:15:00,300,8\n"
                "new,New ride,2026-05-14T06:15:00,300,12\n",
                encoding="utf-8",
            )

            imported = import_activity_file_to_review(
                self.conn,
                {"source": "strava", "activity_file": str(path)},
            )

        duplicate = self.conn.execute(
            "SELECT review_status, duplicate_entry_type FROM raw_activities WHERE source_activity_id = ?",
            ("duplicate",),
        ).fetchone()
        new = self.conn.execute(
            "SELECT review_status FROM raw_activities WHERE source_activity_id = ?",
            ("new",),
        ).fetchone()
        self.assertEqual(imported, 2)
        self.assertEqual(duplicate["review_status"], "already_logged")
        self.assertEqual(duplicate["duplicate_entry_type"], "sprint")
        self.assertEqual(new["review_status"], "needs_hr")


if __name__ == "__main__":
    unittest.main()
