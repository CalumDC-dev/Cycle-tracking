"""Derived metrics for imported activity source data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import sqlite3
from typing import Any


PEAK_WINDOWS = (5, 30, 60, 300)


@dataclass(frozen=True)
class ActivitySample:
    elapsed_seconds: float
    watts: float | None = None
    cadence: float | None = None
    speed_mps: float | None = None
    hr: float | None = None


def analyse_activity_samples(
    samples: list[ActivitySample],
    *,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Return compact, source-agnostic metrics for trackpoint samples."""

    ordered = sorted(samples, key=lambda sample: sample.elapsed_seconds)
    metrics: dict[str, Any] = {
        "analysis_version": 1,
        "sample_count": len(ordered),
        "sample_duration_seconds": _sample_duration(ordered, duration_seconds),
        **_metric_summary("watts", [sample.watts for sample in ordered]),
        **_metric_summary("cadence", [sample.cadence for sample in ordered]),
        **_metric_summary("speed_mps", [sample.speed_mps for sample in ordered]),
        **_metric_summary("source_hr", [sample.hr for sample in ordered]),
    }

    for window in PEAK_WINDOWS:
        metrics[f"best_{window}s_watts"] = _best_window_average(ordered, "watts", window)
    for window in (5, 30, 60):
        metrics[f"best_{window}s_cadence"] = _best_window_average(ordered, "cadence", window)

    metrics["watts_variability_pct"] = _variability_pct([sample.watts for sample in ordered])
    metrics["cadence_variability_pct"] = _variability_pct([sample.cadence for sample in ordered])
    metrics["speed_variability_pct"] = _variability_pct([sample.speed_mps for sample in ordered])
    metrics["data_quality_flags"] = _data_quality_flags(ordered)
    return {key: value for key, value in metrics.items() if value not in (None, [], {})}


