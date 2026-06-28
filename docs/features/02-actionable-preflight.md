# Feature 02: Actionable Preflight Results

## Type

Dashboard-only. Do not modify `engine/` or loop flow.

## Goal

Turn preflight from a passive checklist into a repair-oriented checklist with direct actions for failed checks.

## Problem

`GET /api/projects/{id}/preflight` already reports readiness checks, but users must manually know where to go next. Failed checks should show a direct remediation action.

## User Experience

Each preflight row should show:

- status: OK / Needs Review
- detail text
- optional action button

Suggested mapping:

| Check ID | Failed State Action |
| --- | --- |
| `requirements` | `View REQUIREMENTS.md` |
| `config_yaml` | `Open Config Editor` |
| `agent_config` | `Open Config Wizard` |
| `generation_mode` | `Open Config Wizard` |
| `run_lock` | `Clear Lock` if stale, otherwise `Open Logs` |
| `git_status` | `View Changes` |

## Implementation Plan

1. Update preflight rendering in `dashboard/templates/index.html`.
2. Map known check IDs to UI actions.
3. Keep the backend response unchanged unless more detail is needed.
4. Add clearer failed-state messages.
5. Ensure preflight reruns after config wizard save and clear lock.

## Acceptance Criteria

- Each failed preflight check has a useful action or explicitly says no automatic action exists.
- Clicking an action opens the correct tab/modal or calls the existing endpoint.
- Preflight summary still clearly shows Ready vs Needs Attention.
- No engine behavior changes.

## Tests

- Extend dashboard tests only if backend output changes.
- Manual verification with missing requirements, invalid config, placeholder config, dirty git, and stale lock.

