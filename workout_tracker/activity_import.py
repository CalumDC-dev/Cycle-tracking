"""Manual raw activity file import helpers."""

from __future__ import annotations

import csv
from datetime import datetime
import gzip
import io
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

from .activity_metrics import ActivitySample, analyse_activity_samples, parse_activity_time


SUPPORTED_SUFFIXES = {".csv", ".json", ".tcx", ".tcx.gz", ".zip"}


FIELD_ALIASES = {
    "source": [
        "source",
    ],
    "source_activity_id": [
        "source_activity_id",
        "activity id",
        "activity_id",
        "id",
        "external_id",
        "strava id",
    ],
    "title": [
        "title",
        "activity name",
        "name",
        "description",
    ],
    "started_on": [
        "started_on",
        "started at",
        "start time",
        "start_time",
        "start date",
        "start_date",
        "start date local",
        "start_date_local",
        "activity date",
        "date",
    ],
    "duration_seconds": [
        "duration_seconds",
        "duration",
        "elapsed time",
        "elapsed_time",
        "moving time",
        "moving_time",
        "time",
    ],
    "raw_distance": [
        "raw_distance",
        "distance",
        "distance km",
        "distance_km",
        "device distance",
        "device_distance",
    ],
    "hr": [
        "hr",
        "heart rate",
        "heartrate",
        "average heart rate",
        "average_heartrate",
        "average heart rate bpm",
    ],
    "raw_payload": [
        "raw_payload",
        "raw payload",
    ],
}


def load_activity_file(path: str | Path, source: str = "strava") -> list[dict[str, str]]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    if file_path.is_dir():
        archive_csv = file_path / "activities.csv"
        if archive_csv.exists():
            rows = _load_strava_archive_directory(file_path, source)
            return [row for row in (_normalize_row(row, source) for row in rows) if row is not None]
        rows: list[dict[str, str]] = []
        for child in sorted(file_path.rglob("*")):
            if child.is_file() and _is_supported_activity_path(child):
                rows.extend(load_activity_file(child, source))
        return rows
    if file_path.suffix.lower() == ".csv":
        rows = _load_csv(file_path)
    elif file_path.suffix.lower() == ".json":
        rows = _load_json(file_path)
    elif _is_tcx_path(file_path):
        rows = _load_tcx(file_path, source)
    elif file_path.suffix.lower() == ".zip":
        rows = _load_zip(file_path, source)
    else:
        raise ValueError("Activity imports support .csv, .json, .tcx, .tcx.gz, and .zip files.")
    return [row for row in (_normalize_row(row, source) for row in rows) if row is not None]


def _load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return _load_csv_rows(handle)


def _load_csv_text(text: str) -> list[dict[str, Any]]:
    return _load_csv_rows(io.StringIO(text))


def _load_csv_rows(handle: io.TextIOBase | io.StringIO) -> list[dict[str, Any]]:
    reader = csv.reader(handle)
    try:
        headers = next(reader)
    except StopIteration:
        return []
    deduped_headers = _dedupe_headers(headers)
    rows = []
    for row in reader:
        values = row + [""] * max(0, len(deduped_headers) - len(row))
        rows.append(dict(zip(deduped_headers, values)))
    return rows


