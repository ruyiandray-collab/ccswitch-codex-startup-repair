# Codex CC Switch Provider Compatibility

Windows background monitor that preserves compatibility with Codex conversations created under `custom` or `cc-switch-official` when CC Switch changes routes.

The selected provider is the source of truth. The checker mirrors its complete settings under the other historical name, supporting local proxy and HTTP/HTTPS Responses routes. It never guesses a missing selected provider from a stale alias. It preserves unrelated settings, verifies the TOML semantic change, backs up original bytes, and refuses unsupported table structures.

## Usage

Requires Windows and Python 3.11+. The monitor defaults to the Python runtime bundled with Codex at `%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`. Adjust `$python` if necessary.

```powershell
# Check directly, even while the monitor is running:
python .\repair_config.py "$env:USERPROFILE\.codex\config.toml"

# Run the background monitor (until stopped):
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ccswitch-codex-startup-monitor.ps1
```

To start at logon, configure Windows Task Scheduler to run `powershell.exe` with `-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "<install directory>\ccswitch-codex-startup-monitor.ps1"`. Use the current user's interactive session and IgnoreNew for multiple instances. Stop the task and wait for its process to exit before restarting after updates.

The monitor polls SHA-256 via .NET every two seconds. After three stable samples it runs the checker. Recoverable failures retry after 5, 10, 20, then 30 seconds. A new file version resets the delay. Worker execution is limited to 30 seconds; logs rotate at 1 MiB.

## Status

- `alias_present`: both historical names match the selected provider.
- `repaired`: missing historical name added.
- `alias_synchronized`: existing historical name synchronized to the selected route.
- `blocked_provider`: selected provider missing or outside the supported pair.
- `blocked_route` / `blocked_table_shape`: unsupported route or TOML representation.
- Other `blocked_*` statuses indicate file contention or worker failure.

## Tests

```powershell
python -m unittest -v test_repair_config.py
```

Tests cover both mapping directions, local/direct routes, stale aliases, missing selected providers, unrelated providers, nested tables, quoted headers, BOM, exact backups, and idempotency. No credentials or live configurations are needed.

## Limits

This is a compatibility workaround, not a CC Switch patch. Polling cannot prevent a brief missing-provider window immediately after a switch. Preserving historical provider names in CC Switch's generated configurations avoids that window. The repository does not modify CC Switch's database automatically: such changes must account for the user's proxy mode and existing profiles.

Synchronizing the unselected historical name intentionally routes old conversations through the currently selected provider. Review your selected route before using old conversations. Backups may contain sensitive configuration; they remain local and are excluded from Git.

Unsupported nested provider tables fail closed. There remains a narrow compare/replace race with external writers that do not share the same lock. Upstream errors such as HTTP 503 are outside this tool's scope.