# WSL Sandbox

This project can run from an isolated WSL clone so local tests, the dev server, and the SQLite runtime database do not compete with the OneDrive-backed Windows workspace.

## Current Sandbox

- WSL distro: `CycleTracking`
- Linux user: `calum`
- Repo path: `/home/calum/src/Cycle-tracking`
- Python: system `python3` with a project virtual environment at `.venv`
- App database: `/home/calum/src/Cycle-tracking/data/workout_tracker.sqlite`
- Dashboard URL: `http://127.0.0.1:8006`

## Run Checks

From Windows PowerShell:

```powershell
wsl -d CycleTracking -- bash -lc 'cd ~/src/Cycle-tracking && . .venv/bin/activate && python -m unittest discover -s tests -v'
wsl -d CycleTracking -- bash -lc 'cd ~/src/Cycle-tracking && . .venv/bin/activate && python -m compileall workout_tracker tests run.py'
```

## Start The Dashboard

Use absolute Linux paths so the app always uses the sandbox database, regardless of the Windows working directory:

```powershell
Start-Process -WindowStyle Hidden -FilePath wsl.exe -ArgumentList @('-d','CycleTracking','--','/home/calum/src/Cycle-tracking/.venv/bin/python','/home/calum/src/Cycle-tracking/run.py','--db','/home/calum/src/Cycle-tracking/data/workout_tracker.sqlite','serve','--port','8006')
```

Then open `http://127.0.0.1:8006`.

## Stop The Dashboard

```powershell
wsl -d CycleTracking -- pkill -f '/home/calum/src/Cycle-tracking/run.py'
```

## Refresh The Sandbox Clone

When the main branch has moved forward:

```powershell
wsl -d CycleTracking -- bash -lc 'cd ~/src/Cycle-tracking && git fetch origin && git switch codex/workout-tracker-app && git pull --ff-only'
```

To refresh the sandbox database from the Windows workspace:

```powershell
wsl -d CycleTracking -- cp '/mnt/c/Users/calum.cameron/OneDrive - CGI/Documents/New project/data/workout_tracker.sqlite' /home/calum/src/Cycle-tracking/data/workout_tracker.sqlite
```

Treat the WSL clone as the runtime/test sandbox unless intentionally using it as the active development checkout.
