# Feature 05: Human Required Inbox

## Type

Dashboard-only.

## Goal

Provide a global queue of workspaces needing human attention.

## Problem

The selected workspace can show a human-required banner, but users managing multiple workspaces need a global view of all blocked work.

## User Experience

Add an inbox view or panel listing all projects where:

- status is `human_required`
- `CONTROL.md` has `human_required: true`
- stale or blocked state suggests manual review

Each item should show:

- repo/workspace
- phase
- stuck level
- reason line
- log excerpt
- actions: Open Workspace, Open Logs, View Changes, Resume

## Implementation Plan

1. Reuse `GET /api/projects`.
2. For projects with `human_required`, fetch `GET /api/projects/{id}/human-context`.
3. Render an inbox panel in the dashboard header or sidebar.
4. Add count badge to the global summary.
5. Ensure actions select the workspace before opening the relevant tab.

## Acceptance Criteria

- All human-required workspaces are visible without selecting each project.
- Inbox count updates during polling.
- Resume action uses the existing resume endpoint.
- Empty state is clear.
- No engine changes.

## Tests

- Add dashboard tests only if backend behavior changes.
- Manual verification with multiple mocked projects in `~/.loop/index.md`.

