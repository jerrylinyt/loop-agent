# Feature 07: Documentation Quick Start and Troubleshooting

## Type

Docs-only.

## Goal

Provide clean, reliable documentation for first-time users and common recovery paths.

## Problem

The project has detailed documentation, but the top-level onboarding path should be shorter and more robust. Some files may have encoding/display issues in certain terminals. New users need a concise path and troubleshooting guide.

## Deliverables

1. Rewrite or add a clean `docs/quickstart.md`.
2. Add `docs/troubleshooting.md`.
3. Update top-level `README.md` to link to the new docs.
4. Add dashboard usage notes to `dashboard/README.md`.

## Quick Start Should Cover

- install dependencies
- initialize workspace
- confirm requirements
- configure agent command and models
- run gated mode
- run auto mode
- open dashboard

## Troubleshooting Should Cover

- requirements not confirmed
- config placeholders
- invalid YAML
- stale lock
- human required
- start button does nothing
- dashboard cannot see project
- dirty git state
- logs not appearing

## Acceptance Criteria

- A new user can follow quickstart from a clean clone.
- Troubleshooting entries include symptoms, cause, and fix.
- Documentation uses consistent UTF-8 text.
- No engine or dashboard behavior changes.

## Tests

- Manual docs walk-through on a temporary repo.
- Check links and commands.

