# Open Vending — Agent Instructions

## Releasing a new version

When code changes are ready to ship to users:

1. Bump `version` in `package.json` (e.g. `1.0.0` → `1.0.1`).
2. Commit and push to `main`.

That's all. On next launch, the app fetches the remote `package.json`, compares versions, and shows **"Relaunch to Update"** if the remote version is higher.

Only bump the version when the change is worth delivering to users. Doc-only or tooling commits (README, HANDOFF, .gitignore) do not need a version bump.

## Update mechanism (reference)

- Version check: `GET https://raw.githubusercontent.com/liewcc/Open_Vending/main/package.json`
- Download: `https://github.com/liewcc/Open_Vending/archive/refs/heads/main.zip`
- Updater script is written to `%TEMP%\ov-update-<timestamp>\updater.ps1`, spawned detached, waits for Electron PID to exit, then extracts and copies all files except `node_modules/`, `python/`, `browsers/`, `node/`, `db/`, `.claude/`, `.git/`.
- App relaunches via `run.vbs`.

## Settings

Stored in `%APPDATA%\open-vending\settings.json`:
- `menuBar` (bool, default false) — show/hide Electron menu bar
- `showConsole` (bool, default false) — show/hide DOS console during Python download

## Credentials

Stored encrypted in `%APPDATA%\open-vending\credentials.enc` via Electron `safeStorage`.
Passed to Python as env vars `OV_USERNAME` / `OV_PASSWORD`. Never hardcoded.
