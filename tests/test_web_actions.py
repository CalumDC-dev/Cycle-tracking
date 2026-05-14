import json
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from workout_tracker.calculations import calculated_laps, calculated_sprints
from workout_tracker.database import init_db
import workout_tracker.web as web_module
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
    delete_entry,
    dismiss_duplicate_pair,
    find_activity_duplicate,
    fit_calibration_source_rows,
    grouped_table,
    import_activity_file_to_review,
    parse_post_params,
    populate_missing_duplicate_hr,
    render_insights,
    render_entries,
    render_calibration,
    render_maintenance,
    review_actions,
    calibration_coverage_rows,
    circuit_progress_rows,
    maintenance_items,
    promote_activity_form,
    promote_raw_activity,
    raw_activity_has_entry,
    classify_activity,
    strength_signal_rows,
    update_circuit,
    update_calibration_profile,
    update_lap_entry,
    update_mass_log,
    update_sprint_entry,
    update_resistance_scaling,
    UploadedFile,
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
                "started_at": "07:30",
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
                "started_at": "07:45",
                "lap_index": "1",
                "circuit_id": "1",
                "lap_time_minutes": "4:12",
                "hr": "115",
                "resistance": "4",
                "rpm": "100",
                "notes": "",
            },
        )

        lap = calculated_laps(self.conn)[0]
        self.assertEqual(lap.circuit_name, "Manual Circuit")
        self.assertEqual(lap.started_at, "2026-05-02T07:45")
        self.assertAlmostEqual(lap.lap_time_minutes, 4.2)
        self.assertAlmostEqual(lap.average_speed, 28.5714285714)

    def test_add_lap_entry_accepts_hour_duration_format(self):
        add_lap_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "circuit_id": "1",
                "lap_time_minutes": "1:02:30",
            },
        )

        lap = calculated_laps(self.conn)[0]
        self.assertAlmostEqual(lap.lap_time_minutes, 62.5)

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

    def test_update_sprint_entry_fills_missing_start_index_and_resistance(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "duration_minutes": "5",
                "device_watts": "250",
                "hr": "120",
                "device_distance": "8",
            },
        )
        entry_id = self.conn.execute("SELECT id FROM sprint_entries").fetchone()["id"]

        update_sprint_entry(
            self.conn,
            {
                "id": str(entry_id),
                "performed_on": "2026-05-02",
                "started_at": "2026-05-02T07:30",
                "sprint_index": "3",
                "duration_minutes": "5",
                "rpm": "131.5",
                "device_watts": "250",
                "hr": "120",
                "resistance": "4",
                "device_distance": "8",
            },
        )

        sprint = calculated_sprints(self.conn)[0]
        self.assertEqual(sprint.started_at, "2026-05-02T07:30")
        self.assertEqual(sprint.sprint_index, 3)
        self.assertEqual(sprint.resistance, 4)
        self.assertAlmostEqual(sprint.calories_watts, 15.0)

    def test_update_lap_entry_fills_missing_start_index_and_resistance(self):
        add_lap_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "circuit_id": "1",
                "lap_time_minutes": "4",
                "hr": "115",
            },
        )
        entry_id = self.conn.execute("SELECT id FROM lap_entries").fetchone()["id"]

        update_lap_entry(
            self.conn,
            {
                "id": str(entry_id),
                "performed_on": "2026-05-02",
                "started_at": "2026-05-02T07:45",
                "lap_index": "2",
                "circuit_id": "1",
                "lap_time_minutes": "4:30",
                "hr": "115",
                "resistance": "4",
                "rpm": "100",
            },
        )

        lap = calculated_laps(self.conn)[0]
        self.assertEqual(lap.started_at, "2026-05-02T07:45")
        self.assertEqual(lap.lap_index, 2)
        self.assertEqual(lap.resistance, 4)
        self.assertAlmostEqual(lap.lap_time_minutes, 4.5)

    def test_render_entries_has_inline_edit_forms_with_resistance_defaults(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "duration_minutes": "5",
                "device_watts": "250",
            },
        )
        add_lap_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "circuit_id": "1",
                "lap_time_minutes": "4",
            },
        )

        html = render_entries(self.conn)

        self.assertIn('/entries/sprint/update', html)
        self.assertIn('/entries/lap/update', html)
        self.assertIn('name="sprint_index"', html)
        self.assertIn('name="lap_index"', html)
        self.assertIn('type="time"', html)
        self.assertIn('name="lap_time_minutes"', html)
        self.assertIn('value="4:00"', html)
        self.assertNotIn('name="lap_time_sec"', html)
        self.assertIn('Calories (HR/MET)', html)
        self.assertIn('<option value="4" selected>4</option>', html)

    def test_maintenance_flags_possible_manual_duplicate_entries(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "started_at": "07:30",
                "sprint_index": "1",
                "duration_minutes": "5",
                "device_distance": "2",
            },
        )
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "started_at": "07:31",
                "sprint_index": "1",
                "duration_minutes": "5",
                "device_distance": "2",
            },
        )

        items = maintenance_items(self.conn)
        duplicate_items = [item for item in items if item["issue"] == "Possible duplicate entry"]

        self.assertEqual(len(duplicate_items), 1)
        self.assertEqual(duplicate_items[0]["category"], "Analysis blocker")
        self.assertIn("start time within 2 minutes", duplicate_items[0]["detail"])
        html = render_maintenance(self.conn)
        self.assertIn('/entries/delete', html)
        self.assertIn('/maintenance/not-duplicate', html)
        self.assertIn('name="entry_type" value="sprint"', html)
        self.assertIn("Delete sprint 1", html)
        self.assertIn("Not duplicate", html)

    def test_maintenance_can_dismiss_false_positive_manual_duplicate(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "started_at": "07:30",
                "sprint_index": "1",
                "duration_minutes": "15",
                "device_distance": "5",
            },
        )
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "started_at": "08:00",
                "sprint_index": "2",
                "duration_minutes": "15",
                "device_distance": "5",
            },
        )
        ids = [
            row["id"]
            for row in self.conn.execute("SELECT id FROM sprint_entries ORDER BY id").fetchall()
        ]
        self.assertIn("Possible duplicate entry", [item["issue"] for item in maintenance_items(self.conn)])

        dismiss_duplicate_pair(
            self.conn,
            {"entry_type": "sprint", "first_id": str(ids[1]), "second_id": str(ids[0])},
        )

        self.assertNotIn("Possible duplicate entry", [item["issue"] for item in maintenance_items(self.conn)])
        dismissal = self.conn.execute(
            "SELECT entry_type, first_entry_id, second_entry_id FROM duplicate_dismissals"
        ).fetchone()
        self.assertEqual(dict(dismissal), {"entry_type": "sprint", "first_entry_id": ids[0], "second_entry_id": ids[1]})

    def test_delete_entry_removes_manual_duplicate(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "started_at": "07:30",
                "sprint_index": "1",
                "duration_minutes": "5",
                "device_distance": "2",
            },
        )
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "started_at": "07:31",
                "sprint_index": "1",
                "duration_minutes": "5",
                "device_distance": "2",
            },
        )
        duplicate_id = self.conn.execute(
            "SELECT id FROM sprint_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]

        delete_entry(self.conn, {"entry_type": "sprint", "id": str(duplicate_id)})

        remaining = self.conn.execute("SELECT COUNT(*) AS total FROM sprint_entries").fetchone()["total"]
        issues = [item["issue"] for item in maintenance_items(self.conn)]
        self.assertEqual(remaining, 1)
        self.assertNotIn("Possible duplicate entry", issues)

    def test_maintenance_flags_missing_entry_fields_and_review_items(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-02",
                "duration_minutes": "5",
            },
        )
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "needs-work",
                "started_on": "2026-05-03T07:00",
                "duration_seconds": "300",
            },
        )

        items = maintenance_items(self.conn)
        issues = {item["issue"] for item in items}
        categories = {item["issue"]: item["category"] for item in items}
        html = render_maintenance(self.conn)

        self.assertIn("Missing HR", issues)
        self.assertIn("Missing resistance", issues)
        self.assertIn("Pending needs_hr", issues)
        self.assertEqual(categories["Missing HR"], "Analysis blocker")
        self.assertEqual(categories["Missing sprint number"], "Tidying")
        self.assertEqual(categories["Missing device watts"], "Optional enrichment")
        self.assertIn("Analysis blocker", html)
        self.assertIn("Tidying", html)
        self.assertIn("Optional enrichment", html)
        self.assertIn("/entries#sprint-", html)
        self.assertIn("/review", html)
        self.assertIn("/export/backup.zip", html)

    def test_render_insights_summarises_progress_strength_and_calibration(self):
        add_resistance_calibration_test(
            self.conn,
            {
                "tested_on": "2026-05-03",
                "resistance": "8",
                "duration_minutes": "5",
                "device_watts": "500",
                "expected_watts": "60",
            },
        )
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-04",
                "started_at": "2026-05-04T07:30",
                "sprint_index": "1",
                "duration_minutes": "10",
                "rpm": "80",
                "device_watts": "500",
                "hr": "120",
                "resistance": "8",
                "device_distance": "3",
            },
        )
        add_lap_entry(
            self.conn,
            {
                "performed_on": "2026-05-04",
                "started_at": "2026-05-04T07:45",
                "lap_index": "1",
                "circuit_id": "1",
                "lap_time_minutes": "5",
                "hr": "120",
                "resistance": "4",
                "rpm": "100",
            },
        )
        add_lap_entry(
            self.conn,
            {
                "performed_on": "2026-05-05",
                "started_at": "2026-05-05T07:45",
                "lap_index": "1",
                "circuit_id": "1",
                "lap_time_minutes": "4",
                "hr": "120",
                "resistance": "4",
                "rpm": "100",
            },
        )
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "metric-source",
                "started_on": "2026-05-04T07:30",
                "review_status": "already_logged",
                "session_type": "sprint",
                "raw_payload": json.dumps({"average_watts": 500, "best_300s_watts": 480, "average_cadence": 80}),
            },
        )

        sprints = calculated_sprints(self.conn)
        laps = calculated_laps(self.conn)
        circuit_rows = circuit_progress_rows(laps)
        strength_rows = strength_signal_rows(sprints, laps)
        coverage_rows = calibration_coverage_rows(self.conn)
        html = render_insights(self.conn)

        self.assertEqual(circuit_rows[0]["circuit"], "Manual Circuit")
        self.assertAlmostEqual(circuit_rows[0]["change_minutes"], 1.0)
        self.assertEqual(strength_rows[0]["resistance"], 8)
        self.assertEqual(coverage_rows[7]["resistance"], 8)
        self.assertAlmostEqual(coverage_rows[7]["scaling"], 0.12)
        self.assertIn("Circuit Progress", html)
        self.assertIn("Strength Signals", html)
        self.assertIn("Resistance Calibration Coverage", html)
        self.assertIn("Best 5 minute estimated watts", html)
        self.assertIn("Estimated Watts (W)", html)
        self.assertIn("Heart Rate (bpm)", html)
        self.assertIn("Open larger chart", html)
        self.assertIn("chart-large", html)
        self.assertIn('viewBox="0 0 1000 667"', html)
        self.assertIn("chart-grid-line", html)

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
                "mechanical_efficiency": "0.23",
            },
        )

        profile = editable_calibration_profile(self.conn)
        self.assertEqual(profile["name"], "Updated")
        self.assertAlmostEqual(profile["length_scale"], 0.42)
        self.assertAlmostEqual(profile["distance_per_stroke"], 2.1)
        self.assertAlmostEqual(profile["mechanical_efficiency"], 0.23)

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
        self.assertAlmostEqual(scaling, 0.0409102222)

    def test_fit_calibration_preview_uses_imported_fit_source_defaults(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "fit-cal-source",
                "title": "Steady calibration effort",
                "started_on": "2026-05-14T10:00:00Z",
                "duration_seconds": "300",
                "raw_distance": "4.2",
                "hr": "120",
                "raw_payload": json.dumps(
                    {
                        "format": "fit",
                        "average_watts": 350,
                        "average_cadence": 126,
                    }
                ),
            },
        )
        raw_id = self.conn.execute(
            "SELECT id FROM raw_activities WHERE source_activity_id = ?",
            ("fit-cal-source",),
        ).fetchone()["id"]

        preview = calculate_resistance_calibration_preview(
            self.conn,
            {
                "source_raw_activity_id": str(raw_id),
                "resistance": "6",
            },
        )

        self.assertEqual(preview["tested_on"], "2026-05-14")
        self.assertAlmostEqual(preview["duration_minutes"], 5.0)
        self.assertAlmostEqual(preview["device_watts"], 350.0)
        self.assertEqual(preview["hr"], 120)
        self.assertAlmostEqual(preview["mass_kg"], 80.0)
        self.assertAlmostEqual(preview["expected_watts"], 40.9102222)
        self.assertAlmostEqual(preview["calculated_scaling"], 0.1168863492)
        self.assertAlmostEqual(preview["metabolic_watts"], 185.9555556)
        self.assertAlmostEqual(preview["mechanical_efficiency"], 0.22)
        self.assertEqual(preview["expected_watts_source"], "HR/MET x mechanical efficiency")
        self.assertIn("Steady calibration effort", preview["notes"])

    def test_render_calibration_lists_fit_assisted_sources(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "fit-cal-source",
                "title": "Steady calibration effort",
                "started_on": "2026-05-14T10:00:00Z",
                "duration_seconds": "300",
                "raw_distance": "4.2",
                "raw_payload": json.dumps(
                    {
                        "format": "fit",
                        "average_watts": 350,
                        "average_cadence": 126,
                    }
                ),
            },
        )

        sources = fit_calibration_source_rows(self.conn)
        html = render_calibration(self.conn)

        self.assertEqual(len(sources), 1)
        self.assertIn("FIT-Assisted Calibration Test", html)
        self.assertIn("Steady calibration effort", html)
        self.assertIn('name="source_raw_activity_id"', html)
        self.assertIn("Preview factor", html)

    def test_fit_calibration_upload_preview_persists_source_metadata(self):
        upload_bytes = b"fake-fit-bytes"
        payload = json.dumps(
            {
                "format": "fit",
                "average_watts": 350,
                "average_cadence": 126,
                "cadence_variability_pct": 4,
            },
            sort_keys=True,
        )

        def fake_load_activity_file(path, source):
            return [
                {
                    "source": source,
                    "source_activity_id": "fit:calibration-source",
                    "title": "Resistance 6 calibration",
                    "started_on": "2026-05-14T10:00:00Z",
                    "duration_seconds": 300,
                    "raw_distance": 4.2,
                    "hr": None,
                    "raw_payload": payload,
                }
            ]

        original = web_module.load_activity_file
        web_module.load_activity_file = fake_load_activity_file
        try:
            preview = calculate_resistance_calibration_preview(
                self.conn,
                {
                    "source": "strava",
                    "calibration_upload": UploadedFile("resistance_6.fit", upload_bytes),
                    "resistance": "6",
                    "hr": "120",
                },
            )
            apply_params = {key: "" if value is None else str(value) for key, value in preview.items()}
            add_resistance_calibration_test(self.conn, apply_params)
        finally:
            web_module.load_activity_file = original

        self.assertEqual(preview["tested_on"], "2026-05-14")
        self.assertAlmostEqual(preview["duration_minutes"], 5.0)
        self.assertAlmostEqual(preview["device_watts"], 350.0)
        self.assertEqual(preview["source_file"], "resistance_6.fit")
        self.assertEqual(preview["file_sha256"], hashlib.sha256(upload_bytes).hexdigest())
        self.assertIsNone(preview["quality_flags"])
        row = self.conn.execute(
            """
            SELECT source, source_activity_id, source_title, source_started_on,
                   source_file, file_sha256, raw_payload, quality_flags
            FROM resistance_calibration_tests
            WHERE resistance = 6
            """
        ).fetchone()
        self.assertEqual(row["source"], "strava")
        self.assertEqual(row["source_activity_id"], "fit:calibration-source")
        self.assertEqual(row["source_title"], "Resistance 6 calibration")
        self.assertEqual(row["source_started_on"], "2026-05-14T10:00:00Z")
        self.assertEqual(row["source_file"], "resistance_6.fit")
        self.assertEqual(row["file_sha256"], hashlib.sha256(upload_bytes).hexdigest())
        self.assertEqual(row["raw_payload"], payload)
        self.assertIsNone(row["quality_flags"])
        raw_count = self.conn.execute("SELECT COUNT(*) AS count FROM raw_activities").fetchone()["count"]
        self.assertEqual(raw_count, 0)

    def test_render_calibration_has_direct_fit_upload(self):
        html = render_calibration(self.conn)

        self.assertIn('name="calibration_upload"', html)
        self.assertIn("Preview calibration file", html)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('name="mass_kg" type="number" step="0.001" min="0" value="80"', html)

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
                "hr": "129",
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
        self.assertEqual(raw["hr"], 129)
        self.assertIsNone(sprint["started_at"])

    def test_populate_missing_duplicate_hr_updates_existing_review_rows(self):
        add_sprint_entry(
            self.conn,
            {
                "performed_on": "2026-05-06",
                "duration_minutes": "20",
                "device_distance": "8",
                "hr": "134",
            },
        )
        sprint_id = self.conn.execute("SELECT id FROM sprint_entries WHERE performed_on = ?", ("2026-05-06",)).fetchone()["id"]
        self.conn.execute(
            """
            INSERT INTO raw_activities (
                source, source_activity_id, started_on, duration_seconds, raw_distance,
                review_status, session_type, duplicate_entry_type, duplicate_entry_id,
                duplicate_confidence, duplicate_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "strava",
                "existing-missing-hr",
                "2026-05-06T06:15",
                300,
                8,
                "possible_duplicate",
                "sprint",
                "sprint",
                sprint_id,
                0.65,
                "same date",
            ),
        )
        self.conn.commit()

        updated = populate_missing_duplicate_hr(self.conn)

        raw = self.conn.execute("SELECT hr FROM raw_activities WHERE source_activity_id = ?", ("existing-missing-hr",)).fetchone()
        self.assertEqual(updated, 1)
        self.assertEqual(raw["hr"], 134)

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

    def test_promote_activity_form_rounds_source_defaults_to_input_step(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "payload-form",
                "started_on": "2026-05-10T06:15",
                "duration_seconds": "4502",
                "raw_distance": "8",
                "raw_payload": json.dumps({"average_cadence": 132.321, "average_watts": 347.654}),
            },
        )
        row = self.conn.execute("SELECT * FROM raw_activities WHERE source_activity_id = ?", ("payload-form",)).fetchone()

        html = promote_activity_form(row, '<option value="">No circuit</option>')

        self.assertIn('name="rpm" type="number" step="0.1" min="0" value="132.3"', html)
        self.assertIn('name="device_watts" type="number" step="0.1" min="0" value="347.7"', html)
        self.assertIn('name="duration_minutes" type="number" step="0.001" min="0" value="75.033"', html)
        self.assertIn('name="resistance" type="number" min="1" max="12" value="4" required', html)

    def test_promote_raw_activity_defaults_missing_resistance_to_four(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "default-resistance",
                "started_on": "2026-05-10T06:15",
                "duration_seconds": "300",
                "raw_distance": "8",
                "hr": "128",
            },
        )
        raw_id = self.conn.execute("SELECT id FROM raw_activities WHERE source_activity_id = ?", ("default-resistance",)).fetchone()["id"]

        promote_raw_activity(
            self.conn,
            {
                "id": str(raw_id),
                "session_type": "sprint",
                "performed_on": "2026-05-10",
                "hr": "128",
            },
        )

        sprint = self.conn.execute("SELECT resistance FROM sprint_entries WHERE raw_activity_id = ?", (raw_id,)).fetchone()
        self.assertEqual(sprint["resistance"], 4)

    def test_review_actions_include_explicit_ignore_button(self):
        add_raw_activity(
            self.conn,
            {
                "source": "strava",
                "source_activity_id": "noise",
                "started_on": "2026-05-10T06:15",
                "duration_seconds": "5",
                "raw_distance": "0.01",
            },
        )
        row = self.conn.execute("SELECT * FROM raw_activities WHERE source_activity_id = ?", ("noise",)).fetchone()

        html = review_actions(row, '<option value="">No circuit</option>')

        self.assertIn('name="session_type" value="ignore"', html)
        self.assertIn("Ignore activity", html)

    def test_grouped_table_marks_day_groups(self):
        html = grouped_table(["Date", "Value"], [["2026-05-10", 1], ["2026-05-10", 2], ["2026-05-11", 3]])

        self.assertIn("day-group-a day-start", html)
        self.assertIn("day-group-b day-start", html)

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

    def test_promote_raw_activity_requires_hr_and_tolerates_double_submit(self):
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
        promote_raw_activity(
            self.conn,
            {
                "id": str(raw_id),
                "session_type": "sprint",
                "performed_on": "2026-05-12",
                "hr": "126",
            },
        )
        total = self.conn.execute(
            "SELECT COUNT(*) AS total FROM sprint_entries WHERE raw_activity_id = ?",
            (raw_id,),
        ).fetchone()["total"]
        self.assertEqual(total, 1)

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

    def test_import_activity_file_to_review_accepts_uploaded_file(self):
        upload = UploadedFile(
            "activities.csv",
            (
                "Activity ID,Activity Name,Activity Date,Elapsed Time,Distance\n"
                "uploaded,Uploaded ride,2026-05-15T06:15:00,300,12\n"
            ).encode("utf-8"),
        )

        imported = import_activity_file_to_review(
            self.conn,
            {"source": "strava", "activity_upload": upload, "activity_file": ""},
        )

        raw = self.conn.execute(
            "SELECT title, review_status FROM raw_activities WHERE source_activity_id = ?",
            ("uploaded",),
        ).fetchone()
        self.assertEqual(imported, 1)
        self.assertEqual(raw["title"], "Uploaded ride")
        self.assertEqual(raw["review_status"], "needs_hr")

    def test_parse_post_params_extracts_multipart_upload(self):
        boundary = "----test-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="source"\r\n\r\n'
            "strava\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="activity_upload"; filename="activities.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
            "Activity ID,Activity Date,Elapsed Time,Distance\r\n"
            "abc,2026-05-15T06:15:00,300,12\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        params = parse_post_params(f"multipart/form-data; boundary={boundary}", body)

        self.assertEqual(params["source"], "strava")
        self.assertIsInstance(params["activity_upload"], UploadedFile)
        upload = params["activity_upload"]
        assert isinstance(upload, UploadedFile)
        self.assertEqual(upload.filename, "activities.csv")
        self.assertIn(b"Activity ID", upload.content)


if __name__ == "__main__":
    unittest.main()
