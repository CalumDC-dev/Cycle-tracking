# Workout Tracker App

Local-first Python app for importing workout data from the workbook, storing it in SQLite, applying the calibration rules, and reviewing sessions before future Strava automation is added.

## Quick Start

```powershell
python -m workout_tracker.cli import-workbook "Workout tracking.xlsx" --reset
python -m workout_tracker.cli export
python -m workout_tracker.cli serve --port 8000
```

Then open `http://127.0.0.1:8000`.

## Design Notes

- Raw source activities are stored separately from calibrated sprint/lap records.
- The workbook importer migrates current history, lookup tables, mass log, circuits, and constants.
- Sprint and lap entries can be added manually from the local web UI.
- Strava/Kinomap import can later write into `raw_activities`; the review screen classifies each activity as `lap`, `sprint`, `endurance`, `ignore`, or `unknown`.
- Calculated metrics are generated from the database, not stored as spreadsheet formulas.
- `Workout tracking.xlsx` is intentionally ignored by Git because it contains personal source data.
