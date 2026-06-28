# Feature 06: Dashboard Onboarding Wizard

## Type

Dashboard-only wrapper around existing commands and endpoints.

## Goal

Provide a guided first-run flow without changing `init-project.py` or engine execution.

## Problem

New users must understand repo path, workspace name, requirements confirmation, config fields, preflight, and start modes. The dashboard has pieces of this flow, but they are separate.

## User Experience

Wizard steps:

1. Choose repository path.
2. Choose workspace name.
3. Initialize workspace using existing init endpoint.
4. Configure agent command and models using existing config wizard.
5. Show preflight result.
6. Offer Start or Finish.

The wizard should also support tracking an existing workspace.

## Implementation Plan

1. Add an onboarding modal or full-screen panel.
2. Reuse existing endpoints:
   - `POST /api/projects/init`
   - `POST /api/projects/add`
   - `POST /api/projects/{id}/config-wizard`
   - `GET /api/projects/{id}/preflight`
3. Persist wizard progress only in front-end state unless needed.
4. After successful init/track, select the workspace automatically.
5. Do not change init templates or engine flow.

## Acceptance Criteria

- A user can initialize and configure a workspace through the wizard.
- Existing Track and Init flows still work.
- Preflight appears before Start.
- Errors from existing endpoints are displayed clearly.
- No engine changes.

## Tests

- Manual flow with a temporary repo.
- Verify duplicate workspace and invalid path errors.
- Verify user can exit the wizard without corrupting project state.

