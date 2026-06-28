# Feature 04: Dashboard Diff Review Upgrade

## Type

Dashboard-only, with optional dashboard backend additions. Do not modify engine.

## Goal

Make the Changes tab useful for human review by showing file-level structure and review hints.

## Problem

The dashboard can fetch a raw diff, but raw patches are hard to scan. Human review needs changed file grouping, collapsible sections, and risk cues.

## User Experience

Add:

- changed files list
- per-file collapsible diff
- search/filter by file path
- added/deleted line counts
- large diff truncation warning
- highlight likely high-risk paths:
  - config files
  - tests
  - generated state
  - framework files
  - lock/state files

## Implementation Plan

1. Parse unified diff in front-end JavaScript or add a dashboard-only endpoint that returns structured diff.
2. Render file list and grouped hunks.
3. Preserve raw diff view as fallback.
4. Show base/head SHA values already returned by `/api/projects/{id}/diff`.
5. Add empty states for no diff or invalid git repository.

## Acceptance Criteria

- A raw diff is grouped by file.
- Users can collapse and expand files.
- Large diffs still render without freezing the browser.
- The raw diff can still be copied or inspected.
- No engine changes.

## Tests

- Add tests for any new backend diff parser.
- Manual checks for empty diff, single-file diff, multi-file diff, binary file diff, and truncated diff.

