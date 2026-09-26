# Review and validation

## Root cause

Codex conversations retain provider IDs. Switching between configurations containing only `custom` or only `cc-switch-official` can leave older conversations referencing a missing provider. Earlier versions repaired only one direction and accepted only a local CC Switch source; retrying could not fix the other direction.

## Changes

- Mirror the selected, existing provider under the other historical name in both directions.
- Synchronize stale historical aliases, retaining the selected route and all unrelated configuration.
- Accept selected HTTP/HTTPS Responses routes, including proxy and direct connections.
- Reject missing selected providers instead of guessing from another table.
- Verify the complete parsed result equals the intended change before writing.
- Back up original bytes before atomic replacement; check for concurrent modifications.
- Monitor configuration content instead of desktop process starts; retain failed versions for retry.
- Compute hashes with .NET directly to avoid PowerShell module autoload failures.

## Validation

Seven test methods pass, with parameterized cases covering both IDs and local/direct routes. A separate isolated Windows monitor exercise passed official -> custom -> official transitions, stale alias synchronization, incomplete configuration retry, and recovery. Eighteen local profile replay cases also passed. These integration/replay checks were performed locally; the repository includes the portable unit tests but not private profile data or machine-specific integration fixtures.

## Remaining limits

The monitor reacts after a stable polling interval; it does not prevent every transient UI error. External writers can still race between the final comparison and replacement. Unsupported complex table layouts are rejected. The per-user mutex prevents duplicate monitors, not writes by CC Switch. Existing historical aliases intentionally follow the current route, rather than retaining their previous endpoint.

## Rollback

Stop the scheduled task and wait for its process to exit. Restore the prior scripts and, if necessary, an appropriate configuration backup after checking that it does not discard later user changes. Restart the task. Do not blindly restore old configuration or application databases while their applications are writing them.