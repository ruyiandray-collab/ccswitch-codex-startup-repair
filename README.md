# Codex CC Switch Startup Repair

A small Windows logon monitor that checks the Codex desktop process and, after a 15-second settling delay, runs a local compatibility check for `~/.codex/config.toml`.

The checker uses Python 3.11 or newer (`tomllib`), works offline, and never reads Codex conversation/session files. It only adds `[model_providers.custom]` when the selected provider is a recognized local CC Switch route at `http://127.0.0.1:15721/v1` using the Responses API. It backs up the exact original bytes first and fails closed on unsupported TOML structures or routes. Existing aliases are left alone.

## Files

- `ccswitch-codex-startup-monitor.ps1` — Windows process monitor and bounded worker launcher.
- `repair_config.py` — TOML validation and guarded backup/repair.
- `test_repair_config.py` — unit tests for safety checks, backup, and idempotency.
- `REVIEW.md` — review findings, limitations, and rollback notes.

## Run a one-time check

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ccswitch-codex-startup-monitor.ps1 -Once
```

The monitor expects the bundled Codex Python runtime at `%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`. Adjust `$python` in the script if using a different Python installation.

To install a logon task, create a Windows Task Scheduler task that runs `powershell.exe` with `-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "<install directory>\ccswitch-codex-startup-monitor.ps1"`, triggered at user logon. Set multiple-instance behavior to IgnoreNew.

Run the tests with Python 3.11 or newer:

```powershell
python -m unittest -v test_repair_config.py
```

The monitor identifies the current Codex WindowsApps package layout. A future package layout change may require updating that process match. The file comparison and atomic replacement have a narrow race window with software that does not use the monitor's lock; see `REVIEW.md`.
