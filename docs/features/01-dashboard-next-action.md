# Feature 01: Dashboard Next Action Panel

## Type

Dashboard-only. Do not modify `engine/` or loop flow.

## Goal

Add a clear "Next Action" panel to the workspace overview so users know what to do next without interpreting raw state fields, logs, or config files.

## Problem

The dashboard already exposes project state, preflight checks, logs, config, diff, and tree views. Users still need to infer the next correct action from scattered data. This is especially confusing for first-time users and for states like stale locks, missing requirements confirmation, placeholder config, or `human_required`.

## User Experience

The selected workspace overview should show one primary recommendation and optional secondary actions.

Examples:

- Requirements are not confirmed: "Confirm requirements before planning." Primary action: `View REQUIREMENTS.md`.
- Config has placeholders: "Agent config is incomplete." Primary action: `Open Config Wizard`.
- Stale lock exists: "Previous run left a stale lock." Primary action: `Clear Lock`.
- Human intervention is needed: "Loop stopped for human review." Primary action: `Review Action Needed`.
- Ready to run: "Workspace is ready." Primary action: `Start`.
- Running: "Run is active." Primary action: `Open Live Logs`.

## Implementation Plan

1. Add a `Next Action` card near the top of the selected workspace overview.
2. Reuse existing dashboard endpoints:
   - `GET /api/projects`
   - `GET /api/projects/{id}/preflight`
   - `GET /api/projects/{id}/human-context`
3. Implement a small front-end decision function:
   - stale lock beats all start actions
   - `human_required` beats config/start actions
   - running state points to logs
   - failed preflight maps to the first actionable failed check
   - all checks passing points to start
4. Add action buttons that call existing UI functions where possible.
5. Refresh the panel on project select and during the existing polling interval.

## Acceptance Criteria

- The panel appears for every selected workspace.
- The recommendation changes when project state changes.
- The primary action button performs the expected existing action.
- No `engine/` files are changed.
- The UI remains usable on desktop and narrow screens.

## Tests

- Unit-test the decision function with representative project/preflight states if JS tests exist.
- Otherwise add a manual checklist to `dashboard/README.md`.
- Verify manually with mock projects for: ready, running, stale lock, config incomplete, requirements missing, and human required.