def _dedupe_headers(headers: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    deduped = []
    for index, header in enumerate(headers):
        name = header or f"field_{index + 1}"
        counts[name] = counts.get(name, 0) + 1
        deduped.append(name if counts[name] == 1 else f"{name} {counts[name]}")
    return deduped


def _load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("activities") or payload.get("data") or payload.get("items") or []
    else:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("JSON activity file must contain a list of activities.")
    return [row for row in rows if isinstance(row, dict)]


def _load_tcx(path: Path, source: str) -> list[dict[str, Any]]:
    return _load_tcx_bytes(path.read_bytes(), path.name, source)


def _load_tcx_bytes(data: bytes, name: str, source: str) -> list[dict[str, Any]]:
    if name.lower().endswith(".gz"):
        data = gzip.decompress(data)
    root = ET.fromstring(data)
    return _load_tcx_root(root, _display_stem(name), source)


def _load_tcx_root(root: ET.Element, fallback_title: str, source: str) -> list[dict[str, Any]]:
    rows = []
    for activity in _children(root, "Activity"):
        activity_id = _child_text(activity, "Id")
        laps = list(_children(activity, "Lap"))
        duration = sum(_float(_child_text(lap, "TotalTimeSeconds")) or 0 for lap in laps)
        distance_m = sum(_float(_child_text(lap, "DistanceMeters")) or 0 for lap in laps)
        calories = sum(_float(_child_text(lap, "Calories")) or 0 for lap in laps)
        samples = _trackpoint_samples(activity)
        analysis = analyse_activity_samples(samples, duration_seconds=duration if duration else None)
        row: dict[str, Any] = {
            "source": source,
            "source_activity_id": activity_id or fallback_title,
            "title": fallback_title.replace("_", " "),
            "started_on": _start_time(activity, laps, activity_id),
            "duration_seconds": duration if duration else None,
            "raw_distance": distance_m / 1000 if distance_m else None,
            "hr": analysis.get("average_source_hr"),
            "raw_payload": json.dumps(
                {
                    "format": "tcx",
                    "sport": activity.attrib.get("Sport"),
                    "trackpoint_count": len(samples),
                    "calories": calories or None,
                    **analysis,
                },
                sort_keys=True,
            ),
        }
        rows.append(row)
    return rows


def _trackpoint_samples(activity: ET.Element) -> list[ActivitySample]:
    trackpoints = [node for node in activity.iter() if _tag_name(node) == "Trackpoint"]
    parsed_times = [parse_activity_time(_child_text(trackpoint, "Time")) for trackpoint in trackpoints]
    base_time = next((parsed for parsed in parsed_times if parsed is not None), None)
    samples = []
    for index, trackpoint in enumerate(trackpoints):
        parsed_time = parsed_times[index]
        if parsed_time is not None and base_time is not None:
            elapsed_seconds = (parsed_time - base_time).total_seconds()
        else:
            elapsed_seconds = float(index)
        samples.append(
            ActivitySample(
                elapsed_seconds=elapsed_seconds,
                watts=_float(_descendant_text(trackpoint, "Watts")),
                cadence=_float(_child_text(trackpoint, "Cadence")),
                speed_mps=_float(_descendant_text(trackpoint, "Speed")),
                hr=_float(_descendant_text(trackpoint, "HeartRateBpmValue")),
            )
        )
    return samples


def _load_zip(path: Path, source: str) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        names = {info.filename for info in archive.infolist() if not info.is_dir()}
        if "activities.csv" in names:
            return _load_strava_archive_zip(archive, source)
        rows = []
        for info in sorted((info for info in archive.infolist() if not info.is_dir()), key=lambda item: item.filename):
            if _is_tcx_name(info.filename):
                rows.extend(_load_tcx_bytes(archive.read(info.filename), info.filename, source))
            elif info.filename.lower().endswith(".json"):
                rows.extend(_load_json_payload(json.loads(archive.read(info.filename).decode("utf-8"))))
            elif info.filename.lower().endswith(".csv"):
                rows.extend(_load_csv_text(archive.read(info.filename).decode("utf-8-sig")))
        return rows


def _load_strava_archive_zip(archive: zipfile.ZipFile, source: str) -> list[dict[str, Any]]:
    metadata_rows = _load_csv_text(archive.read("activities.csv").decode("utf-8-sig"))
    names = {info.filename for info in archive.infolist() if not info.is_dir()}
    rows = []
    for metadata in metadata_rows:
        filename = _metadata_filename(metadata)
        activity_rows = []
        if filename in names and _is_tcx_name(filename):
            activity_rows = _load_tcx_bytes(archive.read(filename), filename, source)
        rows.extend(_merge_archive_rows(metadata, activity_rows, filename, source))
    return rows


def _load_strava_archive_directory(path: Path, source: str) -> list[dict[str, Any]]:
    metadata_rows = _load_csv(path / "activities.csv")
    rows = []
    for metadata in metadata_rows:
        filename = _metadata_filename(metadata)
        activity_rows = []
        if filename:
            activity_path = path / filename
            if activity_path.exists() and _is_tcx_path(activity_path):
                activity_rows = _load_tcx(activity_path, source)
        rows.extend(_merge_archive_rows(metadata, activity_rows, filename, source))
    return rows


def _load_json_payload(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("activities") or payload.get("data") or payload.get("items") or []
    else:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("JSON activity file must contain a list of activities.")
    return [row for row in rows if isinstance(row, dict)]


def _merge_archive_rows(
    metadata: dict[str, Any],
    activity_rows: list[dict[str, Any]],
    filename: str | None,
    source: str,
) -> list[dict[str, Any]]:
    if not activity_rows:
        return [_metadata_only_row(metadata, filename, source)]
    return [_merge_archive_row(metadata, activity_row, filename, source) for activity_row in activity_rows]


def _merge_archive_row(
    metadata: dict[str, Any],
    activity_row: dict[str, Any],
    filename: str | None,
    source: str,
) -> dict[str, Any]:
    merged = dict(activity_row)
    merged["source"] = source
    merged["source_activity_id"] = _metadata_value(metadata, "Activity ID") or activity_row.get("source_activity_id")
    merged["title"] = _metadata_value(metadata, "Activity Name") or activity_row.get("title")
    merged["raw_payload"] = _merge_payload(activity_row.get("raw_payload"), _archive_payload(metadata, filename))
    return merged


def _metadata_only_row(metadata: dict[str, Any], filename: str | None, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "source_activity_id": _metadata_value(metadata, "Activity ID"),
        "title": _metadata_value(metadata, "Activity Name"),
        "started_on": _metadata_value(metadata, "Activity Date") or _metadata_value(metadata, "Start Time"),
        "duration_seconds": _metadata_value(metadata, "Elapsed Time") or _metadata_value(metadata, "Moving Time"),
        "raw_distance": _metadata_value(metadata, "Distance"),
        "hr": _metadata_value(metadata, "Average Heart Rate") or _metadata_value(metadata, "Max Heart Rate"),
        "raw_payload": json.dumps(_archive_payload(metadata, filename), sort_keys=True),
    }


def _archive_payload(metadata: dict[str, Any], filename: str | None) -> dict[str, Any]:
    payload = {
        "archive_format": "strava_bulk_export",
        "activity_file": filename,
        "activity_type": _metadata_value(metadata, "Activity Type"),
        "csv_average_watts": _number_or_none(_metadata_value(metadata, "Average Watts")),
        "csv_max_watts": _number_or_none(_metadata_value(metadata, "Max Watts")),
        "csv_average_cadence": _number_or_none(_metadata_value(metadata, "Average Cadence")),
        "csv_max_cadence": _number_or_none(_metadata_value(metadata, "Max Cadence")),
        "csv_average_speed_mps": _number_or_none(_metadata_value(metadata, "Average Speed")),
        "csv_max_speed_mps": _number_or_none(_metadata_value(metadata, "Max Speed")),
        "csv_weighted_average_power": _number_or_none(_metadata_value(metadata, "Weighted Average Power")),
        "csv_training_load": _number_or_none(_metadata_value(metadata, "Training Load")),
        "csv_intensity": _number_or_none(_metadata_value(metadata, "Intensity")),
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def _merge_payload(existing_payload: object, extra: dict[str, Any]) -> str:
    payload: dict[str, Any] = {}
    if existing_payload:
        try:
            decoded = json.loads(str(existing_payload))
        except (TypeError, ValueError):
            decoded = {}
        if isinstance(decoded, dict):
            payload.update(decoded)
    payload.update(extra)
    return json.dumps(payload, sort_keys=True)


def _normalize_row(row: dict[str, Any], source: str) -> dict[str, str] | None:
    lookup = {_clean_key(key): value for key, value in row.items()}
    normalized = {
        "source": _find_value(lookup, "source") or source,
        "source_activity_id": _find_value(lookup, "source_activity_id"),
        "title": _find_value(lookup, "title"),
        "started_on": _date_text(_find_value(lookup, "started_on")),
        "duration_seconds": _duration_value(_find_value(lookup, "duration_seconds")),
        "raw_distance": _number_text(_find_value(lookup, "raw_distance")),
        "hr": _number_text(_find_value(lookup, "hr")),
        "raw_payload": _find_value(lookup, "raw_payload"),
    }
    if not any(normalized.get(key) for key in ("source_activity_id", "started_on", "duration_seconds", "raw_distance")):
        return None
    return {key: value for key, value in normalized.items() if value not in (None, "")}


def _find_value(lookup: dict[str, Any], target: str) -> str | None:
    for alias in FIELD_ALIASES[target]:
        value = lookup.get(_clean_key(alias))
        if value not in (None, ""):
            return str(value).strip()
    return None


def _duration_value(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if ":" not in text:
        return _number_text(text)
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return str(seconds)


def _number_text(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    try:
        return f"{float(text):g}"
    except ValueError:
        return None


def _number_or_none(value: str | None) -> float | None:
    text = _number_text(value)
    return float(text) if text is not None else None


def _date_text(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if "T" in text or _looks_like_iso_date(text):
        return text
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%B %d, %Y, %I:%M:%S %p", "%b %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M %p"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return text


def _looks_like_iso_date(value: str) -> bool:
    return len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-"


def _clean_key(value: str) -> str:
    return str(value).strip().lower().replace("-", " ").replace("_", " ")


def _metadata_value(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value not in (None, ""):
        return str(value).strip()
    return None


def _metadata_filename(metadata: dict[str, Any]) -> str | None:
    filename = _metadata_value(metadata, "Filename")
    if not filename:
        return None
    return filename.replace("\\", "/")


def _is_supported_activity_path(path: Path) -> bool:
    return any(str(path).lower().endswith(suffix) for suffix in SUPPORTED_SUFFIXES)


def _is_tcx_path(path: Path) -> bool:
    return _is_tcx_name(str(path))


def _is_tcx_name(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(".tcx") or lower.endswith(".tcx.gz")


def _display_stem(name: str) -> str:
    base = Path(name).name
    lower = base.lower()
    for suffix in (".tcx.gz", ".tcx"):
        if lower.endswith(suffix):
            return base[: -len(suffix)]
    return Path(base).stem


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in node.iter() if _tag_name(child) == name]


def _child_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if _tag_name(child) == name:
            return _text(child)
    return None


def _text(node: ET.Element) -> str | None:
    return node.text.strip() if node.text else None


def _descendant_text(node: ET.Element, name: str) -> str | None:
    if name == "HeartRateBpmValue":
        for child in node.iter():
            if _tag_name(child) == "HeartRateBpm":
                return _child_text(child, "Value")
        return None
    for child in node.iter():
        if child is not node and _tag_name(child) == name:
            return _text(child)
    return None


def _tag_name(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def _average(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


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


def _start_time(activity: ET.Element, laps: list[ET.Element], activity_id: str | None) -> str | None:
    if laps and laps[0].attrib.get("StartTime"):
        return laps[0].attrib["StartTime"]
    return activity_id
