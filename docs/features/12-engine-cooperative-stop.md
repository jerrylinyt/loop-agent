# Feature 12: Cooperative Stop

## Type

Engine behavior improvement, but not a planning/execution strategy change.

## Goal

Allow dashboard and CLI to request a clean stop at safe boundaries instead of immediately killing the process.

## Problem

Force stopping can leave stale locks, incomplete status, and confusing logs. A cooperative stop request lets the engine finish the current safe unit and record a clean final state.

## Proposed Mechanism

Dashboard or CLI writes:

```text
<repo>/.loop/<ws>/.loop_state/stop_requested
```

Engine checks for this file:

- before starting a new planning cycle
- before starting a new execute round
- after agent subprocess returns
- before sleeping/polling

When seen:

- log a stop message
- write final event/status
- release run lock
- exit with a distinct code if appropriate

## Implementation Plan

1. Add helper `stop_requested(cfg)`.
2. Add checks at safe loop boundaries.
3. Add dashboard endpoint/action later: `Request Stop`.
4. Keep existing Force Stop as fallback.
5. Delete or archive `stop_requested` after honoring it.

## Acceptance Criteria

- Stop request does not kill an active child process mid-command unless the loop is at an existing timeout/kill boundary.
- Run lock is released cleanly.
- Logs and events show cooperative stop.
- Force Stop remains available for hung processes.

## Tests

- Unit test stop marker detection.
- Integration test marker before next round causes clean exit.
- Manual dashboard verification after endpoint/UI is added.

