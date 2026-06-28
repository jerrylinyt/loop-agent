# Feature 10: Engine-Owned Preflight JSON

## Type

Engine additive CLI/API support. Avoid changing preflight rules unless required for consistency.

## Goal

Expose engine preflight as machine-readable JSON so CLI, dashboard, and engine agree on readiness.

## Problem

The dashboard has its own preflight logic while engine has `report_preflight`. These can drift. Users may see dashboard "ready" but engine start fails, or vice versa.

## Proposed CLI

```bash
python engine/run.py --preflight --stage execute --json
```

Example output:

```json
{
  "ok": false,
  "workspace": "default",
  "stage": "execute",
  "checks": [
    {"id":"repo","label":"Repo path exists","ok":true,"detail":"C:/repo"},
    {"id":"requirements","label":"Requirements confirmed","ok":false,"detail":"missing confirmation marker"}
  ]
}
```

## Implementation Plan

1. Refactor existing preflight logic into a function that returns structured check objects.
2. Keep existing human-readable `report_preflight` output by rendering the structured result.
3. Add `--preflight` and `--json` options to `engine/run.py`.
4. Update dashboard preflight endpoint to call or share the same structured logic if feasible.
5. Preserve existing exit codes:
   - `0` if ok
   - non-zero if failed

## Acceptance Criteria

- CLI can print JSON preflight without starting the loop.
- JSON contains stable check IDs.
- Existing engine preflight behavior remains unchanged for normal runs.
- Dashboard can migrate to this output in a later step.

## Tests

- Unit tests for structured preflight result.
- CLI test for valid and invalid config.
- Dashboard compatibility test if endpoint changes.

