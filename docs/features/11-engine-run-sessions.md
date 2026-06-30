# Feature 11: Structured Run Sessions

## Type

Engine additive observability and control traceability.

## Goal

Record each Start/run invocation as a distinct session with metadata and final outcome so later state changes can be attributed to a specific run.

## Problem

`run_id` already exists during loop execution and typed records already land in `.loop_state/rounds.jsonl`, but the session contract is still implicit. Dashboard and future state guards need a clean way to answer:

- when did this run start and end
- which mode and stage owned it
- what final status did it produce
- which run last set `human_required`

## Proposed Record Shape

Do not add a parallel `events.jsonl`. Keep `.loop_state/rounds.jsonl` as the canonical append-only log and add typed lifecycle records.

Example records:

```json
{
  "type": "run_started",
  "run_id": "default:20260628-230100",
  "workspace": "default",
  "mode": "auto",
  "stage": "all",
  "started_at": "2026-06-28 23:01:00"
}
```

```json
{
  "type": "run_finished",
  "run_id": "default:20260628-230100",
  "workspace": "default",
  "ended_at": "2026-06-28 23:35:00",
  "exit_code": 0,
  "final_status": "complete",
  "total_rounds": 8,
  "human_required_code": null
}
```

## Implementation Plan

1. Standardize `run_started` and `run_finished` typed records for both `plan_loop.py` and `loop.py`.
2. Ensure every terminal path writes `run_finished` best-effort, including success, preflight failure, hard stop, and exception paths.
3. Include fields needed by later control guards: `run_id`, `workspace`, `mode`, `stage`, `started_at`, `ended_at`, `exit_code`, `final_status`, and `human_required_code`.
4. Add a helper that reconstructs recent sessions from `rounds.jsonl` instead of creating a second source of truth.
5. Keep writes best-effort so observability failures do not break loop execution.

## Acceptance Criteria

- Every run writes one `run_started` record and one `run_finished` record where process shutdown allows it.
- Terminal records cover normal completion and common stop paths.
- Missing lifecycle record writes must not break loop execution.
- Dashboard can list recent runs by reconstructing sessions from `rounds.jsonl`.
- The latest `run_id` responsible for a stop can be identified reliably.

## Tests

- Unit test lifecycle record helper functions.
- Integration test for a minimal run.
- Verify interrupted or failed runs still leave useful session data where possible.
