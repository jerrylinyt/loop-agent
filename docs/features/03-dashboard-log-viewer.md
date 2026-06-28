# Feature 03: Dashboard Log Viewer Upgrade

## Type

Dashboard-only.

## Goal

Make live logs easier to inspect during long-running loops.

## Problem

The current log viewer streams `loop.log` and `plan.log`, supports filtering, and can download logs. It needs better controls for long sessions and human review.

## User Experience

Add:

- pause/resume live stream
- auto-scroll toggle
- quick filters: error, PASS, FAIL, human_required, review gate, model upgrade
- clear visible buffer without deleting files
- copy visible lines
- line count indicator
- clearer active log label

## Implementation Plan

1. Extend the log tab controls in `dashboard/templates/index.html`.
2. Add front-end state for:
   - paused
   - auto-scroll enabled
   - selected quick filters
   - retained lines count
3. Keep SSE endpoint unchanged.
4. Buffer incoming lines while paused, then append on resume.
5. Preserve existing download behavior.

## Acceptance Criteria

- Users can pause logs without closing the page.
- Auto-scroll can be disabled.
- Quick filters combine predictably with text search.
- Long sessions do not grow the DOM beyond the existing retained-line cap.
- No backend or engine changes are required.

## Tests

- Manual browser verification with mock or real log stream.
- Verify switching between `loop.log` and `plan.log` resets the controls cleanly.