def source_metric_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT r.id, r.source, r.source_activity_id, r.title, r.started_on,
               r.duration_seconds, r.raw_distance, r.hr, r.review_status,
               r.session_type, r.raw_payload, c.name AS circuit_name,
               COALESCE(
                   (SELECT s.resistance FROM sprint_entries s WHERE s.raw_activity_id = r.id LIMIT 1),
                   (SELECT l.resistance FROM lap_entries l WHERE l.raw_activity_id = r.id LIMIT 1),
                   CASE WHEN r.duplicate_entry_type = 'sprint'
                        THEN (SELECT s.resistance FROM sprint_entries s WHERE s.id = r.duplicate_entry_id)
                   END,
                   CASE WHEN r.duplicate_entry_type = 'lap'
                        THEN (SELECT l.resistance FROM lap_entries l WHERE l.id = r.duplicate_entry_id)
                   END,
                   4
               ) AS resistance,
               rs.scaling AS resistance_scaling
        FROM raw_activities r
        LEFT JOIN circuits c ON c.id = r.circuit_id
        LEFT JOIN resistance_scaling rs ON rs.resistance = COALESCE(
            (SELECT s.resistance FROM sprint_entries s WHERE s.raw_activity_id = r.id LIMIT 1),
            (SELECT l.resistance FROM lap_entries l WHERE l.raw_activity_id = r.id LIMIT 1),
            CASE WHEN r.duplicate_entry_type = 'sprint'
                 THEN (SELECT s.resistance FROM sprint_entries s WHERE s.id = r.duplicate_entry_id)
            END,
            CASE WHEN r.duplicate_entry_type = 'lap'
                 THEN (SELECT l.resistance FROM lap_entries l WHERE l.id = r.duplicate_entry_id)
            END,
            4
        )
        WHERE r.raw_payload IS NOT NULL AND r.raw_payload != ''
        ORDER BY r.started_on DESC, r.imported_at DESC, r.id DESC
        """
    ).fetchall()
    output = []
    for row in rows:
        payload = payload_dict(row["raw_payload"])
        if not has_source_metrics(payload):
            continue
        scale = _float_or_none(row["resistance_scaling"])
        output.append(
            {
                "id": row["id"],
                "source": row["source"],
                "source_activity_id": row["source_activity_id"],
                "title": row["title"],
                "started_on": row["started_on"],
                "session_type": row["session_type"],
                "circuit": row["circuit_name"],
                "review_status": row["review_status"],
                "duration_seconds": row["duration_seconds"],
                "raw_distance": row["raw_distance"],
                "hr": row["hr"],
                "resistance": row["resistance"],
                "resistance_scaling": row["resistance_scaling"],
                "calories": payload.get("calories"),
                "average_watts": scaled_metric(payload.get("average_watts"), scale),
                "max_watts": scaled_metric(payload.get("max_watts"), scale),
                "best_5s_watts": scaled_metric(payload.get("best_5s_watts"), scale),
                "best_30s_watts": scaled_metric(payload.get("best_30s_watts"), scale),
                "best_60s_watts": scaled_metric(payload.get("best_60s_watts"), scale),
                "best_300s_watts": scaled_metric(payload.get("best_300s_watts"), scale),
                "device_average_watts": payload.get("average_watts"),
                "device_max_watts": payload.get("max_watts"),
                "device_best_5s_watts": payload.get("best_5s_watts"),
                "device_best_30s_watts": payload.get("best_30s_watts"),
                "device_best_60s_watts": payload.get("best_60s_watts"),
                "device_best_300s_watts": payload.get("best_300s_watts"),
                "watts_variability_pct": payload.get("watts_variability_pct"),
                "average_cadence": payload.get("average_cadence"),
                "max_cadence": payload.get("max_cadence"),
                "best_30s_cadence": payload.get("best_30s_cadence"),
                "cadence_variability_pct": payload.get("cadence_variability_pct"),
                "average_speed_mps": payload.get("average_speed_mps"),
                "max_speed_mps": payload.get("max_speed_mps"),
                "speed_variability_pct": payload.get("speed_variability_pct"),
                "sample_count": payload.get("sample_count") or payload.get("trackpoint_count"),
                "sample_duration_seconds": payload.get("sample_duration_seconds"),
                "data_quality_flags": "; ".join(payload.get("data_quality_flags", []))
                if isinstance(payload.get("data_quality_flags"), list)
                else payload.get("data_quality_flags"),
            }
        )
    return output


def scaled_metric(value: object, scale: float | None) -> float | None:
    raw = _float_or_none(value)
    if raw is None or scale is None:
        return None
    return raw * scale


def payload_dict(raw_payload: object) -> dict[str, Any]:
    if raw_payload in (None, ""):
        return {}
    try:
        payload = json.loads(str(raw_payload))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def has_source_metrics(payload: dict[str, Any]) -> bool:
    return any(
        payload.get(key) is not None
        for key in (
            "average_watts",
            "average_cadence",
            "average_speed_mps",
            "best_5s_watts",
            "csv_average_watts",
            "csv_average_cadence",
        )
    )


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_activity_time(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sample_duration(samples: list[ActivitySample], duration_seconds: float | None) -> float | None:
    if duration_seconds and duration_seconds > 0:
        return duration_seconds
    if not samples:
        return None
    return max(sample.elapsed_seconds for sample in samples) - min(sample.elapsed_seconds for sample in samples)


def _metric_summary(name: str, values: list[float | None]) -> dict[str, float | None]:
    clean = [value for value in values if value is not None]
    if not clean:
        return {
            f"min_{name}": None,
            f"average_{name}": None,
            f"max_{name}": None,
        }
    return {
        f"min_{name}": min(clean),
        f"average_{name}": sum(clean) / len(clean),
        f"max_{name}": max(clean),
    }


def _variability_pct(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if len(clean) < 2:
        return None
    average = sum(clean) / len(clean)
    if average == 0:
        return None
    variance = sum((value - average) ** 2 for value in clean) / len(clean)
    return math.sqrt(variance) / average * 100


def _best_window_average(samples: list[ActivitySample], metric: str, window_seconds: int) -> float | None:
    series = _second_series(samples, metric)
    if len(series) < window_seconds:
        return None
    prefix = [0.0]
    for value in series:
        prefix.append(prefix[-1] + value)
    best = None
    for index in range(0, len(series) - window_seconds + 1):
        total = prefix[index + window_seconds] - prefix[index]
        average = total / window_seconds
        if best is None or average > best:
            best = average
    return best


def _second_series(samples: list[ActivitySample], metric: str) -> list[float]:
    values = [
        (max(0, int(round(sample.elapsed_seconds))), getattr(sample, metric))
        for sample in samples
        if getattr(sample, metric) is not None
    ]
    if not values:
        return []
    values.sort(key=lambda item: item[0])
    series = []
    for index, (second, value) in enumerate(values):
        next_second = values[index + 1][0] if index + 1 < len(values) else second + 1
        repeat = max(1, next_second - second)
        series.extend([float(value)] * repeat)
    return series


def _data_quality_flags(samples: list[ActivitySample]) -> list[str]:
    flags = []
    if not samples:
        return ["no_trackpoints"]
    if not any(sample.watts is not None for sample in samples):
        flags.append("no_watts")
    if not any(sample.cadence is not None for sample in samples):
        flags.append("no_cadence")
    if not any(sample.hr is not None for sample in samples):
        flags.append("missing_source_hr")
    gaps = [
        samples[index + 1].elapsed_seconds - sample.elapsed_seconds
        for index, sample in enumerate(samples[:-1])
        if samples[index + 1].elapsed_seconds - sample.elapsed_seconds > 5
    ]
    if gaps:
        flags.append("trackpoint_gaps")
    return flags
