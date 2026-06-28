# Feature 11: Engine Run Sessions

## Type

Engine additive observability.

## Goal

Record each Start/run invocation as a distinct session with metadata and final outcome.

## Problem

`run.lock` and `rounds.jsonl` show activity, but they do not provide a clean historical boundary for "this run". Dashboard users need run history and final summaries.

## Proposed Artifacts

```text
<repo>/.loop/<ws>/.loop_state/runs/<run_id>/manifest.json
<repo>/.loop/<ws>/.loop_state/runs/<run_id>/events.jsonl
```

Manifest example:

```json
{
  "run_id": "default:20260628-230100",
  "workspace": "default",
  "mode": "auto",
  "stage": "all",
  "started_at": "2026-06-28 23:01:00",
  "ended_at": "2026-06-28 23:35:00",
  "exit_code": 0,
  "final_status": "complete",
  "total_rounds": 8,
  "human_required_code": null
}
```

## Implementation Plan

1. Generate a `run_id` at engine entry.
2. Store `run_id` in memory and pass to plan/execute helpers where practical.
3. Create a manifest at run start.
4. Update manifest at run finish, max rounds, human required, or exception path.
5. Optionally copy or link events into the run folder.
6. Keep existing `rounds.jsonl` for compatibility.

## Acceptance Criteria

- Every run creates a manifest.
- Manifest is updated on normal completion and common stop paths.
- Missing manifest update must not break loop execution.
- Dashboard can list recent runs later.

## Tests

- Unit test manifest create/update helpers.
- Integration test for a minimal run.
- Verify interrupted/failed run still leaves a useful manifest where possible.

