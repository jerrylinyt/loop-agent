# Feature 08: Engine Structured Event Log

## Type


> Current direction: do not create a separate event/artifact JSONL file. Emit typed records into `.loop_state/rounds.jsonl` and use `type` to distinguish lifecycle events, completed rounds, and artifact-bearing records.

Engine additive observability. Avoid changing loop strategy or flow.

## Goal

Have the engine emit machine-readable events so dashboard and analysis tools do not need to parse human log text.

## Problem

Dashboard activity detection currently relies on log text patterns. This is fragile because log wording, language, symbols, or encoding can change.

## Proposed Artifact

Write JSON lines to:

```text
<repo>/.loop/<ws>/.loop_state/events.jsonl
```

Example:

```json
{"ts":"2026-06-28 23:01:00","type":"run_started","run_id":"default:20260628-230100","mode":"auto","stage":"all"}
{"ts":"2026-06-28 23:02:00","type":"round_started","run_id":"default:20260628-230100","round":1,"phase":"1","model_tier":"fast"}
{"ts":"2026-06-28 23:03:00","type":"round_finished","run_id":"default:20260628-230100","round":1,"result":"FAIL","progressed":false}
{"ts":"2026-06-28 23:04:00","type":"human_required","run_id":"default:20260628-230100","code":"git_review_failed","reason":"Review gate requested human intervention."}
```

## Event Types

Minimum event set:

- `run_started`
- `run_finished`
- `preflight_failed`
- `round_started`
- `round_finished`
- `model_tier_changed`
- `git_review_started`
- `git_review_finished`
- `human_required`
- `loop_complete`
- `max_rounds_reached`
- `stop_requested`
- `stop_completed`

## Implementation Plan

1. Add a small append-only event helper in engine state utilities.
2. Best-effort write only: event write failures must not stop the loop.
3. Emit events at existing lifecycle points in `run.py`, `plan_loop.py`, and `loop.py`.
4. Keep existing logs unchanged.
5. Add a dashboard endpoint later if needed.

## Acceptance Criteria

- `events.jsonl` is created during runs.
- Each line is valid JSON.
- Event writes do not affect loop exit behavior.
- Existing tests continue passing.
- Dashboard can eventually consume events instead of log regexes.

## Tests

- Unit test event append helper.
- Integration test one minimal run writes `run_started` and `run_finished`.
- Verify malformed event data cannot crash the loop.

