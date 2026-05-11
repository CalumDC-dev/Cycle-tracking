"""Workbook migration into the app database."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from .database import init_db, reset_db
from .xlsx_reader import XlsxTableReader, excel_date, integer, number


def _non_empty(value: object) -> bool:
    return value not in (None, "")


def _upsert_calibration(conn: sqlite3.Connection, length_scale: float, distance_per_stroke: float | None) -> int:
    conn.execute(
        """
        INSERT INTO calibration_profiles (name, length_scale, distance_per_stroke, active)
        VALUES ('Default under-desk bike', ?, ?, 1)
        ON CONFLICT(name) DO UPDATE SET
            length_scale = excluded.length_scale,
            distance_per_stroke = excluded.distance_per_stroke,
            active = 1
        """,
        (length_scale, distance_per_stroke),
    )
    row = conn.execute("SELECT id FROM calibration_profiles WHERE name = ?", ("Default under-desk bike",)).fetchone()
    return int(row["id"])


def import_workbook(path: str | Path, conn: sqlite3.Connection, *, reset: bool = False) -> dict[str, int]:
    if reset:
        reset_db(conn)
    else:
        init_db(conn)

    workbook_path = Path(path)
    with XlsxTableReader(str(workbook_path)) as reader:
        constants = reader.read_table("Constants")
        constant_row = constants[0] if constants else {}
        length_scale = number(constant_row.get("Length Scale")) or 0.45
        distance_per_stroke = number(constant_row.get("Distance per stroke"))
        calibration_id = _upsert_calibration(conn, length_scale, distance_per_stroke)

        conn.execute("DELETE FROM resistance_scaling")
        for row in reader.read_table("Resistances"):
            resistance = integer(row.get("Resistance"))
            scaling = number(row.get("Scaling"))
            if resistance is None or scaling is None:
                continue
            conn.execute(
                "INSERT INTO resistance_scaling (resistance, scaling) VALUES (?, ?)",
                (resistance, scaling),
            )

        conn.execute("DELETE FROM met_lookup")
        for row in reader.read_table("MET"):
            hr_from = integer(row.get("HR From"))
            effort = row.get("Effort")
            met = number(row.get("MET"))
            if hr_from is None or not effort or met is None:
                continue
            conn.execute(
                "INSERT INTO met_lookup (hr_from, effort, met) VALUES (?, ?, ?)",
                (hr_from, str(effort), met),
            )

        conn.execute("DELETE FROM mass_log")
        for row in reader.read_table("MassLog"):
            measured_on = excel_date(row.get("Date"))
            mass_kg = number(row.get("Mass"))
            if measured_on is None or mass_kg is None:
                continue
            conn.execute(
                "INSERT INTO mass_log (measured_on, mass_kg) VALUES (?, ?)",
                (measured_on, mass_kg),
            )

        conn.execute("DELETE FROM circuits")
        circuit_count = 0
        for row in reader.read_table("Circuits"):
            name = row.get("Circuit")
            length = number(row.get("Length"))
            if not name or length is None:
                continue
            device_distance = number(row.get("Device Distance"))
            conn.execute(
                "INSERT INTO circuits (name, length, device_distance) VALUES (?, ?, ?)",
                (str(name), length, device_distance),
            )
            circuit_count += 1

        conn.execute("DELETE FROM sprint_entries")
        sprint_count = 0
        for row in reader.read_table("SprintLog"):
            performed_on = excel_date(row.get("Date"))
            if performed_on is None:
                continue
            conn.execute(
                """
                INSERT INTO sprint_entries (
                    performed_on, day_number, sprint_index, duration_minutes, rpm,
                    device_watts, hr, resistance, device_distance
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    performed_on,
                    integer(row.get("Day")),
                    integer(row.get("Sprint")),
                    (number(row.get("Time Min")) or 0) * 24 * 60 if _non_empty(row.get("Time Min")) else None,
                    number(row.get("RPM")),
                    number(row.get("Device Watts")),
                    integer(row.get("HR")),
                    integer(row.get("Resistance")),
                    number(row.get("Device Distance")),
                ),
            )
            sprint_count += 1

        conn.execute("DELETE FROM lap_entries")
        lap_count = 0
        for row in reader.read_table("LapLog"):
            performed_on = excel_date(row.get("Date"))
            circuit_name = row.get("Circuit")
            if performed_on is None or not circuit_name:
                continue
            lap_time = number(row.get("Lap-time"))
            hr = integer(row.get("HR"))
            resistance = integer(row.get("Resistance"))
            rpm = number(row.get("RPM"))
            if lap_time is None and hr is None and resistance is None and rpm is None:
                continue
            circuit = conn.execute("SELECT id FROM circuits WHERE name = ?", (str(circuit_name),)).fetchone()
            circuit_id = int(circuit["id"]) if circuit else None
            conn.execute(
                """
                INSERT INTO lap_entries (
                    performed_on, lap_index, circuit_id, lap_time_minutes,
                    hr, resistance, rpm
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    performed_on,
                    integer(row.get("Lap")),
                    circuit_id,
                    lap_time * 24 * 60 if lap_time is not None else None,
                    hr,
                    resistance,
                    rpm,
                ),
            )
            lap_count += 1

        conn.execute(
            """
            INSERT INTO import_log (source_file, sprint_rows, lap_rows, circuit_rows)
            VALUES (?, ?, ?, ?)
            """,
            (str(workbook_path), sprint_count, lap_count, circuit_count),
        )
        conn.commit()

    return {
        "calibration_id": calibration_id,
        "sprint_rows": sprint_count,
        "lap_rows": lap_count,
        "circuit_rows": circuit_count,
    }

