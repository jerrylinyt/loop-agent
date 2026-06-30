# Feature 10: Engine-Owned Structured Preflight

## Type

Engine additive CLI/API support. Avoid changing preflight rules unless required for consistency.

## Goal

Make engine preflight the single source of truth for startup readiness so CLI, dashboard, and future automation all evaluate the same checks.

## Problem

Preflight logic currently exists in more than one place. That creates a control hazard: dashboard can report "ready" while engine still refuses to start, or engine can accept a state the UI would have warned about. The issue is not only presentation. It is split authority.

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
  "generated_at": "2026-06-30 09:12:00",
  "checks": [
    {"id":"framework_path","label":"Framework path exists","ok":true,"severity":"error","detail":"C:/loop-agent"},
    {"id":"requirements_confirmed","label":"Requirements confirmed","ok":false,"severity":"warning","detail":"REQUIREMENTS CONFIRMED marker missing"},
    {"id":"run_lock","label":"Run lock is clear or stale","ok":true,"severity":"error","detail":"no active lock"}
  ]
}
```

## Design Constraints

- One structured function should produce preflight results for both human-readable and JSON output.
- Stable `check.id` values are part of the contract.
- JSON output must be additive and safe for dashboard adoption in phases.
- Dashboard should stop maintaining a divergent copy of engine rules once the shared path is available.

## Implementation Plan

1. Refactor existing preflight logic into a function that returns structured check objects with `id`, `label`, `ok`, `severity`, and `detail`.
2. Keep the existing `report_preflight` behavior by rendering the structured result to text.
3. Add `--preflight` and `--json` options to `engine/run.py`.
4. Add a non-JSON human mode for `--preflight` so users can inspect readiness without starting the loop.
5. Update dashboard preflight endpoint to call or share the engine-owned structured result instead of rebuilding the checks separately.
6. Preserve current exit behavior:
   - `0` if `ok=true`
   - non-zero if `ok=false`

## Suggested Check IDs

- `framework_path`
- `framework_boot_sequence`
- `agent_model_fast`
- `agent_model_normal`
- `agent_model_thinking`
- `agent_prompts`
- `build_cmd`
- `git_repo`
- `git_identity`
- `requirements_present`
- `requirements_confirmed`
- `control_file`
- `phases_present`
- `run_lock`

## Acceptance Criteria

- CLI can print structured JSON preflight without starting plan or execute loops.
- JSON contains stable check IDs and explicit severity.
- Existing engine preflight behavior remains unchanged for normal runs.
- Dashboard can consume the same structured result and stop owning a divergent ruleset.
- Start gating decisions no longer depend on duplicated preflight logic.

## Tests

- Unit tests for the structured preflight result.
- CLI tests for valid and invalid config with and without `--json`.
- Dashboard compatibility test if the endpoint changes to consume engine output.
