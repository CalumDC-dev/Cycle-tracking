"""Standard-library local web UI."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import sqlite3

from .calculations import (
    calculated_laps,
    calculated_sprints,
    dashboard_metrics,
    daily_summary,
    suggest_activity_classification,
)
from .database import connect, init_db
from .exporter import csv_text


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
  table { font-size: 13px; }
}
"""


def serve(db_path: str | Path, host: str = "127.0.0.1", port: int = 8000) -> None:
    handler = type("WorkoutHandler", (WorkoutRequestHandler,), {"db_path": Path(db_path)})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Serving workout tracker on http://{host}:{port}")
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
            elif parsed.path == "/review/classify":
                classify_activity(conn, params)
                self._redirect("/review")
            elif parsed.path == "/entries/sprint/add":
                add_sprint_entry(conn, params)
                self._redirect("/entries")
            elif parsed.path == "/entries/lap/add":
                add_lap_entry(conn, params)
                self._redirect("/entries")
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

    def _post_params(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(body, keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items()}

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
            routes = {
                "/export/daily_summary.csv": daily_summary(conn),
                "/export/sprints.csv": [sprint.__dict__ for sprint in calculated_sprints(conn)],
                "/export/laps.csv": [lap.__dict__ for lap in calculated_laps(conn)],
                "/export/circuits.csv": [dict(row) for row in conn.execute("SELECT * FROM circuits ORDER BY name").fetchall()],
                "/export/raw_activities.csv": [
                    dict(row)
                    for row in conn.execute("SELECT * FROM raw_activities ORDER BY imported_at DESC, id DESC").fetchall()
                ],
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
    calories = [(row["date"], row["total_calories"]) for row in daily]
    watts = [(row["date"], row["average_watts"] or 0) for row in daily]
    mass = [(row["measured_on"], row["mass_kg"]) for row in metrics["mass"]]
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
  <h2>Trends</h2>
  <div class="grid-two">
    {line_chart("Calories", calories, "#a66200")}
    {line_chart("Average Watts", watts, "#1f5a85")}
    {line_chart("Mass", mass, "#2f7d59")}
  </div>
</section>
<section class="band">
  <h2>Best Lap By Circuit</h2>
  {best_laps_table(metrics["best_laps_by_circuit"])}
</section>
<section class="band">
  <h2>Daily Summary</h2>
  {daily_table(daily)}
</section>
<section class="band">
  <h2>Exports</h2>
  <div class="actions">
    <a href="/export/daily_summary.csv">Daily summary CSV</a>
    <a href="/export/sprints.csv">Sprints CSV</a>
    <a href="/export/laps.csv">Laps CSV</a>
    <a href="/export/circuits.csv">Circuits CSV</a>
    <a href="/export/raw_activities.csv">Raw activities CSV</a>
  </div>
</section>
"""


def render_entries(conn: sqlite3.Connection) -> str:
    sprints = calculated_sprints(conn)
    laps = calculated_laps(conn)
    circuits = conn.execute("SELECT id, name FROM circuits WHERE active = 1 ORDER BY name").fetchall()
    return f"""
<section class="band">
  <h2>Add Sprint Entry</h2>
  <form class="stack" method="post" action="/entries/sprint/add">
    <label>Date<input name="performed_on" type="date" required></label>
    <label>Day number<input name="day_number" type="number" min="1"></label>
    <label>Sprint number<input name="sprint_index" type="number" min="1"></label>
    <label>Duration minutes<input name="duration_minutes" type="number" step="0.001" min="0"></label>
    <label>RPM<input name="rpm" type="number" step="0.1" min="0"></label>
    <label>Device watts<input name="device_watts" type="number" step="0.1" min="0"></label>
    <label>HR<input name="hr" type="number" min="0"></label>
    <label>Resistance<input name="resistance" type="number" min="0"></label>
    <label>Device distance<input name="device_distance" type="number" step="0.001" min="0"></label>
    <label>Notes<input name="notes"></label>
    <button type="submit">Add sprint</button>
  </form>
</section>
<section class="band">
  <h2>Add Lap Entry</h2>
  <form class="stack" method="post" action="/entries/lap/add">
    <label>Date<input name="performed_on" type="date" required></label>
    <label>Lap number<input name="lap_index" type="number" min="1"></label>
    <label>Circuit<select name="circuit_id" required>{circuit_select_options(circuits)}</select></label>
    <label>Lap time minutes<input name="lap_time_minutes" type="number" step="0.001" min="0"></label>
    <label>HR<input name="hr" type="number" min="0"></label>
    <label>Resistance<input name="resistance" type="number" min="0"></label>
    <label>RPM<input name="rpm" type="number" step="0.1" min="0"></label>
    <label>Notes<input name="notes"></label>
    <button type="submit">Add lap</button>
  </form>
</section>
<section class="band">
  <h2>Sprint Entries</h2>
  {table(
        ["Date", "Sprint", "Time", "RPM", "Device watts", "Estimated watts", "HR", "Resistance", "Cal distance", "Calories"],
        [
            [
                sprint.performed_on,
                sprint.sprint_index,
                fmt_minutes(sprint.duration_minutes),
                fmt_num(sprint.rpm, 0),
                fmt_num(sprint.device_watts, 0),
                fmt_num(sprint.estimated_watts, 1),
                sprint.hr,
                sprint.resistance,
                fmt_num(sprint.calibrated_distance, 2),
                fmt_num(sprint.calories_watts, 1),
            ]
            for sprint in sprints
        ],
    )}
</section>
<section class="band">
  <h2>Lap Entries</h2>
  {table(
        ["Date", "Lap", "Circuit", "Lap time", "Length", "Avg speed", "HR", "Resistance", "RPM", "Calories"],
        [
            [
                lap.performed_on,
                lap.lap_index,
                lap.circuit_name,
                fmt_minutes(lap.lap_time_minutes),
                fmt_num(lap.length, 3),
                fmt_num(lap.average_speed, 2),
                lap.hr,
                lap.resistance,
                fmt_num(lap.rpm, 0),
                fmt_num(lap.calories_mets, 1),
            ]
            for lap in laps
        ],
    )}
</section>
"""


def render_circuits(conn: sqlite3.Connection) -> str:
    rows = conn.execute("SELECT * FROM circuits ORDER BY name").fetchall()
    body = []
    for row in rows:
        checked = "checked" if row["active"] else ""
        body.append(f"""
<form class="inline" method="post" action="/circuits/update">
  <input type="hidden" name="id" value="{row['id']}">
  <input name="name" value="{escape(str(row['name']))}" aria-label="Circuit name">
  <input name="length" value="{fmt_raw(row['length'])}" aria-label="Length">
  <input name="device_distance" value="{fmt_raw(row['device_distance'])}" aria-label="Device distance">
  <label><span>Active</span><input type="checkbox" name="active" value="1" {checked}></label>
  <button type="submit">Save</button>
</form>""")
    return f"""
<section class="band">
  <h2>Add Circuit</h2>
  <form class="stack" method="post" action="/circuits/add">
    <label>Circuit name<input name="name" required></label>
    <label>Real length<input name="length" type="number" step="0.001" required></label>
    <label>Raw device distance<input name="device_distance" type="number" step="0.001"></label>
    <button type="submit">Add circuit</button>
  </form>
</section>
<section class="band">
  <h2>Circuits</h2>
  <div class="muted">Length is the calibrated circuit length. Raw device distance is the target distance expected from Kinomap/Strava before calibration.</div>
  <div style="display:grid; gap:8px; margin-top:12px;">{''.join(body)}</div>
</section>
"""


def render_review(conn: sqlite3.Connection) -> str:
    circuits = conn.execute("SELECT id, name FROM circuits WHERE active = 1 ORDER BY name").fetchall()
    rows = conn.execute(
        """
        SELECT r.*, c.name AS circuit_name
        FROM raw_activities r
        LEFT JOIN circuits c ON c.id = r.circuit_id
        ORDER BY r.imported_at DESC, r.id DESC
        """
    ).fetchall()
    return f"""
<section class="band">
  <h2>Add Raw Activity</h2>
  <form class="stack" method="post" action="/review/add">
    <label>Source<input name="source" value="manual" required></label>
    <label>Source ID<input name="source_activity_id"></label>
    <label>Title<input name="title" placeholder="Kinomap free-ride"></label>
    <label>Date<input name="started_on" type="date"></label>
    <label>Duration seconds<input name="duration_seconds" type="number"></label>
    <label>Raw distance<input name="raw_distance" type="number" step="0.001"></label>
    <button type="submit">Add to review</button>
  </form>
</section>
<section class="band">
  <h2>Review Queue</h2>
  {raw_activity_table(rows, circuits)}
</section>
"""


def raw_activity_table(rows: list[sqlite3.Row], circuits: list[sqlite3.Row]) -> str:
    if not rows:
        return '<div class="empty">No raw activities yet. Strava imports will appear here later; for now you can add one manually above.</div>'
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
  <td>{fmt_num(row['raw_distance'], 3)}</td>
  <td>{escape(str(row['session_type']))}<br><span class="muted">{escape(str(row['classification_reason'] or ''))}</span></td>
  <td>
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
      <label>Circuit<select name="circuit_id">{options}</select></label>
      <button type="submit">Confirm</button>
    </form>
  </td>
</tr>""")
    return f"""
<table>
  <thead><tr><th>Source</th><th>Title</th><th>Date</th><th>Raw distance</th><th>Current classification</th><th>Review</th></tr></thead>
  <tbody>{''.join(rendered)}</tbody>
</table>"""


def daily_table(rows: list[dict[str, object]]) -> str:
    return table(
        ["Date", "Sprints", "Laps", "Calories", "Time", "Avg watts", "Avg RPM", "Lap distance", "Total distance"],
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


def table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return '<div class="empty">No data yet.</div>'
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape('' if value is None else str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def metric(label: str, value: object, tone: str = "blue") -> str:
    return f'<div class="metric {tone}"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'


def line_chart(title: str, points: list[tuple[str, float | None]], color: str) -> str:
    clean = [(label, float(value)) for label, value in points if value is not None]
    if not clean:
        return f'<svg class="chart" role="img" aria-label="{escape(title)}"></svg>'
    width, height, pad = 680, 220, 28
    values = [value for _, value in clean]
    v_min, v_max = min(values), max(values)
    if v_min == v_max:
        v_min -= 1
        v_max += 1
    x_step = (width - pad * 2) / max(1, len(clean) - 1)
    coords = []
    for index, (_, value) in enumerate(clean):
        x = pad + index * x_step
        y = height - pad - ((value - v_min) / (v_max - v_min) * (height - pad * 2))
        coords.append((x, y))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>' for x, y in coords)
    return f"""
<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
  <text x="18" y="24" fill="#17202a" font-size="15" font-weight="700">{escape(title)}</text>
  <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#d9e2ec"/>
  <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#d9e2ec"/>
  <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="3"/>
  {circles}
</svg>"""


def update_circuit(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    conn.execute(
        """
        UPDATE circuits
        SET name = ?, length = ?, device_distance = ?, active = ?
        WHERE id = ?
        """,
        (
            params["name"].strip(),
            float(params["length"]),
            maybe_float(params.get("device_distance")),
            1 if params.get("active") == "1" else 0,
            int(params["id"]),
        ),
    )
    conn.commit()


def add_circuit(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    conn.execute(
        "INSERT INTO circuits (name, length, device_distance) VALUES (?, ?, ?)",
        (params["name"].strip(), float(params["length"]), maybe_float(params.get("device_distance"))),
    )
    conn.commit()


def add_raw_activity(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    raw_distance = maybe_float(params.get("raw_distance"))
    suggestion = suggest_activity_classification(conn, raw_distance)
    conn.execute(
        """
        INSERT OR IGNORE INTO raw_activities (
            source, source_activity_id, title, started_on, duration_seconds,
            raw_distance, session_type, circuit_id, classification_confidence,
            classification_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            params["source"].strip(),
            empty_to_none(params.get("source_activity_id")),
            empty_to_none(params.get("title")),
            empty_to_none(params.get("started_on")),
            maybe_int(params.get("duration_seconds")),
            raw_distance,
            suggestion["session_type"],
            suggestion.get("circuit_id"),
            suggestion["confidence"],
            suggestion["reason"],
        ),
    )
    conn.commit()


def classify_activity(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    session_type = params["session_type"]
    circuit_id = maybe_int(params.get("circuit_id")) if session_type == "lap" else None
    conn.execute(
        """
        UPDATE raw_activities
        SET session_type = ?,
            circuit_id = ?,
            review_status = 'reviewed',
            classification_confidence = 1,
            classification_reason = 'Manual review'
        WHERE id = ?
        """,
        (session_type, circuit_id, int(params["id"])),
    )
    conn.commit()


def add_sprint_entry(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    performed_on = required(params, "performed_on")
    conn.execute(
        """
        INSERT INTO sprint_entries (
            performed_on, day_number, sprint_index, duration_minutes,
            rpm, device_watts, hr, resistance, device_distance, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            performed_on,
            maybe_int(params.get("day_number")),
            maybe_int(params.get("sprint_index")),
            maybe_float(params.get("duration_minutes")),
            maybe_float(params.get("rpm")),
            maybe_float(params.get("device_watts")),
            maybe_int(params.get("hr")),
            maybe_int(params.get("resistance")),
            maybe_float(params.get("device_distance")),
            empty_to_none(params.get("notes")),
        ),
    )
    conn.commit()


def add_lap_entry(conn: sqlite3.Connection, params: dict[str, str]) -> None:
    performed_on = required(params, "performed_on")
    circuit_id = maybe_int(params.get("circuit_id"))
    if circuit_id is None:
        raise ValueError("A circuit is required for lap entries.")
    conn.execute(
        """
        INSERT INTO lap_entries (
            performed_on, lap_index, circuit_id, lap_time_minutes,
            hr, resistance, rpm, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            performed_on,
            maybe_int(params.get("lap_index")),
            circuit_id,
            maybe_float(params.get("lap_time_minutes")),
            maybe_int(params.get("hr")),
            maybe_int(params.get("resistance")),
            maybe_float(params.get("rpm")),
            empty_to_none(params.get("notes")),
        ),
    )
    conn.commit()


def circuit_select_options(circuits: list[sqlite3.Row], selected_id: int | None = None) -> str:
    options = ['<option value="">Select circuit</option>']
    for circuit in circuits:
        selected = " selected" if selected_id == circuit["id"] else ""
        options.append(f'<option value="{circuit["id"]}"{selected}>{escape(circuit["name"])}</option>')
    return "".join(options)


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


def signed_num(value: object, digits: int = 1) -> str:
    if value is None:
        return ""
    num = float(value)
    return f"{num:+,.{digits}f}"


def fmt_minutes(value: object) -> str:
    if value is None or value == "":
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


def required(params: dict[str, str], key: str) -> str:
    value = empty_to_none(params.get(key))
    if value is None:
        raise ValueError(f"{key} is required.")
    return value


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
