"""Calibration and summary calculations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import sqlite3
from typing import Any


@dataclass(frozen=True)
class CalculatedSprint:
    id: int
    performed_on: str
    started_at: str | None
    sprint_index: int | None
    duration_minutes: float | None
    rpm: float | None
    device_watts: float | None
    estimated_watts: float | None
    hr: int | None
    resistance: int | None
    device_distance: float | None
    calibrated_distance: float | None
    calories_watts: float | None
    calories_mets: float | None


@dataclass(frozen=True)
class CalculatedLap:
    id: int
    performed_on: str
    started_at: str | None
    lap_index: int | None
    circuit_id: int | None
    circuit_name: str | None
    lap_time_minutes: float | None
    length: float | None
    device_distance: float | None
    average_speed: float | None
    hr: int | None
    resistance: int | None
    rpm: float | None
    calories_mets: float | None


def active_calibration(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT * FROM calibration_profiles
        WHERE active = 1
        ORDER BY id
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("No active calibration profile found")
    return row


def device_distance_for_length(length: float | None, length_scale: float | None) -> float | None:
    if length is None or length_scale in (None, 0):
        return None
    return float(length) / float(length_scale)


def resistance_scale(conn: sqlite3.Connection, resistance: int | None) -> float | None:
    if resistance is None:
        return None
    row = conn.execute(
        "SELECT scaling FROM resistance_scaling WHERE resistance = ?",
        (resistance,),
    ).fetchone()
    return float(row["scaling"]) if row else None


def met_for_hr(conn: sqlite3.Connection, hr: int | None) -> float | None:
    if hr is None:
        return None
    row = conn.execute(
        """
        SELECT met FROM met_lookup
        WHERE hr_from <= ?
        ORDER BY hr_from DESC
        LIMIT 1
        """,
        (hr,),
    ).fetchone()
    return float(row["met"]) if row else None


def estimated_watts_from_hr(conn: sqlite3.Connection, hr: int | None, mass_kg: float | None) -> float | None:
    met = met_for_hr(conn, hr)
    if met is None or mass_kg is None:
        return None
    # MET calories are kcal/hour. Convert kcal/hour to watts.
    return met * mass_kg * 4184 / 3600


def estimated_mechanical_watts_from_hr(
    conn: sqlite3.Connection,
    hr: int | None,
    mass_kg: float | None,
    mechanical_efficiency: float | None,
) -> float | None:
    metabolic_watts = estimated_watts_from_hr(conn, hr, mass_kg)
    if metabolic_watts is None or mechanical_efficiency is None:
        return None
    return metabolic_watts * mechanical_efficiency


def mass_for_date(conn: sqlite3.Connection, performed_on: str) -> float | None:
    row = conn.execute(
        """
        SELECT mass_kg FROM mass_log
        WHERE measured_on <= ?
        ORDER BY measured_on DESC
        LIMIT 1
        """,
        (performed_on,),
    ).fetchone()
    if row is None:
        row = conn.execute("SELECT mass_kg FROM mass_log ORDER BY measured_on LIMIT 1").fetchone()
    return float(row["mass_kg"]) if row else None


def _hours(minutes: float | None) -> float | None:
    if minutes is None:
        return None
    return minutes / 60


def _met_calories(conn: sqlite3.Connection, performed_on: str, hr: int | None, minutes: float | None) -> float | None:
    hours = _hours(minutes)
    met = met_for_hr(conn, hr)
    mass = mass_for_date(conn, performed_on)
    if hours is None or met is None or mass is None:
        return None
    return met * mass * hours


def calculated_sprints(conn: sqlite3.Connection) -> list[CalculatedSprint]:
    calibration = active_calibration(conn)
    length_scale = float(calibration["length_scale"])
    rows = conn.execute(
        """
        SELECT * FROM sprint_entries
        ORDER BY performed_on, COALESCE(sprint_index, 999999), id
        """
    ).fetchall()
    output = []
    for row in rows:
        scale = resistance_scale(conn, row["resistance"])
        estimated_watts = None
        if row["device_watts"] is not None and scale is not None:
            estimated_watts = float(row["device_watts"]) * scale
        hours = _hours(row["duration_minutes"])
        calories_watts = None
        if estimated_watts is not None and hours is not None:
            calories_watts = estimated_watts * hours * 3.6
        calibrated_distance = None
        if row["device_distance"] is not None:
            calibrated_distance = float(row["device_distance"]) * length_scale
        output.append(
            CalculatedSprint(
                id=int(row["id"]),
                performed_on=row["performed_on"],
                started_at=row["started_at"],
                sprint_index=row["sprint_index"],
                duration_minutes=row["duration_minutes"],
                rpm=row["rpm"],
                device_watts=row["device_watts"],
                estimated_watts=estimated_watts,
                hr=row["hr"],
                resistance=row["resistance"],
                device_distance=row["device_distance"],
                calibrated_distance=calibrated_distance,
                calories_watts=calories_watts,
                calories_mets=_met_calories(conn, row["performed_on"], row["hr"], row["duration_minutes"]),
            )
        )
    return output


def calculated_laps(conn: sqlite3.Connection) -> list[CalculatedLap]:
    calibration = active_calibration(conn)
    length_scale = float(calibration["length_scale"])
    rows = conn.execute(
        """
        SELECT l.*, c.name AS circuit_name, c.length, c.device_distance
        FROM lap_entries l
        LEFT JOIN circuits c ON c.id = l.circuit_id
        ORDER BY l.performed_on, COALESCE(l.lap_index, 999999), l.id
        """
    ).fetchall()
    output = []
    for row in rows:
        hours = _hours(row["lap_time_minutes"])
        average_speed = None
        if row["length"] is not None and hours and hours > 0:
            average_speed = float(row["length"]) / hours
        output.append(
            CalculatedLap(
                id=int(row["id"]),
                performed_on=row["performed_on"],
                started_at=row["started_at"],
                lap_index=row["lap_index"],
                circuit_id=row["circuit_id"],
                circuit_name=row["circuit_name"],
                lap_time_minutes=row["lap_time_minutes"],
                length=row["length"],
                device_distance=device_distance_for_length(row["length"], length_scale),
                average_speed=average_speed,
                hr=row["hr"],
                resistance=row["resistance"],
                rpm=row["rpm"],
                calories_mets=_met_calories(conn, row["performed_on"], row["hr"], row["lap_time_minutes"]),
            )
        )
    return output


def daily_summary(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    days: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "date": "",
        "sprint_count": 0,
        "lap_count": 0,
        "sprint_calories": 0.0,
        "lap_calories": 0.0,
        "sprint_minutes": 0.0,
        "lap_minutes": 0.0,
        "sprint_device_distance": 0.0,
        "sprint_calibrated_distance": 0.0,
        "lap_distance": 0.0,
        "weighted_watts_total": 0.0,
        "weighted_watts_minutes": 0.0,
        "rpm_values": [],
        "hr_values": [],
        "resistance_values": [],
    })

    for sprint in calculated_sprints(conn):
        day = days[sprint.performed_on]
        day["date"] = sprint.performed_on
        day["sprint_count"] += 1
        day["sprint_calories"] += sprint.calories_mets or 0
        day["sprint_minutes"] += sprint.duration_minutes or 0
        day["sprint_device_distance"] += sprint.device_distance or 0
        day["sprint_calibrated_distance"] += sprint.calibrated_distance or 0
        if sprint.estimated_watts is not None and sprint.duration_minutes:
            day["weighted_watts_total"] += sprint.estimated_watts * sprint.duration_minutes
            day["weighted_watts_minutes"] += sprint.duration_minutes
        if sprint.rpm is not None:
            day["rpm_values"].append(sprint.rpm)
        if sprint.hr is not None:
            day["hr_values"].append(sprint.hr)
        if sprint.resistance is not None:
            day["resistance_values"].append(sprint.resistance)

    for lap in calculated_laps(conn):
        day = days[lap.performed_on]
        day["date"] = lap.performed_on
        day["lap_count"] += 1
        day["lap_calories"] += lap.calories_mets or 0
        day["lap_minutes"] += lap.lap_time_minutes or 0
        day["lap_distance"] += lap.length or 0
        if lap.rpm is not None:
            day["rpm_values"].append(lap.rpm)
        if lap.hr is not None:
            day["hr_values"].append(lap.hr)
        if lap.resistance is not None:
            day["resistance_values"].append(lap.resistance)

    summaries = []
    for date_key in sorted(days):
        day = days[date_key]
        total_minutes = day["sprint_minutes"] + day["lap_minutes"]
        total_calories = day["sprint_calories"] + day["lap_calories"]
        total_distance = day["sprint_calibrated_distance"] + day["lap_distance"]
        summaries.append({
            "date": day["date"],
            "sprint_count": day["sprint_count"],
            "lap_count": day["lap_count"],
            "sprint_calories": day["sprint_calories"],
            "lap_calories": day["lap_calories"],
            "total_calories": total_calories,
            "sprint_minutes": day["sprint_minutes"],
            "lap_minutes": day["lap_minutes"],
            "total_minutes": total_minutes,
            "average_sprint_minutes": day["sprint_minutes"] / day["sprint_count"] if day["sprint_count"] else None,
            "average_watts": (
                day["weighted_watts_total"] / day["weighted_watts_minutes"]
                if day["weighted_watts_minutes"] else None
            ),
            "average_rpm": _average(day["rpm_values"]),
            "average_hr": _average(day["hr_values"]),
            "average_resistance": _average(day["resistance_values"]),
            "sprint_device_distance": day["sprint_device_distance"],
            "sprint_calibrated_distance": day["sprint_calibrated_distance"],
            "lap_distance": day["lap_distance"],
            "total_distance": total_distance,
        })
    return summaries


def dashboard_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    summary = daily_summary(conn)
    sprints = calculated_sprints(conn)
    laps = calculated_laps(conn)
    mass_rows = conn.execute("SELECT measured_on, mass_kg FROM mass_log ORDER BY measured_on").fetchall()

    total_distance = sum(day["total_distance"] for day in summary)
    total_calories = sum(day["total_calories"] for day in summary)
    total_minutes = sum(day["total_minutes"] for day in summary)
    best_lap = min((lap for lap in laps if lap.lap_time_minutes), key=lambda lap: lap.lap_time_minutes, default=None)
    mass_change = None
    if len(mass_rows) >= 2:
        mass_change = float(mass_rows[-1]["mass_kg"]) - float(mass_rows[0]["mass_kg"])

    return {
        "workout_days": len(summary),
        "sprint_count": len(sprints),
        "lap_count": len(laps),
        "total_distance": total_distance,
        "total_calories": total_calories,
        "total_minutes": total_minutes,
        "average_watts": _average([day["average_watts"] for day in summary if day["average_watts"] is not None]),
        "average_rpm": _average([day["average_rpm"] for day in summary if day["average_rpm"] is not None]),
        "best_lap_minutes": best_lap.lap_time_minutes if best_lap else None,
        "best_lap_circuit": best_lap.circuit_name if best_lap else None,
        "best_laps_by_circuit": best_laps_by_circuit(laps),
        "mass_change": mass_change,
        "daily": summary,
        "mass": [dict(row) for row in mass_rows],
    }


def best_laps_by_circuit(laps: list[CalculatedLap] | None = None, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    if laps is None:
        if conn is None:
            raise ValueError("Either laps or conn must be supplied.")
        laps = calculated_laps(conn)

    best: dict[str, CalculatedLap] = {}
    for lap in laps:
        if not lap.circuit_name or lap.lap_time_minutes is None:
            continue
        current = best.get(lap.circuit_name)
        if current is None or lap.lap_time_minutes < current.lap_time_minutes:
            best[lap.circuit_name] = lap

    return [
        {
            "circuit_name": lap.circuit_name,
            "performed_on": lap.performed_on,
            "lap_time_minutes": lap.lap_time_minutes,
            "length": lap.length,
            "average_speed": lap.average_speed,
        }
        for lap in sorted(best.values(), key=lambda item: item.circuit_name or "")
    ]


def suggest_activity_classification(conn: sqlite3.Connection, raw_distance: float | None) -> dict[str, Any]:
    if raw_distance is None:
        return {"session_type": "unknown", "confidence": 0.0, "reason": "No raw distance was supplied."}

    calibration = active_calibration(conn)
    length_scale = float(calibration["length_scale"])
    circuits = conn.execute(
        "SELECT id, name, length FROM circuits WHERE active = 1 AND length IS NOT NULL"
    ).fetchall()
    best = None
    for circuit in circuits:
        target = device_distance_for_length(circuit["length"], length_scale)
        if target <= 0:
            continue
        pct_diff = abs(raw_distance - target) / target
        if best is None or pct_diff < best["pct_diff"]:
            best = {
                "circuit_id": int(circuit["id"]),
                "circuit_name": circuit["name"],
                "pct_diff": pct_diff,
                "target": target,
            }

    if best and best["pct_diff"] <= 0.03:
        return {
            "session_type": "lap",
            "circuit_id": best["circuit_id"],
            "confidence": max(0.0, 1 - best["pct_diff"]),
            "reason": f"Raw distance is within {best['pct_diff']:.1%} of {best['circuit_name']} target.",
        }
    if raw_distance > 0:
        if best:
            return {
                "session_type": "sprint",
                "confidence": 0.45,
                "reason": (
                    f"No circuit target was within 3% of the raw distance; closest was "
                    f"{best['circuit_name']} at {best['pct_diff']:.1%} away, so this is treated as a free-form sprint."
                ),
            }
        return {
            "session_type": "sprint",
            "confidence": 0.4,
            "reason": "No active circuit targets exist, so this is treated as a free-form sprint.",
        }
    return {
        "session_type": "unknown",
        "confidence": 0.0,
        "reason": "Raw distance was not usable for classification.",
    }


def _average(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)
