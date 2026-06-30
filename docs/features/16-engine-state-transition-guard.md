# Feature 16: Engine State Transition Guard

## Type

Engine additive correctness guard. This feature is allowed to harden state writes, but should avoid changing planning or execution strategy.

## Goal

Make `state.json` writes safe, attributable, and transition-aware so old runs, stale dashboard actions, or partial writers cannot silently move the loop into an invalid state.

## Problem

Feature 15 centralized state into `state.json`, which removed a large class of drift bugs. The remaining control risk is not storage format. It is write correctness:

- an older run can overwrite newer state
- dashboard resume can clear a stop created by a different run
- engine code can write a legal key with an illegal transition
- partial writers can mutate related fields without preserving invariants

Without a guard layer, the system still relies on "call the helper correctly everywhere".

## Proposed Concepts

### 1. State revision

Add a monotonically increasing revision counter at the root of `state.json`:

```json
{
  "schema_version": 2,
  "state_revision": 41
}
```

Every successful write increments `state_revision`.

### 2. Last writer metadata

Track the writer that performed the latest state mutation:

```json
{
  "last_writer": {
    "run_id": "repo:default:1719587400",
    "source": "execute_loop",
    "ts": "2026-06-30 09:30:00"
  }
}
```

### 3. Guarded transitions

Define allowed transitions for control fields, for example:

- `human_required: false -> true` allowed from engine stop paths
- `human_required: true -> false` allowed only from explicit resume / clear actions
- `plan_human_required` and `human_required` must not clear each other implicitly
- `current_phase` must not move backward unless a documented reset path is in effect

### 4. Compare-and-swap style writes

Helper APIs should support "write only if current revision matches expected revision" for sensitive actions such as:

- dashboard resume
- dashboard clear-human-required
- run-finalization writes
- stop-condition writes after long-running rounds

If the revision changed underneath the caller, return a structured conflict instead of overwriting state.

## Implementation Plan

1. Add state metadata fields: `schema_version`, `state_revision`, and `last_writer`.
2. Introduce a guarded write helper in `engine/state.py` that loads state, validates a transition, increments revision, stamps writer metadata, and saves atomically.
3. Define a minimal transition policy for the highest-risk fields first:
   - `human_required`
   - `plan_human_required`
   - `current_phase`
   - `last_round_result`
4. Update dashboard mutating endpoints to use guarded writes and surface conflict errors cleanly.
5. Update execute and plan stop helpers to pass `run_id` and source information into guarded writes.
6. Keep legacy `get_val` / `set_val` reads available during migration, but route control-critical writes through the guard.

## Non-Goals

- Do not replace every state write in one pass if the migration risk is too high.
- Do not redesign loop policy, oscillation thresholds, or planner strategy.
- Do not require a separate database or daemon.

## Acceptance Criteria

- Sensitive state changes are revisioned and stamped with writer metadata.
- Dashboard cannot silently clear a stop created by a newer run.
- Invalid or stale writes return structured conflicts instead of overwriting newer state.
- Transition guard enforcement is introduced for at least the highest-risk control fields.
- Existing atomic save behavior remains intact.

## Tests

- Unit tests for guarded transition validation.
- Unit tests for compare-and-swap conflict behavior.
- Integration test where two simulated writers race and the stale writer is rejected.
- Dashboard endpoint test for stale resume or stale clear-human-required conflict handling.
