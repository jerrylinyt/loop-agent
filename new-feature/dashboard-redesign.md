# Dashboard Redesign Plan

## Type

Dashboard rewrite. No backward compatibility requirement.

## Goal

Rewrite the dashboard into a user-friendly progress cockpit that answers:

- What is the loop doing now?
- Is it moving forward, stuck, or regressing?
- Why did the state change?
- What does the user need to do next?

The dashboard should stop being a log/diff viewer first. Logs and diffs remain available as diagnostics, but the primary UI should explain progress, risk, and next action from `state.json` and `.loop_state/rounds.jsonl`.

## Product Direction

Use a React/Vite frontend built into static assets and served by the existing FastAPI backend. Users still start the dashboard with one command:

```bash
python -m dashboard.main
```

Development can use Vite, but production/local usage must not require running a separate npm server. To ensure an out-of-the-box local developer experience without Node/npm requirements, the compiled frontend bundle under `dashboard/frontend/dist` must be tracked and committed to Git.

```text
dashboard/
  app.py
  main.py
  frontend/
    package.json
    src/
    dist/             # Tracked and committed compiled assets
```

FastAPI remains responsible for local filesystem access, process control, log streaming, and engine integration. React owns all UI state, charts, and interaction.

## Current Dashboard Review

### Keep As Core Capabilities

- Project/workspace list from `~/.loop/index.md`, enriched with live `state.json` values.
- Start, stop, resume, and clear stale lock actions.
- Human-required inbox and reason display.
- Preflight checks before start.
- `state.json` summary parsing.
- `rounds.jsonl` history parsing.
- Tree/phase status when a workspace uses tree mode.
- Log access for diagnostics.

### Rebuild Into Better Forms

- Overview tab becomes the main product surface, not just counters.
- Round sparkline becomes a real progress chart with PASS/FAIL/regression/stuck annotations.
- Activity timeline becomes an explanation feed generated from typed records, not raw log fragments.
- Human-required panel becomes a next-action card with reason, evidence, suggested action, and resume button.
- Tree view becomes a progress map: node state, blocked leaves, converged leaves, reflow count, and current active leaf.
- Config wizard becomes a setup/settings panel, not a central workflow.
- Logs become a collapsible diagnostics drawer linked from events and failures.

### Remove Or De-prioritize

- Diff viewer is not primary. Keep a compact "changed files / last commit / open diff" diagnostic entry if data exists.
- Full inline diff rendering can be removed from the main UI. If retained, put it behind a diagnostics route.
- Raw `loop.config.yaml` editing should not be prominent. Prefer structured settings and an advanced editor.
- Project grid/list visual toggle is low value unless the new layout needs it.
- TREE.md fallback compatibility can be removed if `state.json.tree` is now canonical.
- Legacy `templates/index.html` and `static/app.js` can be deleted after the React replacement lands.

## UX Model

### Global Home

Shows all tracked workspaces grouped by attention need:

- Needs human action
- Running
- Stalled or regressing
- Recently progressed
- Complete
- Idle / not started

Each workspace card should show:

- repo and workspace
- current phase or active tree leaf
- status label
- progress direction: forward, neutral, backward, unknown
- last meaningful event
- running duration or last updated time
- primary action: open, start, resume, review issue

### Workspace Overview

The workspace page should start with a single answer card:

```text
Current state: Running, Phase 2
Direction: Forward
Why: round 14 passed validation and phase 2 consecutive_pass increased from 1 to 2
Next: waiting for one more pass to converge this phase
```

Below that:

- Progress chart: rounds over time, with pass/fail, stuck level, model tier, and progress markers.
- Phase/tree progress: phase cards or tree map.
- Cause timeline: typed events explaining progress, regression, escalation, revert, human_required, completion.
- Next action card: only visible when user action is useful.
- Diagnostics drawer: logs, diff, config, raw state.

### Progress Direction Semantics

The UI should clearly decouple **Run Status** and **Progress Trend (Direction)** to ensure orthogonal semantics:

- **Run Status (`status`)**:
  - `running`: Currently running the loop engine.
  - `idle`: Process stopped normally.
  - `completed`: Loop completed successfully.
  - `human_required`: Paused, requiring human intervention.
  - `preflight_blocked`: Blocked at preflight checks.

- **Progress Trend (`direction`)**:
  - `forward`: A recent round progressed, a phase pass counter increased, a tree leaf converged, blocking issues decreased, or loop completed.
  - `backward`: Review gate reverted changes, phase pass counter reset, blocking issues increased, stuck level increased after a failed round, or a tree node moved back to `NEEDS_REVISION`.
  - `stalled`: No progress for configured threshold, repeated same fail fingerprint, or `rounds_since_progress` rising.
  - `neutral`: Idle or running stably without immediate positive/negative trend changes.
  - `unknown`: Insufficient history.

This should be returned by the backend as a view model. The frontend should not reconstruct core semantics from many raw fields.

## Backend Plan

Keep FastAPI, but replace ad hoc UI-specific endpoints with explicit dashboard view models.

### Endpoint Parameters & Safety

The `{id}` parameter must be a URL-safe unique hash (e.g., MD5 hash of the repository path and workspace name) rather than readable file paths. This ensures we avoid path-traversal or router path-resolution issues under Windows (where `:` and `\` are reserved).

### New Endpoints

#### Core & Execution
- `GET /api/workspaces`                         # List workspaces (ID, paths, and statuses)
- `GET /api/workspaces/{id}/overview`           # Get structured workspace state
- `POST /api/workspaces/{id}/start`             # Start the engine
- `POST /api/workspaces/{id}/stop`              # Force stop the engine
- `POST /api/workspaces/{id}/resume`            # Resume after human confirmation

#### Configuration, Planning & Checks
- `GET /api/workspaces/{id}/preflight`          # Preflight run checks (git, config, requirements)
- `GET /api/workspaces/{id}/config`             # Read loop.config.yaml content
- `POST /api/workspaces/{id}/config`            # Write loop.config.yaml with YAML validation
- `POST /api/workspaces/{id}/config-wizard`     # Quick wizard configuration
- `GET /api/workspaces/{id}/tree`               # Get parsed tree nodes (Tree mode only)
- `POST /api/workspaces/{id}/reject`            # Reject a specific subtree and trigger replan

#### Progress & Activity Logs (Performance Optimized)
- `GET /api/workspaces/{id}/timeline?limit=100` # Feed-ready events (parsed backwards with limit for O(1) tail performance)
- `GET /api/workspaces/{id}/progress?limit=200` # Normalized historical round records for charts
- `GET /api/workspaces/{id}/logs/{log_type}`    # SSE stream (Live server-sent events for loop/plan logs)
- `GET /api/workspaces/{id}/logs/{log_type}/download` # Download log file
- `GET /api/workspaces/{id}/diagnostics`        # Static metadata diagnostics (raw state.json, git diff details)

The existing `/api/projects/*` naming can be replaced. No compatibility is required.

### Overview View Model

```json
{
  "id": "403df2ca972109e3e7f4c08e50a96091",
  "repo": "C:/path/repo",
  "workspace": "default",
  "mode": "flat",                            // "flat" or "tree"
  "status": "running",                       // "running" | "idle" | "completed" | "human_required" | "preflight_blocked"
  "direction": "forward",                    // "forward" | "neutral" | "backward" | "stalled" | "unknown"
  "headline": "Phase 2 is progressing",
  "why": "Round 14 passed and consecutive_pass increased to 2/3.",
  "next_action": {
    "kind": "wait",
    "label": "No action needed",
    "detail": "One more passing validation is needed for convergence."
  },
  "current": {
    "phase": "2",
    "active_leaf": null,
    "stuck_level": 0,
    "rounds_since_progress": 0,
    "model_tier": "default"
  },
  "run": {
    "is_running": true,
    "pid": 1234,
    "started_at": "2026-06-30T13:00:00+08:00",
    "heartbeat_age": 5
  }
}
```

### Progress View Model

Normalize `round_finished` records into chart-ready points:

```json
{
  "round": 14,
  "ts": "2026-06-30T13:12:00+08:00",
  "phase": "2",
  "result": "PASS",
  "progressed": true,
  "direction": "forward",
  "stuck_level": 0,
  "rounds_since_progress": 0,
  "model_tier": "default",
  "fail_fingerprint": null,
  "summary": "Validation passed; phase progress advanced."
}
```

### Timeline View Model

Generate typed timeline events from `rounds.jsonl` and `state.json`:

- `run_started`
- `round_passed`
- `round_failed`
- `progress_made`
- `regression_detected`
- `review_reverted`
- `model_escalated`
- `human_required`
- `loop_completed`
- `preflight_blocked`

Each event must include `severity`, `title`, `detail`, `ts`, and optional links to diagnostics.

### Diagnostics

Diagnostics are secondary:

- latest log tail
- downloadable logs
- raw `state.json`
- changed files if available
- optional diff route, hidden behind an advanced action
- config summary and advanced raw editor

## Frontend Plan

### Stack

- Vite
- React
- TypeScript
- React Router or a lightweight route state
- Chart library: Recharts or ECharts
- CSS modules, vanilla CSS, or Tailwind source build

Avoid CDN Tailwind in the new dashboard. Build assets should be local, bundled under `frontend/dist`, and served by FastAPI.
To ensure the CLI is self-contained and run-ready for non-Node users, the built assets in `dashboard/frontend/dist` must be tracked and committed to Git.

### Main Screens

- Home: attention-first workspace list.
- Workspace Overview: status, direction, progress chart, timeline, next action.
- Workspace Map: phase or tree progress visualization.
- Diagnostics: logs, raw state, config, changed files.
- Settings: setup/config wizard and tracking management.

### Visual Requirements

- The UI should make the loop state understandable at a glance.
- Use clear status language instead of raw enum names where possible.
- Use color intentionally:
  - green/teal for forward progress
  - amber for waiting or attention
  - red for regression or blocking
  - gray for idle/unknown
- Charts should annotate cause, not only plot numeric values.
- Empty states must explain what data is missing and what to do next.

## Migration Plan

1. Add React/Vite frontend under `dashboard/frontend`.
2. Add FastAPI static serving for `frontend/dist`.
3. Add new `/api/workspaces/*` view-model endpoints.
4. Implement Home and Workspace Overview first.
5. Implement progress chart and cause timeline from `rounds.jsonl`.
6. Implement next-action and human-required cards.
7. Implement diagnostics drawer.
8. Replace root route with React app.
9. Delete legacy `templates/index.html` and `static/app.js`.
10. Remove obsolete `/api/projects/*` endpoints after equivalent new endpoints exist.

## Acceptance Criteria

- `python -m dashboard.main` starts one local server and serves the new dashboard.
- A user can tell whether each workspace is moving forward, stuck, regressing, complete, or waiting for human action from the home screen.
- Workspace overview explains the current state in one sentence and gives a concrete next action.
- Progress chart uses `rounds.jsonl`, not logs, as the primary source.
- Human-required states show reason, evidence, and resume path.
- Logs and diffs are accessible only as diagnostics, not primary navigation.
- No legacy dashboard compatibility is required.

## Testing

- Unit tests for backend direction classification.
- Unit tests for `state.json` and `rounds.jsonl` normalization.
- API tests for `/api/workspaces`, `/overview`, `/timeline`, and `/progress`.
- Frontend component tests for direction cards, next-action card, and empty states.
- Manual verification with:
  - no projects
  - idle workspace
  - running workspace
  - progressing workspace
  - repeated failure/stalled workspace
  - human_required workspace
  - complete workspace

## Open Decisions

- Whether to require TypeScript for all frontend code from the start. (Highly recommended to ensure static typing and ease of refactoring from day one).
- Whether changed-file summaries should come from existing git inspection or wait for Feature 13 artifact records.
- Whether run-level summaries should wait for Feature 11 run session records or be inferred from existing `rounds.jsonl`.
