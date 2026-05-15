"""Standard-library local web UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.parser import BytesParser
from email import policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
import hashlib
import tempfile
from urllib.parse import parse_qs, urlparse
import json
import sqlite3

from .activity_import import load_activity_file
from .activity_metrics import source_metric_rows
from .calculations import (
    calculated_laps,
    calculated_sprints,
    dashboard_metrics,
    daily_summary,
    device_distance_for_length,
    estimated_mechanical_watts_from_hr,
    estimated_watts_from_hr,
    mass_for_date,
    suggest_activity_classification,
)
from .database import connect, init_db
from .exporter import backup_bundle_bytes, backup_filename, csv_text


CSS = """
:root {
  color-scheme: light;
  --ink: #17202a;
  --muted: #5f6b7a;
  --line: #d9e2ec;
  --panel: #ffffff;
  --soft: #f5f7fa;
  --blue: #1f5a85;
  --green: #2f7d59;
  --amber: #a66200;
  --red: #a33b3b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font: 15px/1.45 "Segoe UI", Arial, sans-serif;
  color: var(--ink);
  background: var(--soft);
}
header {
  background: var(--blue);
  color: #fff;
  padding: 18px 28px 12px;
}
header h1 {
  margin: 0 0 12px;
  font-size: 24px;
  letter-spacing: 0;
}
nav {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
nav a {
  color: #fff;
  text-decoration: none;
  border: 1px solid rgba(255,255,255,.36);
  padding: 7px 10px;
  border-radius: 6px;
  min-width: 86px;
  text-align: center;
}
nav a.active, nav a:hover { background: rgba(255,255,255,.18); }
main {
  max-width: 1260px;
  margin: 0 auto;
  padding: 22px;
}
.band {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 18px;
}
.band h2 {
  margin: 0 0 12px;
  font-size: 18px;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}
.metric {
  border: 1px solid var(--line);
  border-left: 5px solid var(--blue);
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  min-height: 86px;
}
.metric.green { border-left-color: var(--green); }
.metric.amber { border-left-color: var(--amber); }
.metric.red { border-left-color: var(--red); }
.metric span {
  color: var(--muted);
  display: block;
  font-size: 12px;
  text-transform: uppercase;
}
.metric strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
  line-height: 1.15;
}
.grid-two {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 16px;
}
svg.chart {
  width: 100%;
  height: 220px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
svg.chart-large {
  aspect-ratio: 3 / 2;
  height: auto;
  min-height: 300px;
}
.chart-panel {
  display: grid;
  gap: 8px;
}
.chart-panel:has(details[open]) {
  grid-column: 1 / -1;
}
.chart-panel details {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  padding: 8px;
}
.chart-panel summary {
  cursor: pointer;
  color: var(--blue);
  font-weight: 700;
  margin-bottom: 8px;
}
table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
}
th, td {
  border-bottom: 1px solid var(--line);
  padding: 8px 9px;
  text-align: left;
  vertical-align: top;
}
th {
  background: #eaf1f7;
  font-weight: 700;
}
tr:hover td { background: #fbfcfe; }
tr.day-group-a td { background: #fff; }
tr.day-group-b td { background: #f3f8fc; }
tr.day-start td { border-top: 2px solid #bdcbd9; }
tr.day-group-a:hover td, tr.day-group-b:hover td { background: #eef5fb; }
form.inline {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 100px 120px 74px 86px;
  gap: 7px;
  align-items: center;
}
form.stack {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
  align-items: end;
}
label {
  display: grid;
  gap: 4px;
  color: var(--muted);
  font-size: 12px;
}
input, select, button {
  font: inherit;
  border: 1px solid #c8d3df;
  border-radius: 6px;
  padding: 8px 9px;
  background: #fff;
  min-height: 38px;
}
button {
  border-color: var(--blue);
  color: #fff;
  background: var(--blue);
  cursor: pointer;
}
button.secondary {
  border-color: #8091a5;
  color: var(--ink);
  background: #f8fafc;
}
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.actions a {
  border: 1px solid var(--line);
  color: var(--blue);
  text-decoration: none;
  background: #fff;
  padding: 8px 10px;
  border-radius: 6px;
}
.muted { color: var(--muted); }
.table-scroll {
  overflow-x: auto;
}
.table-scroll table {
  min-width: 980px;
}
.entry-table {
  min-width: 1220px;
}
.entry-table input,
.entry-table select {
  width: 100%;
  min-width: 72px;
  min-height: 34px;
  padding: 6px 7px;
}
.entry-table input[type="date"] {
  min-width: 132px;
}
.entry-table input[type="datetime-local"] {
  min-width: 168px;
}
.entry-table .narrow {
  min-width: 62px;
}
.entry-table .readonly-cell {
  color: var(--muted);
  white-space: nowrap;
}
.entry-table .actions-cell {
  min-width: 76px;
}
.entry-table button {
  min-height: 34px;
  padding: 6px 10px;
}
.empty {
  color: var(--muted);
  padding: 18px;
  background: #fff;
  border: 1px dashed #b8c4d0;
  border-radius: 8px;
}
@media (max-width: 720px) {
  main { padding: 14px; }
  form.inline { grid-template-columns: 1fr; }
  svg.chart-large { min-height: 360px; }
  table { font-size: 13px; }
}
"""

STRONG_DUPLICATE_THRESHOLD = 0.85
POSSIBLE_DUPLICATE_THRESHOLD = 0.6


@dataclass(frozen=True)
class UploadedFile:
    filename: str
    content: bytes


FormValue = str | UploadedFile


def serve(db_path: str | Path, host: str = "127.0.0.1", port: int = 8000) -> None:
    handler = type("WorkoutHandler", (WorkoutRequestHandler,), {"db_path": Path(db_path)})
    server = ThreadingHTTPServer((host, port), handler)
    try:
        print(f"Serving workout tracker on http://{host}:{port}", flush=True)
    except (AttributeError, OSError, RuntimeError):
        pass
    server.serve_forever()


class WorkoutRequestHandler(BaseHTTPRequestHandler):
    db_path = Path("data/workout_tracker.sqlite")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        conn = None
        try:
            if parsed.path == "/":
                conn = self._conn()
                self._html("Dashboard", render_dashboard(conn), "dashboard")
            elif parsed.path == "/entries":
                conn = self._conn()
                self._html("Entries", render_entries(conn), "entries")
            elif parsed.path == "/circuits":
                conn = self._conn()
                self._html("Circuits", render_circuits(conn), "circuits")
            elif parsed.path == "/calibration":
                conn = self._conn()
                self._html("Calibration", render_calibration(conn), "calibration")
            elif parsed.path == "/maintenance":
                conn = self._conn()
                self._html("Maintenance", render_maintenance(conn), "maintenance")
            elif parsed.path == "/insights":
                conn = self._conn()
                self._html("Insights", render_insights(conn), "insights")
            elif parsed.path == "/review":
                conn = self._conn()
                self._html("Review", render_review(conn), "review")
            elif parsed.path.startswith("/export/"):
                self._csv_export(parsed.path)
            elif parsed.path == "/health":
                self._text("ok")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, explain=str(exc))
        finally:
            if conn is not None:
                conn.close()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        params = self._post_params()
        conn = None
        try:
            conn = self._conn()
            if parsed.path == "/circuits/update":
                update_circuit(conn, params)
                self._redirect("/circuits")
            elif parsed.path == "/circuits/add":
                add_circuit(conn, params)
                self._redirect("/circuits")
            elif parsed.path == "/review/add":
                add_raw_activity(conn, params)
                self._redirect("/review")
            elif parsed.path == "/review/import-file":
                import_activity_file_to_review(conn, params)
                self._redirect("/review")
            elif parsed.path == "/review/classify":
                classify_activity(conn, params)
                self._redirect("/review")
            elif parsed.path == "/review/confirm-duplicate":
                confirm_duplicate_activity(conn, params)
                self._redirect("/review")
            elif parsed.path == "/maintenance/not-duplicate":
                dismiss_duplicate_pair(conn, params)
                self._redirect("/maintenance")
            elif parsed.path == "/review/promote":
                promote_raw_activity(conn, params)
                self._redirect("/review")
            elif parsed.path == "/entries/sprint/add":
                add_sprint_entry(conn, params)
                self._redirect("/entries")
            elif parsed.path == "/entries/sprint/update":
                update_sprint_entry(conn, params)
                self._redirect("/entries")
            elif parsed.path == "/entries/lap/add":
                add_lap_entry(conn, params)
                self._redirect("/entries")
            elif parsed.path == "/entries/lap/update":
                update_lap_entry(conn, params)
                self._redirect("/entries")
            elif parsed.path == "/entries/delete":
                delete_entry(conn, params)
                self._redirect("/maintenance")
            elif parsed.path == "/calibration/profile/update":
                update_calibration_profile(conn, params)
                self._redirect("/calibration")
            elif parsed.path == "/calibration/resistance/update":
                update_resistance_scaling(conn, params)
                self._redirect("/calibration")
            elif parsed.path == "/calibration/test/preview":
                preview = calculate_resistance_calibration_preview(conn, params)
                self._html("Calibration", render_calibration(conn, preview), "calibration")
            elif parsed.path == "/calibration/test/apply":
                add_resistance_calibration_test(conn, params)
                self._redirect("/calibration")
            elif parsed.path == "/calibration/mass/add":
                add_mass_log(conn, params)
                self._redirect("/calibration")
            elif parsed.path == "/calibration/mass/update":
                update_mass_log(conn, params)
                self._redirect("/calibration")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, explain=str(exc))
        finally:
            if conn is not None:
                conn.close()

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _conn(self) -> sqlite3.Connection:
        conn = connect(self.db_path)
        init_db(conn)
        return conn

    def _post_params(self) -> dict[str, FormValue]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        return parse_post_params(self.headers.get("Content-Type", ""), body)

    def _html(self, title: str, body: str, active: str) -> None:
        content = page(title, body, active)
        encoded = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _text(self, text: str) -> None:
        encoded = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _csv_export(self, path: str) -> None:
        conn = self._conn()
        try:
            if path == "/export/backup.zip":
                encoded = backup_bundle_bytes(conn)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{backup_filename()}"')
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            routes = {
                "/export/daily_summary.csv": daily_summary(conn),
                "/export/sprints.csv": [sprint.__dict__ for sprint in calculated_sprints(conn)],
                "/export/laps.csv": [lap.__dict__ for lap in calculated_laps(conn)],
                "/export/circuits.csv": [dict(row) for row in conn.execute("SELECT * FROM circuits ORDER BY name").fetchall()],
                "/export/raw_activities.csv": [
                    dict(row)
                    for row in conn.execute("SELECT * FROM raw_activities ORDER BY imported_at DESC, id DESC").fetchall()
                ],
                "/export/source_metrics.csv": source_metric_rows(conn),
            }
            if path not in routes:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            encoded = csv_text(routes[path]).encode("utf-8")
            filename = path.rsplit("/", 1)[-1]
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        finally:
            conn.close()


def page(title: str, body: str, active: str) -> str:
    nav = [
        ("dashboard", "/", "Dashboard"),
        ("entries", "/entries", "Entries"),
        ("circuits", "/circuits", "Circuits"),
        ("calibration", "/calibration", "Calibration"),
        ("maintenance", "/maintenance", "Maintenance"),
        ("insights", "/insights", "Insights"),
        ("review", "/review", "Review"),
    ]
    links = "".join(
        f'<a class="{ "active" if key == active else "" }" href="{href}">{label}</a>'
        for key, href, label in nav
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Workout Tracker</title>
  <style>{CSS}</style>
</head>
<body>
  <header>
    <h1>Workout Tracker</h1>
    <nav>{links}</nav>
  </header>
  <main>{body}</main>
</body>
</html>"""


def render_dashboard(conn: sqlite3.Connection) -> str:
    metrics = dashboard_metrics(conn)
    daily = metrics["daily"]
    source_rows = source_metric_rows(conn)
    calories = [(row["date"], row["total_calories"]) for row in daily]
    watts = [(row["date"], row["average_watts"] or 0) for row in daily]
    mass = [(row["measured_on"], row["mass_kg"]) for row in metrics["mass"]]
    source_average_watts = source_metric_points(source_rows, "average_watts")
    source_peak_watts = source_metric_points(source_rows, "best_300s_watts")
    source_cadence = source_metric_points(source_rows, "average_cadence")
    source_variability = source_metric_points(source_rows, "watts_variability_pct")
    return f"""
<section class="band">
  <h2>Overview</h2>
  <div class="metrics">
    {metric("Workout days", metrics["workout_days"], "green")}
    {metric("Total distance", fmt_num(metrics["total_distance"], 2), "green")}
    {metric("Total calories", fmt_num(metrics["total_calories"], 0), "amber")}
    {metric("Workout time", fmt_minutes(metrics["total_minutes"]), "blue")}
    {metric("Sprints", metrics["sprint_count"], "blue")}
    {metric("Laps", metrics["lap_count"], "blue")}
    {metric("Avg watts", fmt_num(metrics["average_watts"], 1), "amber")}
    {metric("Mass change", signed_num(metrics["mass_change"], 2), "red")}
    {metric("Best lap", best_lap(metrics), "green")}
  </div>
</section>
<section class="band">
  <h2>Source Metrics</h2>
  <div class="metrics">
    {metric("Metric sessions", len(source_rows), "blue")}
    {metric("Best 5 min est watts", fmt_num(max_metric(source_rows, "best_300s_watts"), 0), "amber")}
    {metric("Best 60 sec est watts", fmt_num(max_metric(source_rows, "best_60s_watts"), 0), "amber")}
    {metric("Best avg cadence", fmt_num(max_metric(source_rows, "average_cadence"), 0), "green")}
  </div>
</section>
<section class="band">
  <h2>Trends</h2>
  <div class="grid-two">
    {line_chart("Calories", calories, "#a66200")}
    {line_chart("Average Watts", watts, "#1f5a85")}
    {line_chart("Mass", mass, "#2f7d59")}
  </div>
</section>
<section class="band">
  <h2>Source Metric Trends</h2>
  <div class="grid-two">
    {line_chart("Estimated Average Watts", source_average_watts, "#1f5a85")}
    {line_chart("Best 5 Minute Estimated Watts", source_peak_watts, "#a66200")}
    {line_chart("Average Cadence", source_cadence, "#2f7d59")}
    {line_chart("Watts Variability", source_variability, "#a33b3b")}
  </div>
</section>
<section class="band">
  <h2>Best Lap By Circuit</h2>
  {best_laps_table(metrics["best_laps_by_circuit"])}
</section>
<section class="band">
  <h2>Recent Source Metrics</h2>
  {source_metrics_table(source_rows[:12])}
</section>
<section class="band">
  <h2>Daily Summary</h2>
  {daily_table(daily)}
</section>
<section class="band">
  <h2>Exports</h2>
  <div class="actions">
    <a href="/export/backup.zip">Backup bundle ZIP</a>
    <a href="/export/daily_summary.csv">Daily summary CSV</a>
    <a href="/export/sprints.csv">Sprints CSV</a>
    <a href="/export/laps.csv">Laps CSV</a>
    <a href="/export/circuits.csv">Circuits CSV</a>
    <a href="/export/raw_activities.csv">Raw activities CSV</a>
    <a href="/export/source_metrics.csv">Source metrics CSV</a>
  </div>
</section>
"""


def render_entries(conn: sqlite3.Connection) -> str:
    sprints = calculated_sprints(conn)
    laps = calculated_laps(conn)
    circuits = circuit_rows_with_goals(conn)
    return f"""
<section class="band">
  <h2>Add Sprint Entry</h2>
  <form class="stack" method="post" action="/entries/sprint/add">
    <label>Date<input name="performed_on" type="date" required></label>
    <label>Start time<input name="started_at" type="time"></label>
    <label>Day number<input name="day_number" type="number" min="1"></label>
    <label>Sprint number<input name="sprint_index" type="number" min="1"></label>
    <label>Duration minutes<input name="duration_minutes" type="number" step="0.001" min="0"></label>
    <label>RPM<input name="rpm" type="number" step="0.1" min="0"></label>
    <label>Device watts<input name="device_watts" type="number" step="0.1" min="0"></label>
    <label>HR<input name="hr" type="number" min="0"></label>
    <label>Resistance<select name="resistance">{resistance_select_options(4)}</select></label>
    <label>Device distance<input name="device_distance" type="number" step="0.001" min="0"></label>
    <label>Notes<input name="notes"></label>
    <button type="submit">Add sprint</button>
  </form>
</section>
<section class="band">
  <h2>Add Lap Entry</h2>
  <form class="stack" method="post" action="/entries/lap/add">
    <label>Date<input name="performed_on" type="date" required></label>
    <label>Start time<input name="started_at" type="time"></label>
    <label>Lap number<input name="lap_index" type="number" min="1"></label>
    <label>Circuit<select name="circuit_id" required id="lap-circuit">{circuit_select_options(circuits)}</select></label>
    <label>Kinomap goal<input id="lap-goal" readonly></label>
    <label>Lap time<input name="lap_time_minutes" placeholder="1:30"></label>
    <label>HR<input name="hr" type="number" min="0"></label>
    <label>Resistance<select name="resistance">{resistance_select_options(4)}</select></label>
    <label>RPM<input name="rpm" type="number" step="0.1" min="0"></label>
    <label>Notes<input name="notes"></label>
    <button type="submit">Add lap</button>
  </form>
  {circuit_goal_script()}
</section>
<section class="band">
  <h2>Sprint Entries</h2>
  {render_sprint_entries_table(sprints)}
</section>
<section class="band">
  <h2>Lap Entries</h2>
  {render_lap_entries_table(laps, circuits)}
</section>
"""


def render_sprint_entries_table(sprints: list[object]) -> str:
    forms: list[str] = []
    rows: list[tuple[object, list[str], str]] = []
    for sprint in sprints:
        form_id = f"sprint-edit-{sprint.id}"
        forms.append(entry_form(form_id, "/entries/sprint/update", sprint.id))
        rows.append(
            (
                sprint.performed_on,
                [
                    entry_input(form_id, "performed_on", sprint.performed_on, input_type="date", required=True),
                    entry_input(form_id, "started_at", time_input_value(sprint.started_at), input_type="time"),
                    entry_input(form_id, "sprint_index", fmt_raw(sprint.sprint_index), input_type="number", min_value="1", css_class="narrow"),
                    entry_input(
                        form_id,
                        "duration_minutes",
                        step_value(sprint.duration_minutes, 3),
                        input_type="number",
                        step="0.001",
                        min_value="0",
                    ),
                    entry_input(form_id, "rpm", fmt_raw(sprint.rpm), input_type="number", step="0.1", min_value="0"),
                    entry_input(
                        form_id,
                        "device_watts",
                        fmt_raw(sprint.device_watts),
                        input_type="number",
                        step="0.1",
                        min_value="0",
                    ),
                    readonly_cell(fmt_num(sprint.estimated_watts, 1)),
                    entry_input(form_id, "hr", fmt_raw(sprint.hr), input_type="number", min_value="0", css_class="narrow"),
                    entry_select(form_id, "resistance", resistance_select_options(entry_resistance_value(sprint.resistance))),
                    entry_input(
                        form_id,
                        "device_distance",
                        fmt_raw(sprint.device_distance),
                        input_type="number",
                        step="0.001",
                        min_value="0",
                    ),
                    readonly_cell(fmt_num(sprint.calibrated_distance, 2)),
                    readonly_cell(fmt_num(sprint.calories_mets, 1)),
                    save_button(form_id),
                ],
                f"sprint-{sprint.id}",
            )
        )
    return "".join(forms) + grouped_html_table(
        [
            "Date",
            "Start",
            "Sprint",
            "Time",
            "RPM",
            "Device watts",
            "Estimated watts",
            "HR",
            "Resistance",
            "Device distance",
            "Cal distance",
            "Calories (HR/MET)",
            "",
        ],
        rows,
    )


def render_lap_entries_table(laps: list[object], circuits: list[dict[str, object]]) -> str:
    forms: list[str] = []
    rows: list[tuple[object, list[str], str]] = []
    for lap in laps:
        form_id = f"lap-edit-{lap.id}"
        forms.append(entry_form(form_id, "/entries/lap/update", lap.id))
        rows.append(
            (
                lap.performed_on,
                [
                    entry_input(form_id, "performed_on", lap.performed_on, input_type="date", required=True),
                    entry_input(form_id, "started_at", time_input_value(lap.started_at), input_type="time"),
                    entry_input(form_id, "lap_index", fmt_raw(lap.lap_index), input_type="number", min_value="1", css_class="narrow"),
                    entry_select(form_id, "circuit_id", circuit_select_options(circuits, lap.circuit_id), required=True),
                    entry_input(form_id, "lap_time_minutes", duration_entry_value(lap.lap_time_minutes)),
                    readonly_cell(fmt_num(lap.length, 3)),
                    readonly_cell(fmt_num(lap.average_speed, 2)),
                    entry_input(form_id, "hr", fmt_raw(lap.hr), input_type="number", min_value="0", css_class="narrow"),
                    entry_select(form_id, "resistance", resistance_select_options(entry_resistance_value(lap.resistance))),
                    entry_input(form_id, "rpm", fmt_raw(lap.rpm), input_type="number", step="0.1", min_value="0"),
                    readonly_cell(fmt_num(lap.calories_mets, 1)),
                    save_button(form_id),
                ],
                f"lap-{lap.id}",
            )
        )
    return "".join(forms) + grouped_html_table(
        ["Date", "Start", "Lap", "Circuit", "Lap time", "Length", "Avg speed", "HR", "Resistance", "RPM", "Calories (HR/MET)", ""],
        rows,
    )


def render_circuits(conn: sqlite3.Connection) -> str:
    rows = circuit_rows_with_goals(conn, include_inactive=True)
    body = []
    for row in rows:
        checked = "checked" if row["active"] else ""
        body.append(f"""
<form class="inline" method="post" action="/circuits/update">
  <input type="hidden" name="id" value="{row['id']}">
  <input name="name" value="{escape(str(row['name']))}" aria-label="Circuit name">
  <input name="length" value="{fmt_raw(row['length'])}" aria-label="Length">
  <input value="{fmt_raw(row['calculated_device_distance'])}" aria-label="Kinomap goal" readonly>
  <label><span>Active</span><input type="checkbox" name="active" value="1" {checked}></label>
  <button type="submit">Save</button>
</form>""")
    return f"""
<section class="band">
  <h2>Add Circuit</h2>
  <form class="stack" method="post" action="/circuits/add">
    <label>Circuit name<input name="name" required></label>
    <label>Real length<input name="length" type="number" step="0.001" required></label>
    <button type="submit">Add circuit</button>
  </form>
</section>
<section class="band">
  <h2>Circuits</h2>
  <div class="muted">Kinomap goal is calculated from real circuit length divided by the active length scale.</div>
  <div style="display:grid; gap:8px; margin-top:12px;">{''.join(body)}</div>
</section>
"""


def render_calibration(conn: sqlite3.Connection, preview: dict[str, object] | None = None) -> str:
    profile = editable_calibration_profile(conn)
    resistance_rows = resistance_scaling_rows(conn)
    mass_rows = conn.execute("SELECT id, measured_on, mass_kg FROM mass_log ORDER BY measured_on DESC").fetchall()
    current_mass_kg = latest_mass_kg(conn)
    fit_sources = fit_calibration_source_rows(conn)
    tests = conn.execute(
        """
        SELECT *
        FROM resistance_calibration_tests
        ORDER BY tested_on DESC, id DESC
        LIMIT 12
        """
    ).fetchall()
    return f"""
<section class="band">
  <h2>Constants</h2>
  <form class="stack" method="post" action="/calibration/profile/update">
    <input type="hidden" name="id" value="{profile['id']}">
    <label>Name<input name="name" value="{escape(str(profile['name']))}" required></label>
    <label>Length scale<input name="length_scale" type="number" step="0.000001" min="0" value="{fmt_raw(profile['length_scale'])}" required></label>
    <label>Distance per stroke<input name="distance_per_stroke" type="number" step="0.000001" min="0" value="{fmt_raw(profile['distance_per_stroke'])}"></label>
    <label>Mechanical efficiency<input name="mechanical_efficiency" type="number" step="0.001" min="0" max="1" value="{fmt_raw(profile['mechanical_efficiency'])}" required></label>
    <button type="submit">Save constants</button>
  </form>
</section>
<section class="band">
  <h2>Resistance Scaling</h2>
  <form method="post" action="/calibration/resistance/update">
    <table>
      <thead><tr><th>Resistance</th><th>Scaling factor</th></tr></thead>
      <tbody>{''.join(resistance_factor_row(row) for row in resistance_rows)}</tbody>
    </table>
    <p><button type="submit">Save factors</button></p>
  </form>
</section>
<section class="band">
  <h2>Calibration Test</h2>
  <form class="stack" method="post" action="/calibration/test/preview">
    <label>Date<input name="tested_on" type="date" required></label>
    <label>Resistance<select name="resistance" required>{resistance_select_options()}</select></label>
    <label>Duration minutes<input name="duration_minutes" type="number" step="0.001" min="0"></label>
    <label>Device watts<input name="device_watts" type="number" step="0.001" min="0" required></label>
    <label>Expected watts<input name="expected_watts" type="number" step="0.001" min="0"></label>
    <label>Average HR<input name="hr" type="number" min="0"></label>
    <label>Mass kg<input name="mass_kg" type="number" step="0.001" min="0" value="{fmt_raw(current_mass_kg)}"></label>
    <label>Notes<input name="notes"></label>
    <button type="submit">Preview factor</button>
  </form>
  {calibration_preview_panel(preview)}
</section>
<section class="band">
  <h2>FIT-Assisted Calibration Test</h2>
  {calibration_protocol_panel()}
  {fit_calibration_upload_form(current_mass_kg)}
  {fit_calibration_sources_table(fit_sources)}
</section>
<section class="band">
  <h2>Mass Log</h2>
  <form class="stack" method="post" action="/calibration/mass/add">
    <label>Date<input name="measured_on" type="date" required></label>
    <label>Mass kg<input name="mass_kg" type="number" step="0.001" min="0" required></label>
    <button type="submit">Add mass</button>
  </form>
  <div style="margin-top:14px;">{mass_log_table(mass_rows)}</div>
</section>
<section class="band">
  <h2>Recent Calibration Tests</h2>
  {calibration_tests_table(tests)}
</section>
"""


def render_insights(conn: sqlite3.Connection) -> str:
    sprints = calculated_sprints(conn)
    laps = calculated_laps(conn)
    source_rows = source_metric_rows(conn)
    circuit_rows = circuit_progress_rows(laps)
    strength_rows = strength_signal_rows(sprints, laps)
    calibration_rows = calibration_coverage_rows(conn)
    sprint_watts = [
        (sprint.started_at or sprint.performed_on, sprint.estimated_watts)
        for sprint in sprints
        if sprint.estimated_watts is not None
    ]
    sprint_rpm = [(sprint.started_at or sprint.performed_on, sprint.rpm) for sprint in sprints if sprint.rpm is not None]
    sprint_hr = [(sprint.started_at or sprint.performed_on, sprint.hr) for sprint in sprints if sprint.hr is not None]
    return f"""
<section class="band">
  <h2>Insight Summary</h2>
  <div class="metrics">
    {metric("Circuits tracked", len(circuit_rows), "green")}
    {metric("Best circuit gain", best_circuit_gain(circuit_rows), "green")}
    {metric("Best sprint watts", fmt_num(max_sprint_watts(sprints), 1), "amber")}
    {metric("Strength signals", len(strength_rows), "blue")}
    {metric("Calibrated levels", calibrated_resistance_count(calibration_rows), "blue")}
  </div>
</section>
<section class="band">
  <h2>Sprint Trends</h2>
  <div class="grid-two">
    {chart_panel("Estimated Watts", sprint_watts, "#1f5a85", "W")}
    {chart_panel("Cadence", sprint_rpm, "#2f7d59", "rpm")}
    {chart_panel("Heart Rate", sprint_hr, "#a33b3b", "bpm")}
    {chart_panel("Best 5 Minute Estimated Watts", source_metric_points(source_rows, "best_300s_watts"), "#a66200", "W")}
  </div>
</section>
<section class="band">
  <h2>Circuit Progress</h2>
  {circuit_progress_table(circuit_rows)}
</section>
<section class="band">
  <h2>Source Highlights</h2>
  {source_highlights_table(source_rows)}
</section>
<section class="band">
  <h2>Strength Signals</h2>
  {strength_signals_table(strength_rows)}
</section>
<section class="band">
  <h2>Resistance Calibration Coverage</h2>
  {calibration_coverage_table(calibration_rows)}
</section>
"""


def circuit_progress_rows(laps: list[object]) -> list[dict[str, object]]:
    grouped: dict[str, list[object]] = {}
    for lap in laps:
        if not lap.circuit_name or lap.lap_time_minutes is None:
            continue
        grouped.setdefault(str(lap.circuit_name), []).append(lap)

    rows = []
    for circuit_name, circuit_laps in grouped.items():
        ordered = sorted(circuit_laps, key=lambda lap: (lap.performed_on, lap.started_at or "", lap.id))
        times = [float(lap.lap_time_minutes) for lap in ordered if lap.lap_time_minutes is not None]
        if not times:
            continue
        first = ordered[0]
        latest = ordered[-1]
        best = min(ordered, key=lambda lap: lap.lap_time_minutes or 999999)
        rows.append({
            "circuit": circuit_name,
            "laps": len(ordered),
            "first_time": first.lap_time_minutes,
            "latest_time": latest.lap_time_minutes,
            "best_time": best.lap_time_minutes,
            "average_time": average_value(times),
            "change_minutes": (
                float(first.lap_time_minutes) - float(latest.lap_time_minutes)
                if first.lap_time_minutes is not None and latest.lap_time_minutes is not None
                else None
            ),
            "best_date": best.performed_on,
            "latest_date": latest.performed_on,
        })
    return sorted(rows, key=lambda row: str(row["circuit"]))


def strength_signal_rows(sprints: list[object], laps: list[object]) -> list[dict[str, object]]:
    rows = []
    for sprint in sprints:
        if is_strength_signal(sprint.resistance, sprint.rpm):
            rows.append({
                "date": sprint.performed_on,
                "start": fmt_start_time(sprint.started_at),
                "type": "Sprint",
                "label": f"Sprint {sprint.sprint_index or sprint.id}",
                "resistance": sprint.resistance,
                "rpm": sprint.rpm,
                "estimated_watts": sprint.estimated_watts,
                "hr": sprint.hr,
                "minutes": sprint.duration_minutes,
                "calories": sprint.calories_mets,
            })
    for lap in laps:
        if is_strength_signal(lap.resistance, lap.rpm):
            rows.append({
                "date": lap.performed_on,
                "start": fmt_start_time(lap.started_at),
                "type": "Lap",
                "label": lap.circuit_name or f"Lap {lap.lap_index or lap.id}",
                "resistance": lap.resistance,
                "rpm": lap.rpm,
                "estimated_watts": None,
                "hr": lap.hr,
                "minutes": lap.lap_time_minutes,
                "calories": lap.calories_mets,
            })
    return sorted(rows, key=lambda row: (str(row["date"]), str(row["start"]), str(row["type"])))


def is_strength_signal(resistance: object, rpm: object, min_resistance: int = 7, max_rpm: int = 95) -> bool:
    if resistance is None or rpm is None:
        return False
    return int(resistance) >= min_resistance and float(rpm) <= max_rpm


def calibration_coverage_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    scaling = {
        int(row["resistance"]): row["scaling"]
        for row in conn.execute("SELECT resistance, scaling FROM resistance_scaling").fetchall()
    }
    tests = {
        int(row["resistance"]): row
        for row in conn.execute(
            """
            SELECT resistance, COUNT(*) AS tests, MAX(tested_on) AS last_tested
            FROM resistance_calibration_tests
            GROUP BY resistance
            """
        ).fetchall()
    }
    sprint_counts = resistance_counts(conn, "sprint_entries")
    lap_counts = resistance_counts(conn, "lap_entries")
    rows = []
    for resistance in range(1, 13):
        test_row = tests.get(resistance)
        rows.append({
            "resistance": resistance,
            "scaling": scaling.get(resistance),
            "sprint_sessions": sprint_counts.get(resistance, 0),
            "lap_sessions": lap_counts.get(resistance, 0),
            "calibration_tests": int(test_row["tests"]) if test_row else 0,
            "last_tested": test_row["last_tested"] if test_row else "",
        })
    return rows


def fit_calibration_source_rows(conn: sqlite3.Connection, limit: int = 12) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, source, source_activity_id, title, started_on, duration_seconds,
               hr, raw_payload, imported_at
        FROM raw_activities
        WHERE raw_payload IS NOT NULL AND raw_payload != ''
        ORDER BY COALESCE(started_on, imported_at) DESC, id DESC
        LIMIT 80
        """
    ).fetchall()
    output = []
    for row in rows:
        source = fit_calibration_source_defaults(conn, row)
        if source is not None and is_calibration_candidate_source(source):
            output.append(source)
        if len(output) >= limit:
            break
    return output


def fit_calibration_source_defaults(
    conn: sqlite3.Connection,
    row_or_id: sqlite3.Row | int,
) -> dict[str, object] | None:
    row = row_or_id
    if isinstance(row_or_id, int):
        row = conn.execute("SELECT * FROM raw_activities WHERE id = ?", (row_or_id,)).fetchone()
        if row is None:
            return None
    payload = raw_payload_dict(row)
    if payload.get("format") != "fit":
        return None
    device_watts = payload_number(payload, "average_watts") or payload_number(payload, "session_average_watts")
    if device_watts is None:
        return None
    tested_on = date_part(row["started_on"])
    duration_minutes = duration_seconds_to_minutes(row["duration_seconds"])
    if duration_minutes is None:
        duration_seconds = payload_number(payload, "sample_duration_seconds")
        duration_minutes = duration_seconds / 60 if duration_seconds is not None else None
    hr = row["hr"] if row["hr"] is not None else payload_number(payload, "average_source_hr")
    mass_kg = mass_for_date(conn, tested_on) if tested_on is not None else None
    title = row["title"] or row["source_activity_id"] or f"Raw activity {row['id']}"
    quality_flags = calibration_quality_flags(duration_minutes, payload, hr)
    return {
        "id": row["id"],
        "date": tested_on,
        "title": title,
        "duration_minutes": duration_minutes,
        "device_watts": device_watts,
        "cadence": payload_number(payload, "average_cadence"),
        "hr": hr,
        "mass_kg": mass_kg,
        "notes": f"FIT calibration source raw activity #{row['id']} - {title}",
        "source": row["source"],
        "source_activity_id": row["source_activity_id"],
        "source_title": title,
        "source_started_on": row["started_on"],
        "source_file": None,
        "file_sha256": None,
        "raw_payload": row["raw_payload"],
        "quality_flags": quality_flags,
    }


def is_calibration_candidate_source(source: dict[str, object]) -> bool:
    duration = maybe_float(source.get("duration_minutes"))
    return duration is not None and 4.5 <= duration <= 6.5


def uploaded_fit_calibration_source_defaults(
    conn: sqlite3.Connection,
    params: dict[str, FormValue],
) -> dict[str, object] | None:
    upload = params.get("calibration_upload")
    if not isinstance(upload, UploadedFile) or not upload.filename or not upload.content:
        return None
    source = empty_to_none(params.get("source")) or "strava"
    rows = load_uploaded_activity_file(upload, source)
    if len(rows) != 1:
        raise ValueError("Calibration upload must contain exactly one FIT activity.")
    row = rows[0]
    payload = raw_payload_dict(row)
    if payload.get("format") != "fit":
        raise ValueError("Calibration upload must be a FIT file.")
    device_watts = payload_number(payload, "average_watts") or payload_number(payload, "session_average_watts")
    if device_watts is None:
        raise ValueError("Calibration FIT did not contain device watts.")
    tested_on = date_part(row.get("started_on"))
    duration_minutes = duration_seconds_to_minutes(row.get("duration_seconds"))
    if duration_minutes is None:
        duration_seconds = payload_number(payload, "sample_duration_seconds")
        duration_minutes = duration_seconds / 60 if duration_seconds is not None else None
    hr = row.get("hr") if row.get("hr") is not None else payload_number(payload, "average_source_hr")
    mass_kg = mass_for_date(conn, tested_on) if tested_on is not None else None
    title = row.get("title") or row.get("source_activity_id") or Path(upload.filename).stem
    quality_flags = calibration_quality_flags(duration_minutes, payload, hr)
    return {
        "id": None,
        "date": tested_on,
        "title": title,
        "duration_minutes": duration_minutes,
        "device_watts": device_watts,
        "cadence": payload_number(payload, "average_cadence"),
        "hr": hr,
        "mass_kg": mass_kg,
        "notes": f"FIT calibration upload - {title}",
        "source": source,
        "source_activity_id": row.get("source_activity_id"),
        "source_title": title,
        "source_started_on": row.get("started_on"),
        "source_file": Path(upload.filename).name,
        "file_sha256": hashlib.sha256(upload.content).hexdigest(),
        "raw_payload": row.get("raw_payload"),
        "quality_flags": quality_flags,
    }


def calibration_quality_flags(
    duration_minutes: float | None,
    payload: dict[str, object],
    hr: object,
) -> str | None:
    flags = []
    if duration_minutes is None:
        flags.append("Duration missing")
    elif duration_minutes < 4.5:
        flags.append("Shorter than 5 minute target")
    elif duration_minutes > 6.5:
        flags.append("Longer than 5 minute target")
    cadence_variability = payload_number(payload, "cadence_variability_pct")
    if cadence_variability is not None and cadence_variability > 10:
        flags.append("Cadence varied by more than 10%")
    if payload_number(payload, "average_cadence") is None:
        flags.append("Average cadence missing")
    if maybe_int(hr) is None:
        flags.append("HR missing")
    return "; ".join(flags) if flags else None


def payload_number(payload: dict[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resistance_counts(conn: sqlite3.Connection, table_name: str) -> dict[int, int]:
    if table_name not in {"sprint_entries", "lap_entries"}:
        raise ValueError("Unsupported table for resistance counts.")
    rows = conn.execute(
        f"""
        SELECT resistance, COUNT(*) AS sessions
        FROM {table_name}
        WHERE resistance IS NOT NULL
        GROUP BY resistance
        """
    ).fetchall()
    return {int(row["resistance"]): int(row["sessions"]) for row in rows}


def render_maintenance(conn: sqlite3.Connection) -> str:
    items = maintenance_items(conn)
    review_count = sum(1 for item in items if item["area"] == "Review")
    entry_count = len(items) - review_count
    blocker_count = sum(1 for item in items if item["category"] == "Analysis blocker")
    tidy_count = sum(1 for item in items if item["category"] == "Tidying")
    enrichment_count = sum(1 for item in items if item["category"] == "Optional enrichment")
    return f"""
<section class="band">
  <h2>Backup</h2>
  <div class="actions">
    <a href="/export/backup.zip">Download backup bundle</a>
    <a href="/export/daily_summary.csv">Daily summary CSV</a>
    <a href="/export/source_metrics.csv">Source metrics CSV</a>
  </div>
</section>
<section class="band">
  <h2>Data Quality</h2>
  <div class="metrics">
    {metric("Open issues", len(items), "amber" if items else "green")}
    {metric("Blockers", blocker_count, "red" if blocker_count else "green")}
    {metric("Tidying", tidy_count, "amber" if tidy_count else "green")}
    {metric("Enrichment", enrichment_count, "blue")}
    {metric("Entry fixes", entry_count, "blue")}
    {metric("Review items", review_count, "red" if review_count else "green")}
  </div>
</section>
<section class="band">
  <h2>Maintenance Queue</h2>
  {maintenance_table(items)}
</section>
"""


def maintenance_items(conn: sqlite3.Connection) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    sprints = calculated_sprints(conn)
    laps = calculated_laps(conn)
    for sprint in sprints:
        context = f"Sprint {sprint.sprint_index or sprint.id}"
        action = f"/entries#sprint-{sprint.id}"
        maybe_add_issue(
            items, not sprint.started_at, "Sprint", sprint.performed_on, sprint.started_at, context,
            "Tidying", "Missing start time", "Needed for reliable duplicate matching.", action,
        )
        maybe_add_issue(
            items, sprint.sprint_index is None, "Sprint", sprint.performed_on, sprint.started_at, context,
            "Tidying", "Missing sprint number", "Helps order multiple free-flow sessions on the same day.", action,
        )
        maybe_add_issue(
            items, sprint.hr is None, "Sprint", sprint.performed_on, sprint.started_at, context,
            "Analysis blocker", "Missing HR", "Needed for the primary HR/MET calorie estimate.", action,
        )
        maybe_add_issue(
            items, sprint.resistance is None, "Sprint", sprint.performed_on, sprint.started_at, context,
            "Analysis blocker", "Missing resistance", "Needed for estimated watts and resistance-scaled comparisons.", action,
        )
        maybe_add_issue(
            items, sprint.duration_minutes is None, "Sprint", sprint.performed_on, sprint.started_at, context,
            "Analysis blocker", "Missing duration", "Needed for calories, pace, and session totals.", action,
        )
        maybe_add_issue(
            items, sprint.device_watts is None, "Sprint", sprint.performed_on, sprint.started_at, context,
            "Optional enrichment", "Missing device watts", "Needed for estimated watts and watts-based comparisons.", action,
        )
        if sprint.hr is not None and sprint.duration_minutes is not None and sprint.calories_mets is None:
            add_entry_issue(items, "Sprint", sprint.performed_on, sprint.started_at, context, "Analysis blocker", "Missing calorie lookup", "Check mass log and MET lookup coverage for this HR/date.", f"/calibration")
        if sprint.resistance is not None and sprint.device_watts is not None and sprint.estimated_watts is None:
            add_entry_issue(items, "Sprint", sprint.performed_on, sprint.started_at, context, "Analysis blocker", "Missing resistance factor", "Add a scaling factor for this resistance level.", f"/calibration")

    for lap in laps:
        context = f"{lap.circuit_name or 'Lap'} {lap.lap_index or lap.id}"
        action = f"/entries#lap-{lap.id}"
        maybe_add_issue(
            items, not lap.started_at, "Lap", lap.performed_on, lap.started_at, context,
            "Tidying", "Missing start time", "Needed for reliable duplicate matching.", action,
        )
        maybe_add_issue(
            items, lap.lap_index is None, "Lap", lap.performed_on, lap.started_at, context,
            "Tidying", "Missing lap number", "Helps order multiple circuit sessions on the same day.", action,
        )
        maybe_add_issue(
            items, lap.circuit_id is None, "Lap", lap.performed_on, lap.started_at, context,
            "Analysis blocker", "Missing circuit", "Needed for lap distance, speed, and circuit leaderboards.", action,
        )
        maybe_add_issue(
            items, lap.hr is None, "Lap", lap.performed_on, lap.started_at, context,
            "Analysis blocker", "Missing HR", "Needed for the primary HR/MET calorie estimate.", action,
        )
        maybe_add_issue(
            items, lap.resistance is None, "Lap", lap.performed_on, lap.started_at, context,
            "Optional enrichment", "Missing resistance", "Needed for resistance-level analysis and future comparisons.", action,
        )
        maybe_add_issue(
            items, lap.lap_time_minutes is None, "Lap", lap.performed_on, lap.started_at, context,
            "Analysis blocker", "Missing lap time", "Needed for calories, speed, and best-lap tracking.", action,
        )
        if lap.hr is not None and lap.lap_time_minutes is not None and lap.calories_mets is None:
            add_entry_issue(items, "Lap", lap.performed_on, lap.started_at, context, "Analysis blocker", "Missing calorie lookup", "Check mass log and MET lookup coverage for this HR/date.", f"/calibration")

    add_manual_duplicate_issues(conn, items, sprints, laps)

    review_rows = conn.execute(
        """
        SELECT id, source, source_activity_id, title, started_on, review_status, session_type
        FROM raw_activities
        WHERE review_status NOT IN ('already_logged', 'reviewed', 'imported', 'ignored')
        ORDER BY COALESCE(started_on, imported_at), id
        """
    ).fetchall()
    for row in review_rows:
        context = row["title"] or row["source_activity_id"] or f"Raw activity {row['id']}"
        add_entry_issue(
            items,
            "Review",
            date_part(row["started_on"]) or "",
            row["started_on"],
            context,
            "Analysis blocker",
            f"Pending {row['review_status']}",
            f"Classified as {row['session_type']}; review before importing or ignoring.",
            "/review",
        )

    return sorted(
        items,
        key=lambda item: (
            maintenance_category_rank(str(item["category"])),
            str(item["date"] or ""),
            str(item["start"] or ""),
            str(item["area"]),
            str(item["issue"]),
        ),
    )


def add_manual_duplicate_issues(
    conn: sqlite3.Connection,
    items: list[dict[str, object]],
    sprints: list[object],
    laps: list[object],
) -> None:
    dismissed_sprints = dismissed_duplicate_pairs(conn, "sprint")
    for index, sprint in enumerate(sprints):
        for candidate in sprints[index + 1:]:
            if duplicate_pair_key(sprint.id, candidate.id) in dismissed_sprints:
                continue
            score, reason = duplicate_score(
                started_on=sprint.started_at or sprint.performed_on,
                duration_seconds=minutes_to_seconds(sprint.duration_minutes),
                raw_distance=sprint.device_distance,
                candidate_date=candidate.performed_on,
                candidate_started_at=candidate.started_at,
                candidate_minutes=candidate.duration_minutes,
                candidate_raw_distance=candidate.device_distance,
                circuit_match=False,
            )
            if is_manual_duplicate_candidate(
                score,
                sprint.started_at,
                candidate.started_at,
                sprint.performed_on,
                candidate.performed_on,
                sprint.sprint_index,
                candidate.sprint_index,
            ):
                add_entry_issue(
                    items,
                    "Sprint",
                    sprint.performed_on,
                    sprint.started_at,
                    f"Sprint {sprint.sprint_index or sprint.id} and sprint {candidate.sprint_index or candidate.id}",
                    "Analysis blocker",
                    "Possible duplicate entry",
                    reason or "Similar sprint entries were found.",
                    f"/entries#sprint-{sprint.id}",
                    duplicate_actions("sprint", sprint, candidate),
                )

    dismissed_laps = dismissed_duplicate_pairs(conn, "lap")
    for index, lap in enumerate(laps):
        for candidate in laps[index + 1:]:
            if duplicate_pair_key(lap.id, candidate.id) in dismissed_laps:
                continue
            if lap.circuit_id != candidate.circuit_id:
                continue
            score, reason = duplicate_score(
                started_on=lap.started_at or lap.performed_on,
                duration_seconds=minutes_to_seconds(lap.lap_time_minutes),
                raw_distance=lap.device_distance,
                candidate_date=candidate.performed_on,
                candidate_started_at=candidate.started_at,
                candidate_minutes=candidate.lap_time_minutes,
                candidate_raw_distance=candidate.device_distance,
                circuit_match=lap.circuit_id is not None,
            )
            if is_manual_duplicate_candidate(
                score,
                lap.started_at,
                candidate.started_at,
                lap.performed_on,
                candidate.performed_on,
                lap.lap_index,
                candidate.lap_index,
            ):
                add_entry_issue(
                    items,
                    "Lap",
                    lap.performed_on,
                    lap.started_at,
                    f"{lap.circuit_name or 'Lap'} {lap.lap_index or lap.id} and lap {candidate.lap_index or candidate.id}",
                    "Analysis blocker",
                    "Possible duplicate entry",
                    reason or "Similar lap entries were found.",
                    f"/entries#lap-{lap.id}",
                    duplicate_actions("lap", lap, candidate),
                )


def is_manual_duplicate_candidate(
    score: float,
    started_at: str | None,
    candidate_started_at: str | None,
    performed_on: str | None,
    candidate_performed_on: str | None,
    entry_index: int | None,
    candidate_index: int | None,
) -> bool:
    if score < POSSIBLE_DUPLICATE_THRESHOLD:
        same_date = date_part(performed_on) == date_part(candidate_performed_on)
        same_index = entry_index is not None and entry_index == candidate_index
        return same_date and same_index
    delta = start_delta_minutes(started_at, candidate_started_at)
    if delta is not None:
        return delta <= 10 or score >= STRONG_DUPLICATE_THRESHOLD
    same_date = date_part(performed_on) == date_part(candidate_performed_on)
    same_index = entry_index == candidate_index
    return same_date and same_index


def minutes_to_seconds(minutes: float | None) -> int | None:
    if minutes is None:
        return None
    return int(round(float(minutes) * 60))


def maybe_add_issue(
    items: list[dict[str, object]],
    condition: bool,
    area: str,
    date: str | None,
    start: str | None,
    record: str,
    category: str,
    issue: str,
    detail: str,
    action: str,
) -> None:
    if condition:
        add_entry_issue(items, area, date, start, record, category, issue, detail, action)


def add_entry_issue(
    items: list[dict[str, object]],
    area: str,
    date: str | None,
    start: str | None,
    record: str,
    category: str,
    issue: str,
    detail: str,
    action: str,
    extra_actions: list[dict[str, object]] | None = None,
) -> None:
    items.append({
        "area": area,
        "category": category,
        "date": date or "",
        "start": fmt_start_time(start),
        "record": record,
        "issue": issue,
        "detail": detail,
        "action": action,
        "extra_actions": extra_actions or [],
    })


def maintenance_table(items: list[dict[str, object]]) -> str:
    if not items:
        return '<div class="empty">No maintenance issues found.</div>'
    rows = []
    for item in items:
        rows.append([
            escape(str(item["category"])),
            escape(str(item["date"])),
            escape(str(item["start"])),
            escape(str(item["area"])),
            escape(str(item["record"])),
            escape(str(item["issue"])),
            escape(str(item["detail"])),
            maintenance_actions(item),
        ])
    return html_table(["Category", "Date", "Start", "Area", "Record", "Issue", "Detail", ""], rows)


def duplicate_actions(entry_type: str, first: object, second: object) -> list[dict[str, object]]:
    return [
        {"kind": "link", "href": f"/entries#{entry_type}-{second.id}", "label": "Open match"},
        {
            "kind": "not_duplicate",
            "entry_type": entry_type,
            "first_entry_id": first.id,
            "second_entry_id": second.id,
            "label": "Not duplicate",
        },
        {
            "kind": "delete",
            "entry_type": entry_type,
            "entry_id": first.id,
            "label": f"Delete {duplicate_entry_label(entry_type, first)}",
        },
        {
            "kind": "delete",
            "entry_type": entry_type,
            "entry_id": second.id,
            "label": f"Delete {duplicate_entry_label(entry_type, second)}",
        },
    ]


def duplicate_entry_label(entry_type: str, entry: object) -> str:
    if entry_type == "sprint":
        index = getattr(entry, "sprint_index", None)
    else:
        index = getattr(entry, "lap_index", None)
    number = index or getattr(entry, "id")
    return f"{entry_type} {number} (id {getattr(entry, 'id')})"


def maintenance_actions(item: dict[str, object]) -> str:
    parts = [f'<a href="{escape(str(item["action"]))}">Open</a>']
    for action in item.get("extra_actions", []):
        if not isinstance(action, dict):
            continue
        if action.get("kind") == "link":
            parts.append(f'<a href="{escape(str(action["href"]))}">{escape(str(action["label"]))}</a>')
        elif action.get("kind") == "not_duplicate":
            parts.append(
                f'<form method="post" action="/maintenance/not-duplicate">'
                f'<input type="hidden" name="entry_type" value="{escape(str(action["entry_type"]))}">'
                f'<input type="hidden" name="first_id" value="{escape(str(action["first_entry_id"]))}">'
                f'<input type="hidden" name="second_id" value="{escape(str(action["second_entry_id"]))}">'
                f'<button class="secondary" type="submit">{escape(str(action["label"]))}</button>'
                f"</form>"
            )
        elif action.get("kind") == "delete":
            label = str(action["label"])
            parts.append(
                f'<form method="post" action="/entries/delete" '
                f'onsubmit="return confirm(\'Delete this entry? This cannot be undone.\')">'
                f'<input type="hidden" name="entry_type" value="{escape(str(action["entry_type"]))}">'
                f'<input type="hidden" name="id" value="{escape(str(action["entry_id"]))}">'
                f'<button class="secondary" type="submit">{escape(label)}</button>'
                f"</form>"
            )
    return f'<div class="actions">{"".join(parts)}</div>'


def dismissed_duplicate_pairs(conn: sqlite3.Connection, entry_type: str) -> set[tuple[int, int]]:
    rows = conn.execute(
        """
        SELECT first_entry_id, second_entry_id
        FROM duplicate_dismissals
        WHERE entry_type = ?
        """,
        (entry_type,),
    ).fetchall()
    return {duplicate_pair_key(row["first_entry_id"], row["second_entry_id"]) for row in rows}


def duplicate_pair_key(first_id: object, second_id: object) -> tuple[int, int]:
    first = int(first_id)
    second = int(second_id)
    return (first, second) if first <= second else (second, first)


def maintenance_category_rank(category: str) -> int:
    order = {
        "Analysis blocker": 0,
        "Tidying": 1,
        "Optional enrichment": 2,
    }
    return order.get(category, 9)


def render_review(conn: sqlite3.Connection) -> str:
    populate_missing_duplicate_hr(conn)
    circuits = conn.execute("SELECT id, name FROM circuits WHERE active = 1 ORDER BY name").fetchall()
    queue_rows = review_activity_rows(conn, terminal=False)
    history_rows = review_activity_rows(conn, terminal=True)
    return f"""
<section class="band">
  <h2>Add Raw Activity</h2>
  <form class="stack" method="post" action="/review/add">
    <label>Source<input name="source" value="manual" required></label>
    <label>Source ID<input name="source_activity_id"></label>
    <label>Title<input name="title" placeholder="Kinomap free-ride"></label>
    <label>Start time<input name="started_on" type="datetime-local"></label>
    <label>Duration seconds<input name="duration_seconds" type="number"></label>
    <label>Raw distance<input name="raw_distance" type="number" step="0.001"></label>
    <label>HR<input name="hr" type="number" min="0"></label>
    <button type="submit">Add to review</button>
  </form>
</section>
<section class="band">
  <h2>Import Activity File</h2>
  <form class="stack" method="post" action="/review/import-file" enctype="multipart/form-data">
    <label>Source<input name="source" value="strava" required></label>
    <label>Activity file<input name="activity_upload" type="file" accept=".csv,.json,.tcx,.fit,.gz,.zip"></label>
    <label>Folder or path<input name="activity_file" placeholder="exports/activities"></label>
    <button type="submit">Import file</button>
  </form>
</section>
<section class="band">
  <h2>Review Queue</h2>
  {raw_activity_table(queue_rows, circuits)}
</section>
<section class="band">
  <h2>Import History</h2>
  {raw_activity_table(history_rows, circuits, readonly=True)}
</section>
"""


def review_activity_rows(conn: sqlite3.Connection, *, terminal: bool) -> list[sqlite3.Row]:
    status_filter = (
        "r.review_status IN ('already_logged', 'reviewed', 'imported', 'ignored')"
        if terminal
        else "r.review_status NOT IN ('already_logged', 'reviewed', 'imported', 'ignored')"
    )
    limit = "LIMIT 30" if terminal else ""
    return conn.execute(
        f"""
        WITH raw_with_resistance AS (
            SELECT r.*, c.name AS circuit_name,
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
                   ) AS default_resistance
            FROM raw_activities r
            LEFT JOIN circuits c ON c.id = r.circuit_id
            WHERE {status_filter}
        )
        SELECT rr.*, rs.scaling AS default_resistance_scaling
        FROM raw_with_resistance rr
        LEFT JOIN resistance_scaling rs ON rs.resistance = rr.default_resistance
        ORDER BY rr.imported_at DESC, rr.id DESC
        {limit}
        """
    ).fetchall()


def raw_activity_table(rows: list[sqlite3.Row], circuits: list[sqlite3.Row], readonly: bool = False) -> str:
    if not rows:
        return '<div class="empty">No raw activities in this section.</div>'
    circuit_options = '<option value="">No circuit</option>' + "".join(
        f'<option value="{row["id"]}">{escape(row["name"])}</option>' for row in circuits
    )
    rendered = []
    for row in rows:
        options = circuit_options
        if row["circuit_id"]:
            options = options.replace(f'value="{row["circuit_id"]}"', f'value="{row["circuit_id"]}" selected')
        rendered.append(f"""
<tr>
  <td>{escape(str(row['source']))}</td>
  <td>{escape(str(row['title'] or ''))}</td>
  <td>{escape(str(row['started_on'] or ''))}</td>
  <td>{fmt_num(row['raw_distance'], 3)}<br><span class="muted">{source_metric_summary(row)}</span></td>
  <td>{review_status_label(row)}<br><span class="muted">{escape(str(row['classification_reason'] or ''))}</span></td>
  <td>{duplicate_match_label(row)}</td>
  <td>{'' if readonly else review_actions(row, options)}</td>
</tr>""")
    return f"""
<table>
  <thead><tr><th>Source</th><th>Title</th><th>Start</th><th>Raw distance</th><th>Status</th><th>Possible match</th><th>Review</th></tr></thead>
  <tbody>{''.join(rendered)}</tbody>
</table>"""


def review_status_label(row: sqlite3.Row) -> str:
    status = str(row["review_status"] or "needs_review")
    session = str(row["session_type"] or "unknown")
    label = {
        "already_logged": "Already logged",
        "possible_duplicate": "Possible duplicate",
        "needs_hr": "Needs HR",
        "needs_review": "Needs review",
        "ready_to_import": "Ready to import",
        "imported": "Imported",
        "reviewed": "Reviewed",
        "ignored": "Ignored",
    }.get(status, status.replace("_", " ").title())
    return f"{escape(label)}<br><span class=\"muted\">{escape(session)}</span>"


def duplicate_match_label(row: sqlite3.Row) -> str:
    if not row["duplicate_entry_type"] or not row["duplicate_entry_id"]:
        return '<span class="muted">No match</span>'
    confidence = row["duplicate_confidence"]
    pieces = [
        f"{row['duplicate_entry_type']} #{row['duplicate_entry_id']}",
        fmt_num(confidence, 2) if confidence is not None else "",
    ]
    reason = row["duplicate_reason"] or ""
    return f"{escape(' - '.join(piece for piece in pieces if piece))}<br><span class=\"muted\">{escape(str(reason))}</span>"


def review_actions(row: sqlite3.Row, circuit_options: str) -> str:
    confirm_duplicate = ""
    if row["duplicate_entry_type"] and row["duplicate_entry_id"]:
        confirm_duplicate = f"""
      <form method="post" action="/review/confirm-duplicate">
        <input type="hidden" name="id" value="{row['id']}">
        <button class="secondary" type="submit">Confirm duplicate</button>
      </form>"""
    promote_form = promote_activity_form(row, circuit_options)
    return f"""
    <div style="display:grid; gap:8px;">
      {confirm_duplicate}
      <form method="post" action="/review/classify">
        <input type="hidden" name="id" value="{row['id']}">
        <input type="hidden" name="session_type" value="ignore">
        <button class="secondary" type="submit">Ignore activity</button>
      </form>
      <form class="stack" method="post" action="/review/classify">
        <input type="hidden" name="id" value="{row['id']}">
        <label>Type
          <select name="session_type">
            {select_option('unknown', row['session_type'])}
            {select_option('lap', row['session_type'])}
            {select_option('sprint', row['session_type'])}
            {select_option('endurance', row['session_type'])}
            {select_option('ignore', row['session_type'])}
          </select>
        </label>
        <label>Circuit<select name="circuit_id">{circuit_options}</select></label>
        <button type="submit">Confirm</button>
      </form>
      {promote_form}
    </div>"""


def promote_activity_form(row: sqlite3.Row, circuit_options: str) -> str:
    payload = raw_payload_dict(row)
    performed_on = date_part(row["started_on"]) or ""
    duration_minutes = duration_seconds_to_minutes(row["duration_seconds"])
    raw_type = row["session_type"] if row["session_type"] in ("lap", "sprint") else "sprint"
    rpm = step_value(payload.get("average_cadence"), 1)
    device_watts = step_value(payload.get("average_watts"), 1)
    resistance = row_value(row, "default_resistance", 4)
    notes = default_promotion_notes(row)
    return f"""
      <form class="stack" method="post" action="/review/promote">
        <input type="hidden" name="id" value="{row['id']}">
        <label>Import as
          <select name="session_type">
            {select_option('sprint', raw_type)}
            {select_option('lap', raw_type)}
          </select>
        </label>
        <label>Date<input name="performed_on" type="date" value="{escape(performed_on)}" required></label>
        <label>Duration min<input name="duration_minutes" type="number" step="0.001" min="0" value="{step_value(duration_minutes, 3)}"></label>
        <label>HR<input name="hr" type="number" min="0" value="{fmt_raw(row['hr'])}" required></label>
        <label>Resistance<input name="resistance" type="number" min="1" max="12" value="{fmt_raw(resistance)}" required></label>
        <label>RPM<input name="rpm" type="number" step="0.1" min="0" value="{fmt_raw(rpm)}"></label>
        <label>Device watts<input name="device_watts" type="number" step="0.1" min="0" value="{fmt_raw(device_watts)}"></label>
        <label>Entry number<input name="entry_index" type="number" min="1"></label>
        <label>Circuit<select name="circuit_id">{circuit_options}</select></label>
        <label>Notes<input name="notes" value="{escape(notes)}"></label>
        <button type="submit">Import entry</button>
      </form>"""


def default_promotion_notes(row: sqlite3.Row) -> str:
    pieces = [f"Imported from {row['source']}"]
    if row["source_activity_id"]:
        pieces.append(str(row["source_activity_id"]))
    if row["title"]:
        pieces.append(str(row["title"]))
    return " - ".join(pieces)


def raw_payload_dict(row: sqlite3.Row) -> dict[str, object]:
    if not row["raw_payload"]:
        return {}
    return payload_from_text(row["raw_payload"])


def payload_from_text(raw_payload: object) -> dict[str, object]:
    try:
        payload = json.loads(str(raw_payload))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def merge_raw_payload(existing_payload: object, incoming_payload: object) -> str | None:
    if incoming_payload in (None, ""):
        return str(existing_payload) if existing_payload not in (None, "") else None
    if existing_payload in (None, ""):
        return str(incoming_payload)
    try:
        existing = json.loads(str(existing_payload))
    except (TypeError, ValueError):
        existing = {}
    try:
        incoming = json.loads(str(incoming_payload))
    except (TypeError, ValueError):
        incoming = {}
    if not isinstance(existing, dict) or not isinstance(incoming, dict):
        return str(incoming_payload)
    merged = {**existing, **incoming}
    return json.dumps(merged, sort_keys=True)


def source_metric_summary(row: sqlite3.Row) -> str:
    payload = raw_payload_dict(row)
    if not payload:
        return ""
    pieces = []
    if payload.get("average_watts") is not None:
        scale = row_float(row, "default_resistance_scaling")
        average_watts = scaled_number(payload.get("average_watts"), scale)
        max_watts = scaled_number(payload.get("max_watts"), scale)
        label = "est watts" if scale is not None else "device watts"
        pieces.append(f"{label} avg {fmt_num(average_watts, 0)} max {fmt_num(max_watts, 0)}")
    if payload.get("average_cadence") is not None:
        pieces.append(f"rpm avg {fmt_num(payload.get('average_cadence'), 0)} max {fmt_num(payload.get('max_cadence'), 0)}")
    if payload.get("average_speed_mps") is not None:
        pieces.append(f"speed avg {fmt_num(payload.get('average_speed_mps'), 1)} m/s")
    if payload.get("calories") is not None:
        pieces.append(f"source calories {fmt_num(payload.get('calories'), 0)}")
    return escape("; ".join(pieces))


def resistance_factor_row(row: dict[str, object]) -> str:
    resistance = int(row["resistance"])
    scaling = row.get("scaling")
    return f"""
<tr>
  <td>{resistance}</td>
  <td><input name="scaling_{resistance}" type="number" step="0.000001" min="0" value="{fmt_raw(scaling)}"></td>
</tr>"""


def mass_log_table(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return '<div class="empty">No mass records yet.</div>'
    rendered = []
    for row in rows:
        rendered.append(f"""
<form method="post" action="/calibration/mass/update">
  <input type="hidden" name="id" value="{row['id']}">
  <table><tbody><tr>
    <td><input name="measured_on" type="date" value="{escape(str(row['measured_on']))}" required></td>
    <td><input name="mass_kg" type="number" step="0.001" min="0" value="{fmt_raw(row['mass_kg'])}" required></td>
    <td><button type="submit">Save</button></td>
  </tr></tbody></table>
</form>""")
    return "".join(rendered)


def calibration_protocol_panel() -> str:
    return """
<div class="muted" style="margin-bottom:12px;">
  Warm up first, run a steady 5 minute effort at one resistance level, keep cadence stable, then upload the FIT file here so it is used for calibration rather than added to the workout review queue.
</div>"""


def fit_calibration_upload_form(current_mass_kg: float | None) -> str:
    return f"""
<form class="stack" method="post" action="/calibration/test/preview" enctype="multipart/form-data" style="margin-bottom:14px;">
  <label>Source<input name="source" value="strava" required></label>
  <label>Calibration FIT<input name="calibration_upload" type="file" accept=".fit,.fit.gz" required></label>
  <label>Resistance<select name="resistance" required>{resistance_select_options(4)}</select></label>
  <label>Average HR<input name="hr" type="number" min="0"></label>
  <label>Mass kg<input name="mass_kg" type="number" step="0.001" min="0" value="{fmt_raw(current_mass_kg)}"></label>
  <label>Expected watts<input name="expected_watts" type="number" step="0.001" min="0"></label>
  <label>Notes<input name="notes"></label>
  <button type="submit">Preview calibration file</button>
</form>"""


def fit_calibration_sources_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return '<div class="empty">No imported FIT activities match the 5 minute calibration protocol yet.</div>'
    body = []
    for row in rows:
        quality = f'<br><span class="muted">{escape(str(row["quality_flags"]))}</span>' if row.get("quality_flags") else ""
        body.append(f"""
<tr>
  <td>{escape(str(row["date"] or ""))}<br><span class="muted">{escape(str(row["title"] or ""))}</span></td>
  <td>{fmt_minutes(row["duration_minutes"])}</td>
  <td>{fmt_num(row["device_watts"], 1)}</td>
  <td>{fmt_num(row["cadence"], 1)}</td>
  <td>{fmt_num(row["hr"], 0)}{quality}</td>
  <td>
    <form class="stack" method="post" action="/calibration/test/preview">
      <input type="hidden" name="source_raw_activity_id" value="{row['id']}">
      <label>Resistance<select name="resistance" required>{resistance_select_options()}</select></label>
      <label>Average HR<input name="hr" type="number" min="0" value="{fmt_raw(row['hr'])}"></label>
      <label>Mass kg<input name="mass_kg" type="number" step="0.001" min="0" value="{fmt_raw(row['mass_kg'])}"></label>
      <label>Expected watts<input name="expected_watts" type="number" step="0.001" min="0"></label>
      <label>Notes<input name="notes" value="{escape(str(row['notes']))}"></label>
      <button type="submit">Preview factor</button>
    </form>
  </td>
</tr>""")
    return f"""
<div class="table-scroll">
  <table>
    <thead><tr><th>Activity</th><th>Time</th><th>Device watts</th><th>Cadence</th><th>HR</th><th>Calibration input</th></tr></thead>
    <tbody>{''.join(body)}</tbody>
  </table>
</div>"""


def calibration_tests_table(rows: list[sqlite3.Row]) -> str:
    return table(
        ["Date", "Resistance", "Device watts", "Expected watts", "HR", "Mass", "Scaling", "Source", "Quality", "Notes"],
        [
            [
                row["tested_on"],
                row["resistance"],
                fmt_num(row["device_watts"], 1),
                fmt_num(row["expected_watts"], 1),
                row["hr"],
                fmt_num(row["mass_kg"], 2),
                fmt_num(row["calculated_scaling"], 4),
                calibration_test_source_label(row),
                row["quality_flags"],
                row["notes"],
            ]
            for row in rows
        ],
    )


def calibration_test_source_label(row: sqlite3.Row) -> str:
    if row["source_title"]:
        return str(row["source_title"])
    if row["source_file"]:
        return str(row["source_file"])
    if row["source_activity_id"]:
        return str(row["source_activity_id"])
    return str(row["source"] or "")


def calibration_preview_panel(preview: dict[str, object] | None) -> str:
    if preview is None:
        return ""
    current = preview.get("current_scaling")
    change = preview.get("change_pct")
    source = calibration_preview_source(preview)
    quality = calibration_preview_quality(preview)
    expected_note = calibration_expected_watts_note(preview)
    return f"""
<div class="band" style="margin-top:14px;">
  <h2>Preview Factor</h2>
  <div class="metrics">
    {metric("Resistance", preview["resistance"], "blue")}
    {metric("Device watts", fmt_num(preview["device_watts"], 1), "amber")}
    {metric("Expected watts", fmt_num(preview["expected_watts"], 1), "green")}
    {metric("Calculated factor", fmt_num(preview["calculated_scaling"], 4), "green")}
    {metric("Current factor", fmt_num(current, 4) if current is not None else "None", "blue")}
    {metric("Change", signed_percent(change), "amber")}
  </div>
  {expected_note}
  {source}
  {quality}
  <form method="post" action="/calibration/test/apply" style="margin-top:14px;">
    {hidden_calibration_inputs(preview)}
    <button type="submit">Apply factor</button>
  </form>
</div>"""


def calibration_expected_watts_note(preview: dict[str, object]) -> str:
    if preview.get("expected_watts_source") != "HR/MET x mechanical efficiency":
        return ""
    return (
        '<div class="muted" style="margin-top:12px;">'
        f'Expected watts: {fmt_num(preview.get("metabolic_watts"), 1)} metabolic W '
        f'x {fmt_percent(preview.get("mechanical_efficiency"))} mechanical efficiency.'
        "</div>"
    )


def calibration_preview_source(preview: dict[str, object]) -> str:
    pieces = []
    if preview.get("source"):
        pieces.append(str(preview["source"]))
    if preview.get("source_title"):
        pieces.append(str(preview["source_title"]))
    if preview.get("source_file"):
        pieces.append(str(preview["source_file"]))
    if not pieces:
        return ""
    return f'<div class="muted" style="margin-top:12px;">Source: {escape(" - ".join(pieces))}</div>'


def calibration_preview_quality(preview: dict[str, object]) -> str:
    flags = preview.get("quality_flags")
    if not flags:
        return ""
    return f'<div class="empty" style="margin-top:12px;">Calibration check: {escape(str(flags))}</div>'


def circuit_progress_table(rows: list[dict[str, object]]) -> str:
    return table(
        ["Circuit", "Laps", "First", "Latest", "Best", "Average", "Latest gain", "Best date", "Latest date"],
        [
            [
                row["circuit"],
                row["laps"],
                fmt_minutes(row["first_time"]),
                fmt_minutes(row["latest_time"]),
                fmt_minutes(row["best_time"]),
                fmt_minutes(row["average_time"]),
                signed_minutes(row["change_minutes"]),
                row["best_date"],
                row["latest_date"],
            ]
            for row in rows
        ],
    )


def source_highlights_table(rows: list[dict[str, object]]) -> str:
    highlights = []
    for label, key, digits in [
        ("Average estimated watts", "average_watts", 0),
        ("Best 5 minute estimated watts", "best_300s_watts", 0),
        ("Best 60 second estimated watts", "best_60s_watts", 0),
        ("Average cadence", "average_cadence", 0),
        ("Watts variability", "watts_variability_pct", 1),
    ]:
        row = best_source_row(rows, key)
        if row is None:
            continue
        highlights.append([
            label,
            fmt_num(row.get(key), digits),
            row.get("started_on", ""),
            row.get("session_type", ""),
            row.get("circuit", ""),
            row.get("resistance", ""),
        ])
    return table(["Metric", "Value", "Start", "Type", "Circuit", "Resistance"], highlights)


def strength_signals_table(rows: list[dict[str, object]]) -> str:
    return table(
        ["Date", "Start", "Type", "Session", "Resistance", "RPM", "Est watts", "HR", "Time", "Calories"],
        [
            [
                row["date"],
                row["start"],
                row["type"],
                row["label"],
                row["resistance"],
                fmt_num(row["rpm"], 0),
                fmt_num(row["estimated_watts"], 1),
                row["hr"],
                fmt_minutes(row["minutes"]),
                fmt_num(row["calories"], 1),
            ]
            for row in rows
        ],
    )


def calibration_coverage_table(rows: list[dict[str, object]]) -> str:
    return table(
        ["Resistance", "Status", "Scaling", "Sprint sessions", "Lap sessions", "Tests", "Last tested"],
        [
            [
                row["resistance"],
                "Calibrated" if row["scaling"] is not None else "Needs factor",
                fmt_num(row["scaling"], 4),
                row["sprint_sessions"],
                row["lap_sessions"],
                row["calibration_tests"],
                row["last_tested"],
            ]
            for row in rows
        ],
    )


def daily_table(rows: list[dict[str, object]]) -> str:
    return table(
        ["Date", "Sprints", "Laps", "Calories (HR/MET)", "Time", "Avg watts", "Avg RPM", "Lap distance", "Total distance"],
        [
            [
                row["date"],
                row["sprint_count"],
                row["lap_count"],
                fmt_num(row["total_calories"], 1),
                fmt_minutes(row["total_minutes"]),
                fmt_num(row["average_watts"], 1),
                fmt_num(row["average_rpm"], 1),
                fmt_num(row["lap_distance"], 3),
                fmt_num(row["total_distance"], 3),
            ]
            for row in rows
        ],
    )


def best_laps_table(rows: list[dict[str, object]]) -> str:
    return table(
        ["Circuit", "Best time", "Date", "Length", "Average speed"],
        [
            [
                row["circuit_name"],
                fmt_minutes(row["lap_time_minutes"]),
                row["performed_on"],
                fmt_num(row["length"], 3),
                fmt_num(row["average_speed"], 2),
            ]
            for row in rows
        ],
    )


def source_metrics_table(rows: list[dict[str, object]]) -> str:
    return f"""<div class="table-scroll">{table(
        ["Start", "Type", "Circuit", "Resistance", "Avg est watts", "Best 5m", "Best 60s", "Avg RPM", "Max RPM", "Avg speed", "Watts var", "Flags"],
        [
            [
                row["started_on"],
                row["session_type"],
                row["circuit"],
                row["resistance"],
                fmt_num(row["average_watts"], 0),
                fmt_num(row["best_300s_watts"], 0),
                fmt_num(row["best_60s_watts"], 0),
                fmt_num(row["average_cadence"], 0),
                fmt_num(row["max_cadence"], 0),
                fmt_num(row["average_speed_mps"], 1),
                fmt_num(row["watts_variability_pct"], 1),
                row["data_quality_flags"],
            ]
            for row in rows
        ],
    )}</div>"""


def table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return '<div class="empty">No data yet.</div>'
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape('' if value is None else str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def html_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<div class="empty">No data yet.</div>'
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def grouped_table(headers: list[str], rows: list[list[object]], group_index: int = 0) -> str:
    if not rows:
        return '<div class="empty">No data yet.</div>'
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = []
    current_group = object()
    group_class = "day-group-b"
    for row in rows:
        is_new_group = row[group_index] != current_group
        if is_new_group:
            current_group = row[group_index]
            group_class = "day-group-a" if group_class == "day-group-b" else "day-group-b"
        classes = f'{group_class}{" day-start" if is_new_group else ""}'
        cells = "".join(f"<td>{escape('' if value is None else str(value))}</td>" for value in row)
        body.append(f'<tr class="{classes}">{cells}</tr>')
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def grouped_html_table(headers: list[str], rows: list[tuple[object, list[str], str | None]]) -> str:
    if not rows:
        return '<div class="empty">No data yet.</div>'
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = []
    current_group = object()
    group_class = "day-group-b"
    for group_key, cells, row_id in rows:
        is_new_group = group_key != current_group
        if is_new_group:
            current_group = group_key
            group_class = "day-group-a" if group_class == "day-group-b" else "day-group-b"
        classes = f'{group_class}{" day-start" if is_new_group else ""}'
        id_attr = f' id="{escape(row_id)}"' if row_id else ""
        body.append(f'<tr{id_attr} class="{classes}">' + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    return f'<div class="table-scroll"><table class="entry-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def entry_form(form_id: str, action: str, entry_id: int) -> str:
    return (
        f'<form id="{escape(form_id)}" method="post" action="{escape(action)}">'
        f'<input type="hidden" name="id" value="{entry_id}"></form>'
    )


def entry_input(
    form_id: str,
    name: str,
    value: object,
    *,
    input_type: str = "text",
    step: str | None = None,
    min_value: str | None = None,
    max_value: str | None = None,
    required: bool = False,
    css_class: str = "",
) -> str:
    attrs = [
        f'form="{escape(form_id)}"',
        f'name="{escape(name)}"',
        f'type="{escape(input_type)}"',
        f'value="{escape("" if value is None else str(value))}"',
    ]
    if step is not None:
        attrs.append(f'step="{escape(step)}"')
    if min_value is not None:
        attrs.append(f'min="{escape(min_value)}"')
    if max_value is not None:
        attrs.append(f'max="{escape(max_value)}"')
    if required:
        attrs.append("required")
    if css_class:
        attrs.append(f'class="{escape(css_class)}"')
    return f"<input {' '.join(attrs)}>"


def entry_select(form_id: str, name: str, options: str, required: bool = True) -> str:
    required_attr = " required" if required else ""
    return f'<select form="{escape(form_id)}" name="{escape(name)}"{required_attr}>{options}</select>'


def readonly_cell(value: object) -> str:
    return f'<span class="readonly-cell">{escape("" if value is None else str(value))}</span>'


def save_button(form_id: str) -> str:
    return f'<button class="secondary" form="{escape(form_id)}" type="submit">Save</button>'


def metric(label: str, value: object, tone: str = "blue") -> str:
    return f'<div class="metric {tone}"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'


def chart_panel(title: str, points: list[tuple[str, float | None]], color: str, unit: str = "") -> str:
    return f"""
<div class="chart-panel">
  {line_chart(title, points, color, unit=unit)}
  <details>
    <summary>Open larger chart</summary>
    {line_chart(title, points, color, unit=unit, large=True)}
  </details>
</div>"""


def line_chart(
    title: str,
    points: list[tuple[str, float | None]],
    color: str,
    *,
    unit: str = "",
    large: bool = False,
) -> str:
    display_title = f"{title} ({unit})" if unit else title
    chart_class = "chart chart-large" if large else "chart"
    clean = [(label, float(value)) for label, value in points if value is not None]
    if not clean:
        return f'<svg class="{chart_class}" role="img" aria-label="{escape(display_title)}"></svg>'
    width, height = (1000, 667) if large else (680, 220)
    left_pad, right_pad, top_pad, bottom_pad = 56, 18, 34, 30
    values = [value for _, value in clean]
    v_min, v_max = min(values), max(values)
    if v_min == v_max:
        v_min -= 1
        v_max += 1
    x_step = (width - left_pad - right_pad) / max(1, len(clean) - 1)
    plot_height = height - top_pad - bottom_pad
    coords = []
    for index, (_, value) in enumerate(clean):
        x = left_pad + index * x_step
        y = height - bottom_pad - ((value - v_min) / (v_max - v_min) * plot_height)
        coords.append((x, y))
    grid_lines = chart_grid_lines(v_min, v_max, unit, left_pad, width - right_pad, top_pad, height - bottom_pad)
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>' for x, y in coords)
    first_label = chart_edge_label(clean[0][0])
    last_label = chart_edge_label(clean[-1][0])
    return f"""
<svg class="{chart_class}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(display_title)}">
  <text x="18" y="24" fill="#17202a" font-size="15" font-weight="700">{escape(display_title)}</text>
  {grid_lines}
  <line x1="{left_pad}" y1="{height-bottom_pad}" x2="{width-right_pad}" y2="{height-bottom_pad}" stroke="#d9e2ec"/>
  <line x1="{left_pad}" y1="{top_pad}" x2="{left_pad}" y2="{height-bottom_pad}" stroke="#d9e2ec"/>
  <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="3"/>
  {circles}
  <text x="{left_pad}" y="{height - 8}" fill="#5f6b7a" font-size="11">{escape(first_label)}</text>
  <text x="{width - right_pad}" y="{height - 8}" fill="#5f6b7a" font-size="11" text-anchor="end">{escape(last_label)}</text>
</svg>"""


def chart_grid_lines(
    v_min: float,
    v_max: float,
    unit: str,
    x1: int,
    x2: int,
    y_top: int,
    y_bottom: int,
    count: int = 4,
) -> str:
    lines = []
    for index in range(count):
        value = v_min + ((v_max - v_min) * index / max(1, count - 1))
        y = y_bottom - ((value - v_min) / (v_max - v_min) * (y_bottom - y_top))
        lines.append(
            f'<line class="chart-grid-line" x1="{x1}" y1="{y:.1f}" x2="{x2}" y2="{y:.1f}" stroke="#e7eef5"/>'
            f'<text class="chart-axis-value" x="8" y="{y + 4:.1f}" fill="#5f6b7a" font-size="11">'
            f'{escape(chart_axis_label(value, unit))}</text>'
        )
    return "\n  ".join(lines)


def chart_axis_label(value: float, unit: str = "") -> str:
    digits = 0 if abs(value) >= 10 else 1
    label = fmt_num(value, digits)
    return f"{label} {unit}".strip()


def chart_edge_label(label: object) -> str:
    text = str(label)
    if "T" in text:
        return text.split("T", 1)[0]
    if " " in text:
        return text.split(" ", 1)[0]
    return text[:16]


def source_metric_points(rows: list[dict[str, object]], key: str) -> list[tuple[str, float | None]]:
    ordered = list(reversed(rows))
    return [(str(row["started_on"] or row["id"]), row.get(key)) for row in ordered]


def max_metric(rows: list[dict[str, object]], key: str) -> float | None:
    values = []
    for row in rows:
        value = row.get(key)
        if value not in (None, ""):
            values.append(float(value))
    return max(values) if values else None


def best_source_row(rows: list[dict[str, object]], key: str) -> dict[str, object] | None:
    candidates = [row for row in rows if row.get(key) not in (None, "")]
    if not candidates:
        return None
    return max(candidates, key=lambda row: float(row[key]))


def max_sprint_watts(sprints: list[object]) -> float | None:
    values = [float(sprint.estimated_watts) for sprint in sprints if sprint.estimated_watts is not None]
    return max(values) if values else None


def calibrated_resistance_count(rows: list[dict[str, object]]) -> int:
    return sum(1 for row in rows if row.get("scaling") is not None)


def best_circuit_gain(rows: list[dict[str, object]]) -> str:
    gains = [float(row["change_minutes"]) for row in rows if row.get("change_minutes") is not None]
    if not gains:
        return ""
    best = max(gains)
    return signed_minutes(best)


def average_value(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def row_value(row: sqlite3.Row, key: str, default: object = None) -> object:
    return row[key] if key in row.keys() and row[key] not in (None, "") else default


def row_float(row: sqlite3.Row, key: str) -> float | None:
    value = row_value(row, key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def scaled_number(value: object, scale: float | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    return raw * scale if scale is not None else raw


def update_circuit(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    conn.execute(
        """
        UPDATE circuits
        SET name = ?, length = ?, active = ?
        WHERE id = ?
        """,
        (
            params["name"].strip(),
            float(params["length"]),
            1 if params.get("active") == "1" else 0,
            int(params["id"]),
        ),
    )
    conn.commit()


def add_circuit(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    conn.execute(
        "INSERT INTO circuits (name, length) VALUES (?, ?)",
        (params["name"].strip(), float(params["length"])),
    )
    conn.commit()


def find_activity_duplicate(
    conn: sqlite3.Connection,
    *,
    started_on: str | None,
    duration_seconds: int | None,
    raw_distance: float | None,
    session_type: str = "unknown",
    circuit_id: int | None = None,
) -> dict[str, object] | None:
    profile = editable_calibration_profile(conn)
    length_scale = float(profile["length_scale"])
    candidates: list[dict[str, object]] = []

    for row in conn.execute(
        """
        SELECT id, performed_on, started_at, duration_minutes, device_distance
        FROM sprint_entries
        """
    ).fetchall():
        score, reason = duplicate_score(
            started_on=started_on,
            duration_seconds=duration_seconds,
            raw_distance=raw_distance,
            candidate_date=row["performed_on"],
            candidate_started_at=row["started_at"],
            candidate_minutes=row["duration_minutes"],
            candidate_raw_distance=row["device_distance"],
            circuit_match=False,
        )
        if score >= POSSIBLE_DUPLICATE_THRESHOLD:
            candidates.append({
                "entry_type": "sprint",
                "entry_id": int(row["id"]),
                "circuit_id": None,
                "confidence": score,
                "reason": reason,
            })

    for row in conn.execute(
        """
        SELECT l.id, l.performed_on, l.started_at, l.lap_time_minutes, l.circuit_id, c.length
        FROM lap_entries l
        LEFT JOIN circuits c ON c.id = l.circuit_id
        """
    ).fetchall():
        candidate_device_distance = device_distance_for_length(row["length"], length_scale)
        score, reason = duplicate_score(
            started_on=started_on,
            duration_seconds=duration_seconds,
            raw_distance=raw_distance,
            candidate_date=row["performed_on"],
            candidate_started_at=row["started_at"],
            candidate_minutes=row["lap_time_minutes"],
            candidate_raw_distance=candidate_device_distance,
            circuit_match=session_type == "lap" and circuit_id is not None and circuit_id == row["circuit_id"],
        )
        if score >= POSSIBLE_DUPLICATE_THRESHOLD:
            candidates.append({
                "entry_type": "lap",
                "entry_id": int(row["id"]),
                "circuit_id": row["circuit_id"],
                "confidence": score,
                "reason": reason,
            })

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: float(candidate["confidence"]))


def duplicate_score(
    *,
    started_on: str | None,
    duration_seconds: int | None,
    raw_distance: float | None,
    candidate_date: str | None,
    candidate_started_at: str | None,
    candidate_minutes: float | None,
    candidate_raw_distance: float | None,
    circuit_match: bool,
) -> tuple[float, str]:
    score = 0.0
    reasons = []
    day_delta = date_delta_days(started_on, candidate_date)
    if day_delta == 0:
        score += 0.25
        reasons.append("same date")
    elif day_delta == 1:
        score += 0.12
        reasons.append("adjacent date")

    start_delta = start_delta_minutes(started_on, candidate_started_at)
    if start_delta is not None:
        if start_delta <= 2:
            score += 0.25
            reasons.append("start time within 2 minutes")
        elif start_delta <= 10:
            score += 0.18
            reasons.append("start time within 10 minutes")
        elif start_delta <= 60:
            score += 0.08
            reasons.append("start time within 60 minutes")

    duration_score, duration_reason = similarity_score(
        duration_seconds,
        candidate_minutes * 60 if candidate_minutes is not None else None,
        exact_points=0.25,
        close_points=0.18,
        loose_points=0.08,
    )
    score += duration_score
    if duration_reason:
        reasons.append(f"duration {duration_reason}")

    distance_score, distance_reason = similarity_score(
        raw_distance,
        candidate_raw_distance,
        exact_points=0.35,
        close_points=0.24,
        loose_points=0.1,
    )
    score += distance_score
    if distance_reason:
        reasons.append(f"distance {distance_reason}")

    if circuit_match:
        score += 0.1
        reasons.append("same circuit target")

    return min(score, 1.0), "; ".join(reasons)


def similarity_score(
    observed: float | int | None,
    expected: float | int | None,
    *,
    exact_points: float,
    close_points: float,
    loose_points: float,
) -> tuple[float, str | None]:
    if observed is None or expected in (None, 0):
        return 0.0, None
    pct_diff = abs(float(observed) - float(expected)) / abs(float(expected))
    if pct_diff <= 0.03:
        return exact_points, f"within {pct_diff:.1%}"
    if pct_diff <= 0.08:
        return close_points, f"within {pct_diff:.1%}"
    if pct_diff <= 0.15:
        return loose_points, f"within {pct_diff:.1%}"
    return 0.0, None


def suggestion_for_duplicate(suggestion: dict[str, object], duplicate: dict[str, object]) -> dict[str, object]:
    output = dict(suggestion)
    entry_type = str(duplicate["entry_type"])
    if entry_type in {"lap", "sprint"}:
        output["session_type"] = entry_type
    if entry_type == "lap":
        output["circuit_id"] = duplicate.get("circuit_id")
    prefix = "Strong duplicate" if float(duplicate["confidence"]) >= STRONG_DUPLICATE_THRESHOLD else "Possible duplicate"
    output["confidence"] = duplicate["confidence"]
    output["reason"] = f"{prefix}: {duplicate['reason']}"
    return output


def review_status_for_activity(duplicate: dict[str, object] | None, hr: int | None) -> str:
    if duplicate and float(duplicate["confidence"]) >= STRONG_DUPLICATE_THRESHOLD:
        return "already_logged"
    if duplicate and float(duplicate["confidence"]) >= POSSIBLE_DUPLICATE_THRESHOLD:
        return "possible_duplicate"
    if hr is None:
        return "needs_hr"
    return "needs_review"


def hr_for_duplicate(conn: sqlite3.Connection, duplicate: dict[str, object] | None) -> int | None:
    if not duplicate:
        return None
    table = {"sprint": "sprint_entries", "lap": "lap_entries"}.get(str(duplicate["entry_type"]))
    if table is None:
        return None
    row = conn.execute(f"SELECT hr FROM {table} WHERE id = ?", (int(duplicate["entry_id"]),)).fetchone()
    if row is None or row["hr"] is None:
        return None
    return int(row["hr"])


def populate_missing_duplicate_hr(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT id, duplicate_entry_type, duplicate_entry_id, duplicate_confidence, duplicate_reason
        FROM raw_activities
        WHERE hr IS NULL
          AND duplicate_entry_type IS NOT NULL
          AND duplicate_entry_id IS NOT NULL
        """
    ).fetchall()
    updated = 0
    for row in rows:
        duplicate = {
            "entry_type": row["duplicate_entry_type"],
            "entry_id": row["duplicate_entry_id"],
            "confidence": row["duplicate_confidence"],
            "reason": row["duplicate_reason"],
        }
        duplicate_hr = hr_for_duplicate(conn, duplicate)
        if duplicate_hr is None:
            continue
        conn.execute("UPDATE raw_activities SET hr = ? WHERE id = ?", (duplicate_hr, row["id"]))
        updated += 1
    if updated:
        conn.commit()
    return updated


def backfill_duplicate_started_at(
    conn: sqlite3.Connection,
    duplicate: dict[str, object],
    started_on: str | None,
) -> bool:
    if not started_on or not has_time_component(started_on):
        return False
    table = {"sprint": "sprint_entries", "lap": "lap_entries"}.get(str(duplicate["entry_type"]))
    if table is None:
        return False
    row = conn.execute(f"SELECT started_at FROM {table} WHERE id = ?", (int(duplicate["entry_id"]),)).fetchone()
    if row is None or row["started_at"]:
        return False
    conn.execute(f"UPDATE {table} SET started_at = ? WHERE id = ?", (started_on, int(duplicate["entry_id"])))
    return True


def import_activity_file_to_review(conn: sqlite3.Connection, params: dict[str, FormValue]) -> int:
    source = required(params, "source")
    upload = params.get("activity_upload")
    if isinstance(upload, UploadedFile) and upload.filename and upload.content:
        rows = load_uploaded_activity_file(upload, source)
    else:
        rows = load_activity_file(required(params, "activity_file"), source)
    imported = 0
    for row in rows:
        add_raw_activity(conn, row)
        imported += 1
    return imported


def load_uploaded_activity_file(upload: UploadedFile, source: str) -> list[dict[str, str]]:
    filename = Path(upload.filename).name or "activity_upload"
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / filename
        path.write_bytes(upload.content)
        return load_activity_file(path, source)


def add_raw_activity(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    editable_calibration_profile(conn)
    source = params["source"].strip()
    source_activity_id = empty_to_none(params.get("source_activity_id"))
    title = empty_to_none(params.get("title"))
    raw_distance = maybe_float(params.get("raw_distance"))
    started_on = normalize_datetime(empty_to_none(params.get("started_on")))
    duration_seconds = maybe_int(params.get("duration_seconds"))
    hr = maybe_int(params.get("hr"))
    raw_payload = empty_to_none(params.get("raw_payload"))
    suggestion = suggest_activity_classification(conn, raw_distance)
    duplicate = find_activity_duplicate(
        conn,
        started_on=started_on,
        duration_seconds=duration_seconds,
        raw_distance=raw_distance,
        session_type=str(suggestion["session_type"]),
        circuit_id=suggestion.get("circuit_id"),
    )
    if duplicate:
        suggestion = suggestion_for_duplicate(suggestion, duplicate)
    if duplicate and hr is None:
        hr = hr_for_duplicate(conn, duplicate)
    review_status = review_status_for_activity(duplicate, hr)
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO raw_activities (
            source, source_activity_id, title, started_on, duration_seconds,
            raw_distance, hr, raw_payload, review_status, session_type, circuit_id,
            classification_confidence, classification_reason,
            duplicate_entry_type, duplicate_entry_id, duplicate_confidence,
            duplicate_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source,
            source_activity_id,
            title,
            started_on,
            duration_seconds,
            raw_distance,
            hr,
            raw_payload,
            review_status,
            suggestion["session_type"],
            suggestion.get("circuit_id"),
            suggestion["confidence"],
            suggestion["reason"],
            duplicate["entry_type"] if duplicate else None,
            duplicate["entry_id"] if duplicate else None,
            duplicate["confidence"] if duplicate else None,
            duplicate["reason"] if duplicate else None,
        ),
    )
    if cursor.rowcount == 0:
        enrich_existing_raw_activity(
            conn,
            source=source,
            source_activity_id=source_activity_id,
            title=title,
            started_on=started_on,
            duration_seconds=duration_seconds,
            raw_distance=raw_distance,
            hr=hr,
            raw_payload=raw_payload,
        )
    elif duplicate and duplicate["confidence"] >= STRONG_DUPLICATE_THRESHOLD:
        backfill_duplicate_started_at(conn, duplicate, started_on)
    conn.commit()


def enrich_existing_raw_activity(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_activity_id: str | None,
    title: str | None,
    started_on: str | None,
    duration_seconds: int | None,
    raw_distance: float | None,
    hr: int | None,
    raw_payload: str | None,
) -> None:
    if source_activity_id is None:
        return
    row = conn.execute(
        "SELECT * FROM raw_activities WHERE source = ? AND source_activity_id = ?",
        (source, source_activity_id),
    ).fetchone()
    if row is None:
        return
    existing_duplicate = None
    if row["duplicate_entry_type"] and row["duplicate_entry_id"]:
        existing_duplicate = {
            "entry_type": row["duplicate_entry_type"],
            "entry_id": row["duplicate_entry_id"],
            "confidence": row["duplicate_confidence"],
            "reason": row["duplicate_reason"],
        }
    if hr is None and existing_duplicate:
        hr = hr_for_duplicate(conn, existing_duplicate)
    conn.execute(
        """
        UPDATE raw_activities
        SET title = ?,
            started_on = ?,
            duration_seconds = ?,
            raw_distance = ?,
            hr = ?,
            raw_payload = ?
        WHERE id = ?
        """,
        (
            prefer_existing(row["title"], title),
            prefer_existing(row["started_on"], started_on),
            prefer_existing(row["duration_seconds"], duration_seconds),
            prefer_existing(row["raw_distance"], raw_distance),
            prefer_existing(row["hr"], hr),
            merge_raw_payload(row["raw_payload"], raw_payload),
            row["id"],
        ),
    )
    if existing_duplicate and (row["duplicate_confidence"] or 0) >= STRONG_DUPLICATE_THRESHOLD:
        backfill_duplicate_started_at(conn, existing_duplicate, started_on or row["started_on"])


def prefer_existing(existing: object, incoming: object) -> object:
    return existing if existing not in (None, "") else incoming


def classify_activity(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    session_type = params["session_type"]
    circuit_id = maybe_int(params.get("circuit_id")) if session_type == "lap" else None
    if session_type == "ignore":
        review_status = "ignored"
    elif session_type in ("lap", "sprint"):
        review_status = "ready_to_import"
    else:
        review_status = "needs_review"
    conn.execute(
        """
        UPDATE raw_activities
        SET session_type = ?,
            circuit_id = ?,
            review_status = ?,
            classification_confidence = 1,
            classification_reason = 'Manual review'
        WHERE id = ?
        """,
        (session_type, circuit_id, review_status, int(params["id"])),
    )
    conn.commit()


def confirm_duplicate_activity(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    row = conn.execute("SELECT * FROM raw_activities WHERE id = ?", (int(required(params, "id")),)).fetchone()
    if row is None:
        raise ValueError("Raw activity was not found.")
    if not row["duplicate_entry_type"] or not row["duplicate_entry_id"]:
        raise ValueError("Raw activity does not have a duplicate match.")
    duplicate = {
        "entry_type": row["duplicate_entry_type"],
        "entry_id": row["duplicate_entry_id"],
        "confidence": row["duplicate_confidence"] or 1.0,
        "reason": row["duplicate_reason"] or "Manually confirmed duplicate.",
    }
    backfilled = backfill_duplicate_started_at(conn, duplicate, row["started_on"])
    reason = "Manual duplicate confirmation"
    if backfilled:
        reason += "; start time backfilled"
    duplicate_hr = hr_for_duplicate(conn, duplicate)
    conn.execute(
        """
        UPDATE raw_activities
        SET review_status = 'already_logged',
            hr = COALESCE(hr, ?),
            classification_confidence = 1,
            classification_reason = ?
        WHERE id = ?
        """,
        (duplicate_hr, reason, row["id"]),
    )
    conn.commit()


def promote_raw_activity(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    raw_id = int(required(params, "id"))
    row = conn.execute("SELECT * FROM raw_activities WHERE id = ?", (raw_id,)).fetchone()
    if row is None:
        raise ValueError("Raw activity was not found.")
    if row["review_status"] == "imported" and raw_activity_has_entry(conn, raw_id):
        return
    if row["review_status"] in ("already_logged", "imported"):
        raise ValueError("Raw activity has already been handled.")
    if raw_activity_has_entry(conn, raw_id):
        raise ValueError("Raw activity is already linked to an entry.")
    payload = raw_payload_dict(row)

    session_type = required(params, "session_type")
    if session_type not in ("sprint", "lap"):
        raise ValueError("Raw activity can only be imported as sprint or lap.")
    performed_on = empty_to_none(params.get("performed_on")) or date_part(row["started_on"])
    if performed_on is None:
        raise ValueError("Date is required to import an activity.")
    started_at = normalize_datetime(row["started_on"]) if has_time_component(row["started_on"]) else None
    duration_minutes = maybe_float(params.get("duration_minutes"))
    if duration_minutes is None:
        duration_minutes = duration_seconds_to_minutes(row["duration_seconds"])
    hr = maybe_int(params.get("hr"))
    if hr is None:
        hr = row["hr"]
    if hr is None:
        raise ValueError("HR is required to import an activity.")
    resistance = maybe_int(params.get("resistance"))
    if resistance is None:
        resistance = 4
    if resistance < 1 or resistance > 12:
        raise ValueError("Resistance must be between 1 and 12.")
    rpm = maybe_float(params.get("rpm"))
    if rpm is None:
        rpm = maybe_float(str(payload.get("average_cadence"))) if payload.get("average_cadence") is not None else None
    entry_index = maybe_int(params.get("entry_index"))
    notes = empty_to_none(params.get("notes"))

    if session_type == "lap":
        circuit_id = maybe_int(params.get("circuit_id")) or row["circuit_id"]
        if circuit_id is None:
            raise ValueError("Circuit is required to import a lap activity.")
        cursor = conn.execute(
            """
            INSERT INTO lap_entries (
                performed_on, started_at, lap_index, circuit_id, lap_time_minutes,
                hr, resistance, rpm, raw_activity_id, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                performed_on,
                started_at,
                entry_index,
                circuit_id,
                duration_minutes,
                hr,
                resistance,
                rpm,
                raw_id,
                notes,
            ),
        )
        entry_id = cursor.lastrowid
        circuit_for_raw = circuit_id
    else:
        cursor = conn.execute(
            """
            INSERT INTO sprint_entries (
                performed_on, started_at, sprint_index, duration_minutes,
                rpm, device_watts, hr, resistance, device_distance, raw_activity_id, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                performed_on,
                started_at,
                entry_index,
                duration_minutes,
                rpm,
                promotion_device_watts(params, payload),
                hr,
                resistance,
                row["raw_distance"],
                raw_id,
                notes,
            ),
        )
        entry_id = cursor.lastrowid
        circuit_for_raw = None

    conn.execute(
        """
        UPDATE raw_activities
        SET review_status = 'imported',
            session_type = ?,
            circuit_id = ?,
            hr = ?,
            classification_confidence = 1,
            classification_reason = ?
        WHERE id = ?
        """,
        (
            session_type,
            circuit_for_raw,
            hr,
            f"Imported as {session_type} entry #{entry_id}",
            raw_id,
        ),
    )
    conn.commit()


def raw_activity_has_entry(conn: sqlite3.Connection, raw_id: int) -> bool:
    sprint = conn.execute("SELECT id FROM sprint_entries WHERE raw_activity_id = ? LIMIT 1", (raw_id,)).fetchone()
    if sprint is not None:
        return True
    lap = conn.execute("SELECT id FROM lap_entries WHERE raw_activity_id = ? LIMIT 1", (raw_id,)).fetchone()
    return lap is not None


def promotion_device_watts(params: dict[str, str], payload: dict[str, object]) -> float | None:
    value = maybe_float(params.get("device_watts"))
    if value is not None:
        return value
    average_watts = payload.get("average_watts")
    return maybe_float(str(average_watts)) if average_watts is not None else None


def add_sprint_entry(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    performed_on = required(params, "performed_on")
    started_at = combine_entry_start(performed_on, params.get("started_at"))
    resistance = validated_resistance(params.get("resistance"))
    conn.execute(
        """
        INSERT INTO sprint_entries (
            performed_on, started_at, day_number, sprint_index, duration_minutes,
            rpm, device_watts, hr, resistance, device_distance, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            performed_on,
            started_at,
            maybe_int(params.get("day_number")),
            maybe_int(params.get("sprint_index")),
            maybe_float(params.get("duration_minutes")),
            maybe_float(params.get("rpm")),
            maybe_float(params.get("device_watts")),
            maybe_int(params.get("hr")),
            resistance,
            maybe_float(params.get("device_distance")),
            empty_to_none(params.get("notes")),
        ),
    )
    conn.commit()


def update_sprint_entry(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    entry_id = int(required(params, "id"))
    conn.execute(
        """
        UPDATE sprint_entries
        SET performed_on = ?,
            started_at = ?,
            sprint_index = ?,
            duration_minutes = ?,
            rpm = ?,
            device_watts = ?,
            hr = ?,
            resistance = ?,
            device_distance = ?
        WHERE id = ?
        """,
        (
            required(params, "performed_on"),
            combine_entry_start(required(params, "performed_on"), params.get("started_at")),
            maybe_int(params.get("sprint_index")),
            maybe_float(params.get("duration_minutes")),
            maybe_float(params.get("rpm")),
            maybe_float(params.get("device_watts")),
            maybe_int(params.get("hr")),
            validated_resistance(params.get("resistance")),
            maybe_float(params.get("device_distance")),
            entry_id,
        ),
    )
    conn.commit()


def add_lap_entry(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    performed_on = required(params, "performed_on")
    started_at = combine_entry_start(performed_on, params.get("started_at"))
    circuit_id = maybe_int(params.get("circuit_id"))
    if circuit_id is None:
        raise ValueError("A circuit is required for lap entries.")
    resistance = validated_resistance(params.get("resistance"))
    conn.execute(
        """
        INSERT INTO lap_entries (
            performed_on, started_at, lap_index, circuit_id, lap_time_minutes,
            hr, resistance, rpm, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            performed_on,
            started_at,
            maybe_int(params.get("lap_index")),
            circuit_id,
            lap_time_minutes_from_params(params),
            maybe_int(params.get("hr")),
            resistance,
            maybe_float(params.get("rpm")),
            empty_to_none(params.get("notes")),
        ),
    )
    conn.commit()


def update_lap_entry(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    entry_id = int(required(params, "id"))
    circuit_id = maybe_int(params.get("circuit_id"))
    if circuit_id is None:
        raise ValueError("A circuit is required for lap entries.")
    conn.execute(
        """
        UPDATE lap_entries
        SET performed_on = ?,
            started_at = ?,
            lap_index = ?,
            circuit_id = ?,
            lap_time_minutes = ?,
            hr = ?,
            resistance = ?,
            rpm = ?
        WHERE id = ?
        """,
        (
            required(params, "performed_on"),
            combine_entry_start(required(params, "performed_on"), params.get("started_at")),
            maybe_int(params.get("lap_index")),
            circuit_id,
            lap_time_minutes_from_params(params),
            maybe_int(params.get("hr")),
            validated_resistance(params.get("resistance")),
            maybe_float(params.get("rpm")),
            entry_id,
        ),
    )
    conn.commit()


def delete_entry(conn: sqlite3.Connection, params: dict[str, FormValue]) -> None:
    entry_type = required(params, "entry_type")
    entry_id = maybe_int(required(params, "id"))
    if entry_id is None:
        raise ValueError("Entry id is required.")
    table = {"sprint": "sprint_entries", "lap": "lap_entries"}.get(entry_type)
    if table is None:
        raise ValueError("Entry type must be sprint or lap.")
    row = conn.execute(f"SELECT raw_activity_id FROM {table} WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise ValueError("Entry was not found.")
    raw_activity_id = row["raw_activity_id"]
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (entry_id,))
    conn.execute(
        """
        UPDATE raw_activities
        SET duplicate_entry_type = NULL,
            duplicate_entry_id = NULL,
            duplicate_confidence = NULL,
            duplicate_reason = NULL,
            review_status = CASE
                WHEN review_status = 'already_logged' AND hr IS NULL THEN 'needs_hr'
                WHEN review_status = 'already_logged' THEN 'needs_review'
                ELSE review_status
            END
        WHERE duplicate_entry_type = ? AND duplicate_entry_id = ?
        """,
        (entry_type, entry_id),
    )
    if raw_activity_id is not None:
        conn.execute(
            """
            UPDATE raw_activities
            SET review_status = CASE WHEN hr IS NULL THEN 'needs_hr' ELSE 'needs_review' END
            WHERE id = ? AND review_status = 'imported'
            """,
            (raw_activity_id,),
        )
    conn.commit()


def dismiss_duplicate_pair(conn: sqlite3.Connection, params: dict[str, FormValue]) -> None:
    entry_type = required(params, "entry_type")
    table = {"sprint": "sprint_entries", "lap": "lap_entries"}.get(entry_type)
    if table is None:
        raise ValueError("Entry type must be sprint or lap.")
    first_id = maybe_int(required(params, "first_id"))
    second_id = maybe_int(required(params, "second_id"))
    if first_id is None or second_id is None:
        raise ValueError("Both entry ids are required.")
    if first_id == second_id:
        raise ValueError("Duplicate pair must contain two different entries.")
    first_id, second_id = duplicate_pair_key(first_id, second_id)
    matching_rows = conn.execute(
        f"SELECT COUNT(*) AS total FROM {table} WHERE id IN (?, ?)",
        (first_id, second_id),
    ).fetchone()["total"]
    if matching_rows != 2:
        raise ValueError("Both entries must exist before a duplicate can be dismissed.")
    conn.execute(
        """
        INSERT OR IGNORE INTO duplicate_dismissals (
            entry_type, first_entry_id, second_entry_id
        )
        VALUES (?, ?, ?)
        """,
        (entry_type, first_id, second_id),
    )
    conn.commit()


def validated_resistance(value: str | None) -> int | None:
    resistance = maybe_int(value)
    if resistance is not None and not 1 <= resistance <= 12:
        raise ValueError("Resistance must be between 1 and 12.")
    return resistance


def mechanical_efficiency_value(value: str | None) -> float:
    efficiency = maybe_float(value)
    if efficiency is None:
        efficiency = 0.22
    if not 0 < efficiency <= 1:
        raise ValueError("Mechanical efficiency must be between 0 and 1.")
    return efficiency


def editable_calibration_profile(conn: sqlite3.Connection) -> sqlite3.Row:
    profile = conn.execute(
        "SELECT * FROM calibration_profiles WHERE active = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if profile is None:
        conn.execute(
            """
            INSERT INTO calibration_profiles (name, length_scale, distance_per_stroke, mechanical_efficiency, active)
            VALUES ('Default under-desk bike', 0.45, NULL, 0.22, 1)
            """
        )
        conn.commit()
        profile = conn.execute("SELECT * FROM calibration_profiles WHERE active = 1 ORDER BY id LIMIT 1").fetchone()
    return profile


def update_calibration_profile(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    profile_id = int(required(params, "id"))
    conn.execute(
        """
        UPDATE calibration_profiles
        SET name = ?, length_scale = ?, distance_per_stroke = ?, mechanical_efficiency = ?, active = 1
        WHERE id = ?
        """,
        (
            required(params, "name"),
            float(required(params, "length_scale")),
            maybe_float(params.get("distance_per_stroke")),
            mechanical_efficiency_value(params.get("mechanical_efficiency")),
            profile_id,
        ),
    )
    conn.commit()


def resistance_scaling_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    existing = {
        int(row["resistance"]): row["scaling"]
        for row in conn.execute("SELECT resistance, scaling FROM resistance_scaling").fetchall()
    }
    return [{"resistance": resistance, "scaling": existing.get(resistance)} for resistance in range(1, 13)]


def update_resistance_scaling(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    for resistance in range(1, 13):
        scaling = maybe_float(params.get(f"scaling_{resistance}"))
        if scaling is None:
            continue
        conn.execute(
            """
            INSERT INTO resistance_scaling (resistance, scaling)
            VALUES (?, ?)
            ON CONFLICT(resistance) DO UPDATE SET scaling = excluded.scaling
            """,
            (resistance, scaling),
        )
    conn.commit()


def calculate_resistance_calibration_preview(conn: sqlite3.Connection, params: dict[str, FormValue]) -> dict[str, object]:
    source_id = maybe_int(params.get("source_raw_activity_id"))
    source_defaults = uploaded_fit_calibration_source_defaults(conn, params)
    if source_defaults is None and source_id is not None:
        source_defaults = fit_calibration_source_defaults(conn, source_id)
    if source_id is not None and source_defaults is None:
        raise ValueError("FIT calibration source was not found or does not contain device watts.")

    tested_on = empty_to_none(params.get("tested_on")) or (source_defaults or {}).get("date")
    if tested_on is None:
        raise ValueError("Date is required.")
    resistance = maybe_int(params.get("resistance"))
    if resistance is None:
        raise ValueError("Resistance is required.")
    device_watts = maybe_float(params.get("device_watts"))
    if device_watts is None and source_defaults is not None:
        device_watts = maybe_float(str(source_defaults["device_watts"]))
    if device_watts is None or device_watts <= 0:
        raise ValueError("Device watts must be greater than zero.")

    mass_kg = maybe_float(params.get("mass_kg"))
    if mass_kg is None and source_defaults is not None:
        mass_kg = maybe_float(source_defaults.get("mass_kg"))
    hr = maybe_int(params.get("hr"))
    if hr is None and source_defaults is not None:
        hr = maybe_int(source_defaults.get("hr"))
    profile = editable_calibration_profile(conn)
    mechanical_efficiency = mechanical_efficiency_value(params.get("mechanical_efficiency") or profile["mechanical_efficiency"])
    metabolic_watts = None
    expected_watts_source = "manual"
    expected_watts = maybe_float(params.get("expected_watts"))
    if expected_watts is None:
        metabolic_watts = estimated_watts_from_hr(conn, hr, mass_kg)
        expected_watts = estimated_mechanical_watts_from_hr(conn, hr, mass_kg, mechanical_efficiency)
        expected_watts_source = "HR/MET x mechanical efficiency"
    if expected_watts is None or expected_watts <= 0:
        raise ValueError("Expected watts, or HR and mass kg, are required.")

    calculated_scaling = expected_watts / device_watts
    current = conn.execute(
        "SELECT scaling FROM resistance_scaling WHERE resistance = ?",
        (resistance,),
    ).fetchone()
    current_scaling = float(current["scaling"]) if current else None
    change_pct = None
    if current_scaling:
        change_pct = (calculated_scaling - current_scaling) / current_scaling

    duration_minutes = maybe_float(params.get("duration_minutes"))
    if duration_minutes is None and source_defaults is not None:
        duration_minutes = maybe_float(source_defaults.get("duration_minutes"))

    source = empty_to_none(params.get("source")) or (source_defaults or {}).get("source")
    source_activity_id = empty_to_none(params.get("source_activity_id")) or (source_defaults or {}).get("source_activity_id")
    source_title = empty_to_none(params.get("source_title")) or (source_defaults or {}).get("source_title")
    source_started_on = empty_to_none(params.get("source_started_on")) or (source_defaults or {}).get("source_started_on")
    source_file = empty_to_none(params.get("source_file")) or (source_defaults or {}).get("source_file")
    file_sha256 = empty_to_none(params.get("file_sha256")) or (source_defaults or {}).get("file_sha256")
    raw_payload = empty_to_none(params.get("raw_payload")) or (source_defaults or {}).get("raw_payload")
    quality_flags = empty_to_none(params.get("quality_flags")) or (source_defaults or {}).get("quality_flags")
    if raw_payload and empty_to_none(params.get("quality_flags")) is None:
        payload = payload_from_text(raw_payload)
        if payload.get("format") == "fit":
            quality_flags = calibration_quality_flags(duration_minutes, payload, hr)

    return {
        "tested_on": tested_on,
        "resistance": resistance,
        "duration_minutes": duration_minutes,
        "device_watts": device_watts,
        "expected_watts": expected_watts,
        "expected_watts_source": expected_watts_source,
        "metabolic_watts": metabolic_watts,
        "mechanical_efficiency": mechanical_efficiency,
        "hr": hr,
        "mass_kg": mass_kg,
        "calculated_scaling": calculated_scaling,
        "current_scaling": current_scaling,
        "change_pct": change_pct,
        "notes": empty_to_none(params.get("notes")) or (source_defaults or {}).get("notes"),
        "source_raw_activity_id": source_id,
        "source": source,
        "source_activity_id": source_activity_id,
        "source_title": source_title,
        "source_started_on": source_started_on,
        "source_file": source_file,
        "file_sha256": file_sha256,
        "raw_payload": raw_payload,
        "quality_flags": quality_flags,
    }


def add_resistance_calibration_test(conn: sqlite3.Connection, params: dict[str, FormValue]) -> None:
    preview = calculate_resistance_calibration_preview(conn, params)
    conn.execute(
        """
        INSERT INTO resistance_calibration_tests (
            tested_on, resistance, duration_minutes, device_watts,
            expected_watts, hr, mass_kg, calculated_scaling, notes,
            source, source_activity_id, source_title, source_started_on,
            source_file, file_sha256, raw_payload, quality_flags
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            preview["tested_on"],
            preview["resistance"],
            preview["duration_minutes"],
            preview["device_watts"],
            preview["expected_watts"],
            preview["hr"],
            preview["mass_kg"],
            preview["calculated_scaling"],
            preview["notes"],
            preview["source"],
            preview["source_activity_id"],
            preview["source_title"],
            preview["source_started_on"],
            preview["source_file"],
            preview["file_sha256"],
            preview["raw_payload"],
            preview["quality_flags"],
        ),
    )
    conn.execute(
        """
        INSERT INTO resistance_scaling (resistance, scaling)
        VALUES (?, ?)
        ON CONFLICT(resistance) DO UPDATE SET scaling = excluded.scaling
        """,
        (preview["resistance"], preview["calculated_scaling"]),
    )
    conn.commit()


def add_mass_log(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    conn.execute(
        """
        INSERT INTO mass_log (measured_on, mass_kg)
        VALUES (?, ?)
        ON CONFLICT(measured_on) DO UPDATE SET mass_kg = excluded.mass_kg
        """,
        (required(params, "measured_on"), float(required(params, "mass_kg"))),
    )
    conn.commit()


def latest_mass_kg(conn: sqlite3.Connection) -> float | None:
    row = conn.execute(
        """
        SELECT mass_kg
        FROM mass_log
        ORDER BY measured_on DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return float(row["mass_kg"]) if row else None


def update_mass_log(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    conn.execute(
        "UPDATE mass_log SET measured_on = ?, mass_kg = ? WHERE id = ?",
        (required(params, "measured_on"), float(required(params, "mass_kg")), int(required(params, "id"))),
    )
    conn.commit()


def circuit_rows_with_goals(conn: sqlite3.Connection, include_inactive: bool = False) -> list[dict[str, object]]:
    profile = editable_calibration_profile(conn)
    length_scale = float(profile["length_scale"])
    where = "" if include_inactive else "WHERE active = 1"
    rows = conn.execute(f"SELECT * FROM circuits {where} ORDER BY name").fetchall()
    return [
        {
            **dict(row),
            "calculated_device_distance": device_distance_for_length(row["length"], length_scale),
        }
        for row in rows
    ]


def circuit_select_options(circuits: list[dict[str, object]] | list[sqlite3.Row], selected_id: int | None = None) -> str:
    options = ['<option value="">Select circuit</option>']
    for circuit in circuits:
        selected = " selected" if selected_id == circuit["id"] else ""
        goal = circuit.get("calculated_device_distance") if isinstance(circuit, dict) else None
        data_goal = f' data-goal="{fmt_raw(goal)}"' if goal is not None else ""
        options.append(f'<option value="{circuit["id"]}"{selected}{data_goal}>{escape(str(circuit["name"]))}</option>')
    return "".join(options)


def circuit_goal_script() -> str:
    return """
<script>
(() => {
  const select = document.getElementById('lap-circuit');
  const output = document.getElementById('lap-goal');
  if (!select || !output) return;
  const update = () => {
    const option = select.options[select.selectedIndex];
    output.value = option?.dataset?.goal || '';
  };
  select.addEventListener('change', update);
  update();
})();
</script>"""


def resistance_select_options(selected: int | None = None) -> str:
    return "".join(
        f'<option value="{resistance}"{" selected" if selected == resistance else ""}>{resistance}</option>'
        for resistance in range(1, 13)
    )


def hidden_calibration_inputs(preview: dict[str, object]) -> str:
    fields = [
        "tested_on",
        "resistance",
        "duration_minutes",
        "device_watts",
        "expected_watts",
        "hr",
        "mass_kg",
        "notes",
        "source",
        "source_activity_id",
        "source_title",
        "source_started_on",
        "source_file",
        "file_sha256",
        "raw_payload",
        "quality_flags",
    ]
    inputs = []
    for field in fields:
        value = preview.get(field)
        if value is None:
            value = ""
        inputs.append(f'<input type="hidden" name="{field}" value="{escape(str(value))}">')
    return "".join(inputs)


def select_option(value: str, current: str) -> str:
    selected = " selected" if value == current else ""
    return f'<option value="{value}"{selected}>{value}</option>'


def best_lap(metrics: dict[str, object]) -> str:
    minutes = metrics["best_lap_minutes"]
    circuit = metrics["best_lap_circuit"]
    if minutes is None:
        return "No laps"
    return f"{fmt_minutes(minutes)} {circuit or ''}".strip()


def fmt_num(value: object, digits: int = 1) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_raw(value: object) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.6g}"
    except (TypeError, ValueError):
        return str(value)


def step_value(value: object, digits: int) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def signed_num(value: object, digits: int = 1) -> str:
    if value is None:
        return ""
    num = float(value)
    return f"{num:+,.{digits}f}"


def signed_minutes(value: object) -> str:
    if value is None:
        return ""
    prefix = "+" if float(value) >= 0 else "-"
    return f"{prefix}{fmt_minutes(abs(float(value)))}"


def signed_percent(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value):+,.1%}"


def fmt_percent(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value):.1%}"


def fmt_minutes(value: object) -> str:
    if value is None or value == "":
        return ""
    total_seconds = int(round(float(value) * 60))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def duration_seconds_to_minutes(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value) / 60


def fmt_start_time(value: object) -> str:
    if value in (None, ""):
        return ""
    text = str(value)
    parsed = parse_datetime(text)
    if parsed is not None and has_time_component(text):
        return parsed.strftime("%H:%M")
    return text


def time_input_value(value: object) -> str:
    if value in (None, ""):
        return ""
    text = str(value)
    parsed = parse_datetime(text)
    if parsed is not None and has_time_component(text):
        return parsed.strftime("%H:%M")
    if ":" in text:
        return text[:5]
    return ""


def combine_entry_start(performed_on: str, value: FormValue | None) -> str | None:
    start = empty_to_none(value)
    if start is None:
        return None
    if has_time_component(start):
        return normalize_datetime(start)
    if ":" in start:
        return f"{performed_on}T{start[:5]}"
    return normalize_datetime(start)


def entry_resistance_value(value: object) -> int:
    if value in (None, ""):
        return 4
    return int(float(value))


def normalize_datetime(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if " " in cleaned and "T" not in cleaned:
        cleaned = cleaned.replace(" ", "T", 1)
    return cleaned


def has_time_component(value: str | None) -> bool:
    if value is None:
        return False
    cleaned = value.strip()
    return len(cleaned) > 10 and ("T" in cleaned or " " in cleaned)


def parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    cleaned = normalize_datetime(value)
    if cleaned is None:
        return None
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def date_delta_days(started_on: str | None, candidate_date: str | None) -> int | None:
    activity_date = date_part(started_on)
    manual_date = date_part(candidate_date)
    if activity_date is None or manual_date is None:
        return None
    try:
        return abs((datetime.fromisoformat(activity_date) - datetime.fromisoformat(manual_date)).days)
    except ValueError:
        return None


def start_delta_minutes(started_on: str | None, candidate_started_at: str | None) -> float | None:
    activity_start = parse_datetime(started_on)
    manual_start = parse_datetime(candidate_started_at)
    if activity_start is None or manual_start is None:
        return None
    return abs((activity_start - manual_start).total_seconds()) / 60


def date_part(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) < 10:
        return None
    return cleaned[:10]


def lap_time_minutes_from_params(params: dict[str, FormValue]) -> float | None:
    existing = empty_to_none(params.get("lap_time_minutes"))
    if existing is not None:
        return duration_text_to_minutes(existing)
    minutes = maybe_int(params.get("lap_time_min"))
    seconds = maybe_int(params.get("lap_time_sec"))
    if minutes is None and seconds is None:
        return None
    minutes = minutes or 0
    seconds = seconds or 0
    if seconds < 0 or seconds > 59:
        raise ValueError("Lap seconds must be between 0 and 59.")
    return minutes + (seconds / 60)


def duration_text_to_minutes(value: str) -> float:
    cleaned = value.strip()
    if ":" not in cleaned:
        minutes = float(cleaned)
        if minutes < 0:
            raise ValueError("Lap time cannot be negative.")
        return minutes
    parts = cleaned.split(":")
    if len(parts) not in (2, 3) or any(part.strip() == "" for part in parts):
        raise ValueError("Lap time must use minutes:seconds or hours:minutes:seconds.")
    try:
        numbers = [int(part) for part in parts]
    except ValueError as exc:
        raise ValueError("Lap time must use whole minutes and seconds.") from exc
    if any(number < 0 for number in numbers):
        raise ValueError("Lap time cannot be negative.")
    if len(numbers) == 2:
        minutes, seconds = numbers
        hours = 0
    else:
        hours, minutes, seconds = numbers
        if minutes > 59:
            raise ValueError("Lap minutes must be between 0 and 59 when hours are supplied.")
    if seconds > 59:
        raise ValueError("Lap seconds must be between 0 and 59.")
    return (hours * 60) + minutes + (seconds / 60)


def duration_entry_value(value: object) -> str:
    if value in (None, ""):
        return ""
    total_seconds = int(round(float(value) * 60))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def maybe_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def maybe_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def parse_post_params(content_type: str, body: bytes) -> dict[str, FormValue]:
    if content_type.lower().startswith("multipart/form-data"):
        return parse_multipart_params(content_type, body)
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def parse_multipart_params(content_type: str, body: bytes) -> dict[str, FormValue]:
    headers = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    message = BytesParser(policy=policy.default).parsebytes(headers + body)
    if not message.is_multipart():
        return {}
    params: dict[str, FormValue] = {}
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename is not None:
            params[name] = UploadedFile(Path(filename).name, payload)
        else:
            charset = part.get_content_charset() or "utf-8"
            params[name] = payload.decode(charset, errors="replace")
    return params


def required(params: dict[str, FormValue], key: str) -> str:
    value = empty_to_none(params.get(key))
    if value is None:
        raise ValueError(f"{key} is required.")
    return value


def empty_to_none(value: FormValue | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, UploadedFile):
        return None
    cleaned = value.strip()
    return cleaned or None
